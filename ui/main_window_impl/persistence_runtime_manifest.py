# -*- coding: utf-8 -*-

import hashlib
import bisect
import shutil
from typing import Any, Iterable, cast
from uuid import uuid4

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt, QTimer

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost

QProgressDialog = cast(Any, getattr(QtWidgets, "QProgressDialog"))


class MainWindowRuntimeManifestMixin(MainWindowHost):

    def _load_runtime_manifest_payload(
            self,
            path: str | Path,
            *,
            allow_salvage: bool = False,
        ) -> dict[str, Any]:
            manifest_path = Path(path)
            runtime_root = manifest_path.parent
            all_entries: list[SubtitleEntry] = []
            skipped = 0
            skipped_files = 0
            warnings: list[str] = []
            manifest: dict[str, Any] = {}
            manifest_loaded = False

            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    loaded_manifest = json.load(f)
                if not isinstance(loaded_manifest, dict):
                    raise ValueError("지원하지 않는 runtime manifest 구조입니다.")
                if str(loaded_manifest.get("format", "") or "") != "runtime_session_manifest_v1":
                    raise ValueError("지원하지 않는 runtime manifest 형식입니다.")
                manifest = loaded_manifest
                manifest_loaded = True
            except Exception as exc:
                if not allow_salvage:
                    raise
                skipped_files += 1
                warnings.append(f"manifest 복구 전환: {exc}")

            def adopt_meta(raw_data: dict[str, Any] | None) -> None:
                nonlocal manifest
                if not isinstance(raw_data, dict):
                    return
                if not str(manifest.get("created", "") or "").strip():
                    manifest["created"] = str(raw_data.get("created", "") or "")
                if not str(manifest.get("url", "") or "").strip():
                    manifest["url"] = str(raw_data.get("url", "") or "")
                if not str(manifest.get("committee_name", "") or "").strip():
                    manifest["committee_name"] = str(raw_data.get("committee_name", "") or "")
                if not str(manifest.get("version", "") or "").strip():
                    manifest["version"] = str(raw_data.get("version", "") or "unknown")
                if not str(manifest.get("lineage_id", "") or "").strip():
                    manifest["lineage_id"] = str(raw_data.get("lineage_id", "") or "")

            segments = manifest.get("segments", [])
            if manifest_loaded and not isinstance(segments, list):
                if not allow_salvage:
                    raise ValueError("runtime manifest segments 구조가 올바르지 않습니다.")
                skipped_files += 1
                warnings.append("manifest segments 구조가 손상되어 sibling scan으로 대체합니다.")
                segments = self._build_salvaged_runtime_segments(runtime_root)
            elif not manifest_loaded:
                segments = self._build_salvaged_runtime_segments(runtime_root)

            for segment in segments if isinstance(segments, list) else []:
                relative_path = str(
                    getattr(segment, "get", lambda *_args, **_kwargs: "")("path", "") or ""
                )
                if not relative_path:
                    if allow_salvage:
                        skipped_files += 1
                        warnings.append("path가 없는 runtime segment를 건너뜁니다.")
                    continue
                try:
                    segment_path, safe_relative_path = self._resolve_runtime_relative_path(
                        runtime_root,
                        relative_path,
                        source="runtime segment",
                    )
                except ValueError as exc:
                    if not allow_salvage:
                        raise
                    skipped_files += 1
                    warnings.append(str(exc))
                    continue
                raw_data, segment_entries, segment_skipped, segment_error = (
                    self._try_load_runtime_entries_file(
                        segment_path,
                        source=f"runtime_manifest:{safe_relative_path}",
                        cache_result=True,
                    )
                )
                if segment_error:
                    if not allow_salvage:
                        raise ValueError(segment_error)
                    skipped_files += 1
                    warnings.append(segment_error)
                    continue
                adopt_meta(raw_data)
                skipped += segment_skipped
                all_entries.extend(entry.clone() for entry in segment_entries)

            checkpoint_relative = str(
                manifest.get("tail_checkpoint", "tail_checkpoint.json")
                or "tail_checkpoint.json"
            )
            checkpoint_path: Path | None = None
            try:
                checkpoint_path, safe_checkpoint_relative = self._resolve_runtime_relative_path(
                    runtime_root,
                    checkpoint_relative,
                    source="runtime tail checkpoint",
                )
            except ValueError as exc:
                if not allow_salvage:
                    raise
                skipped_files += 1
                warnings.append(str(exc))
                safe_checkpoint_relative = checkpoint_relative
            if checkpoint_path is not None and checkpoint_path.exists():
                checkpoint_data, tail_entries, tail_skipped, checkpoint_error = (
                    self._try_load_runtime_entries_file(
                        checkpoint_path,
                        source=f"runtime_tail:{checkpoint_path}",
                    )
                )
                if checkpoint_error:
                    if not allow_salvage:
                        raise ValueError(checkpoint_error)
                    skipped_files += 1
                    warnings.append(checkpoint_error)
                else:
                    adopt_meta(checkpoint_data)
                    skipped += tail_skipped
                    all_entries.extend(tail_entries)
            elif checkpoint_path is not None and allow_salvage:
                skipped_files += 1
                warnings.append(f"{safe_checkpoint_relative} 이(가) 없어 tail 복구를 건너뜁니다.")
            elif checkpoint_path is not None and manifest_loaded:
                raise ValueError(f"{safe_checkpoint_relative} 이(가) 없습니다.")

            if not all_entries:
                warning_text = " / ".join(warnings)
                if warning_text:
                    raise ValueError(f"복구 가능한 runtime 자막이 없습니다. ({warning_text})")
                raise ValueError("복구 가능한 runtime 자막이 없습니다.")

            payload = {
                "version": manifest.get("version", "unknown"),
                "created_at": manifest.get("created", ""),
                "url": manifest.get("url", ""),
                "committee_name": manifest.get("committee_name", ""),
                "lineage_id": manifest.get("lineage_id", ""),
                "subtitles": all_entries,
                "skipped": skipped,
                "runtime_manifest": True,
                "path": str(manifest_path),
            }
            if skipped_files > 0:
                payload["skipped_files"] = skipped_files
            if warnings:
                payload["recovery_warnings"] = warnings
            return payload
