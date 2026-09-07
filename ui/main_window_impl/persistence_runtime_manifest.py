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
from core.models import CaptureQualityState
from core.resource_budget import ResourceBudget, ResourceBudgetLimits, ResourceLimitExceeded

QProgressDialog = cast(Any, getattr(QtWidgets, "QProgressDialog"))


class MainWindowRuntimeManifestMixin(MainWindowHost):

    def _adopt_runtime_tail_entries(
            self,
            loaded_entries: list[SubtitleEntry],
            tail_entries: list[SubtitleEntry],
            *,
            manifest: dict[str, Any],
            checkpoint_data: dict[str, Any],
            allow_salvage: bool,
        ) -> tuple[list[SubtitleEntry], str | None]:
            def _optional_int(payload: dict[str, Any], key: str) -> int | None:
                if key not in payload or payload.get(key) is None:
                    return None
                try:
                    return int(payload.get(key, 0) or 0)
                except Exception:
                    return None

            manifest_generation = _optional_int(manifest, "checkpoint_generation")
            tail_generation = _optional_int(checkpoint_data, "checkpoint_generation")
            manifest_archived = _optional_int(manifest, "archived_count")
            tail_archived = _optional_int(checkpoint_data, "archived_count")
            generation_mismatch = (
                manifest_generation is not None
                and tail_generation is not None
                and manifest_generation != tail_generation
            )
            archived_mismatch = (
                manifest_archived is not None
                and tail_archived is not None
                and manifest_archived != tail_archived
            )
            if not generation_mismatch and not archived_mismatch:
                return list(tail_entries), None

            mismatch = "checkpoint generation mismatch"
            loaded_ids = {
                str(entry.entry_id)
                for entry in loaded_entries
                if str(entry.entry_id or "")
            }
            skip = 0
            for entry in tail_entries:
                entry_id = str(entry.entry_id or "")
                if entry_id and entry_id in loaded_ids:
                    skip += 1
                    continue
                break
            if skip <= 0:
                if not allow_salvage:
                    raise ValueError(mismatch)
                return [], mismatch
            return list(tail_entries[skip:]), mismatch

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
            budget = ResourceBudget(
                ResourceBudgetLimits(
                    per_file_bytes=int(Config.SESSION_RESOURCE_PER_FILE_MAX_BYTES),
                    total_bytes=int(Config.SESSION_RESOURCE_TOTAL_MAX_BYTES),
                    max_entries=int(Config.SESSION_RESOURCE_MAX_ENTRIES),
                    max_segments=int(Config.SESSION_RESOURCE_MAX_SEGMENTS),
                )
            )

            try:
                budget.consume_file(manifest_path.stat().st_size, label="runtime manifest")
                with open(manifest_path, "r", encoding="utf-8") as f:
                    loaded_manifest = json.load(f)
                if not isinstance(loaded_manifest, dict):
                    raise ValueError("지원하지 않는 runtime manifest 구조입니다.")
                if str(loaded_manifest.get("format", "") or "") != "runtime_session_manifest_v1":
                    raise ValueError("지원하지 않는 runtime manifest 형식입니다.")
                manifest = loaded_manifest
                manifest_loaded = True
            except ResourceLimitExceeded:
                raise
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

            for segment_index, segment in enumerate(
                segments if isinstance(segments, list) else [],
                start=1,
            ):
                budget.consume_segment()
                if not isinstance(segment, dict):
                    structure_error = (
                        f"runtime segment #{segment_index} 구조가 올바르지 않습니다."
                    )
                    if not allow_salvage:
                        raise ValueError(structure_error)
                    skipped_files += 1
                    warnings.append(structure_error)
                    continue
                relative_path = str(segment.get("path", "") or "")
                if not relative_path:
                    path_error = (
                        f"runtime segment #{segment_index} path가 비어 있어 건너뜁니다."
                    )
                    if not allow_salvage:
                        raise ValueError(path_error)
                    if allow_salvage:
                        skipped_files += 1
                        warnings.append(path_error)
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
                        cache_result=False,
                        budget=budget,
                    )
                )
                if segment_error:
                    if not allow_salvage:
                        raise ValueError(segment_error)
                    skipped_files += 1
                    warnings.append(segment_error)
                    continue
                integrity_errors = [
                    error
                    for error in (
                        self._runtime_entries_integrity_error(
                            segment_entries,
                            segment,
                            source=f"{safe_relative_path} manifest",
                        ),
                        self._runtime_entries_integrity_error(
                            segment_entries,
                            raw_data,
                            source=f"{safe_relative_path} file",
                        ),
                    )
                    if error
                ]
                if integrity_errors:
                    integrity_error = " / ".join(integrity_errors)
                    if not allow_salvage:
                        raise ValueError(integrity_error)
                    skipped_files += 1
                    warnings.append(integrity_error)
                    continue
                try:
                    self._cache_runtime_segment_entries(
                        str(segment_path.resolve()),
                        segment_entries,
                    )
                except Exception:
                    logger.debug(
                        "runtime segment cache 반영 실패: %s",
                        segment_path,
                        exc_info=True,
                    )
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
                        budget=budget,
                    )
                )
                if checkpoint_error:
                    if not allow_salvage:
                        raise ValueError(checkpoint_error)
                    skipped_files += 1
                    warnings.append(checkpoint_error)
                else:
                    integrity_error = self._runtime_entries_integrity_error(
                        tail_entries,
                        checkpoint_data,
                        source=f"{safe_checkpoint_relative} file",
                    )
                    if integrity_error:
                        if not allow_salvage:
                            raise ValueError(integrity_error)
                        skipped_files += 1
                        warnings.append(integrity_error)
                    else:
                        adopt_meta(checkpoint_data)
                        skipped += tail_skipped
                        adopted_tail, tail_warning = self._adopt_runtime_tail_entries(
                            all_entries,
                            tail_entries,
                            manifest=manifest,
                            checkpoint_data=checkpoint_data if isinstance(checkpoint_data, dict) else {},
                            allow_salvage=allow_salvage,
                        )
                        if tail_warning:
                            if not allow_salvage:
                                raise ValueError(tail_warning)
                            warnings.append(tail_warning)
                        all_entries.extend(adopted_tail)
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
                "resource_usage": budget.summary(),
            }
            if skipped_files > 0:
                payload["skipped_files"] = skipped_files
            quality = CaptureQualityState.from_mapping(
                manifest.get("capture_quality", {})
            )
            quality.salvage_skipped_files += skipped_files
            payload["capture_quality"] = quality.to_dict()
            if warnings:
                payload["recovery_warnings"] = warnings
            return payload
