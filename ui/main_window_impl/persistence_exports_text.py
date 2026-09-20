# -*- coding: utf-8 -*-

import os
import sys
import tempfile
import threading
from pathlib import Path

from ui.main_window_common import *
from ui.main_window_common import _import_optional_module as _common_import_optional_module
from ui.main_window_types import MainWindowHost
from core.export_text import (
    format_srt_relative,
    format_vtt_relative,
    normalize_hwp_insert_text,
    resolve_cue_time_range,
    sanitize_document_text,
    sanitize_subtitle_cue_text,
)
from core.hwpx_export import save_hwpx_document
from core.file_io import canonical_path_key


class MainWindowPersistenceExportsTextMixin(MainWindowHost):
    """텍스트 계열 내보내기 (SRP: TXT/SRT/VTT/통계)."""

    def _export_stats(self):
            """자막 통계 내보내기"""
            prepared_entries = self._build_persistent_entries_snapshot()
            runtime_root, runtime_manifest = self._snapshot_runtime_stream_context()
            if not prepared_entries and not runtime_manifest:
                QMessageBox.warning(self, "알림", "내보낼 내용이 없습니다.")
                return

            keywords_snapshot = [
                (keyword, keyword.lower())
                for keyword in list(self.keywords)
                if str(keyword or "").strip()
            ]

            filename = f"자막통계_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            path, _ = QFileDialog.getSaveFileName(
                self, "통계 내보내기", filename, "텍스트 (*.txt)"
            )

            if not path:
                return

            def do_save(filepath):
                total_count = 0
                total_chars = 0
                total_words = 0
                hour_counts: dict[int, int] = {}
                longest_text = ""
                shortest_text = ""
                keyword_counts = {keyword: 0 for keyword, _ in keywords_snapshot}

                for entry in self._iter_full_session_entries(
                    prepared_entries,
                    runtime_root=runtime_root,
                    runtime_manifest=runtime_manifest,
                ):
                    text = str(entry.text or "")
                    total_count += 1
                    total_chars += len(text)
                    total_words += len(text.split())
                    hour = entry.timestamp.hour
                    hour_counts[hour] = hour_counts.get(hour, 0) + 1
                    if not longest_text or len(text) > len(longest_text):
                        longest_text = text
                    if not shortest_text or len(text) < len(shortest_text):
                        shortest_text = text
                    lowered_text = text.lower()
                    for keyword, lowered_keyword in keywords_snapshot:
                        keyword_counts[keyword] += lowered_text.count(lowered_keyword)

                if total_count <= 0:
                    raise RuntimeError("내보낼 내용이 없습니다.")

                generated_at = datetime.now().strftime("%Y년 %m월 %d일 %H:%M:%S")

                def writer(handle) -> None:
                    handle.write("=" * 50 + "\n")
                    handle.write("        국회 자막 통계 보고서\n")
                    handle.write("=" * 50 + "\n\n")
                    handle.write(f"생성 일시: {generated_at}\n\n")
                    handle.write("■ 기본 통계\n")
                    handle.write("-" * 30 + "\n")
                    handle.write(f"  총 문장 수: {total_count:,}개\n")
                    handle.write(f"  총 글자 수: {total_chars:,}자\n")
                    handle.write(f"  총 공백 기준 단어 수: {total_words:,}개\n")
                    handle.write(f"  평균 문장 길이: {total_chars / total_count:.1f}자\n")
                    handle.write(f"  평균 공백 기준 단어 수: {total_words / total_count:.1f}개\n\n")
                    handle.write("■ 문장 분석\n")
                    handle.write("-" * 30 + "\n")
                    handle.write(f"  가장 긴 문장: {len(longest_text)}자\n")
                    preview_long = longest_text[:50] + ("..." if len(longest_text) > 50 else "")
                    handle.write(f'    "{preview_long}"\n')
                    handle.write(f"  가장 짧은 문장: {len(shortest_text)}자\n")
                    handle.write(f'    "{shortest_text}"\n\n')

                    if hour_counts:
                        handle.write("■ 시간대별 분포\n")
                        handle.write("-" * 30 + "\n")
                        for hour in sorted(hour_counts.keys()):
                            bar = "■" * min(hour_counts[hour] // 2, 20)
                            handle.write(f"  {hour:02d}시 {bar} {hour_counts[hour]}개\n")
                        handle.write("\n")

                    if keywords_snapshot:
                        handle.write("■ 키워드 빈도\n")
                        handle.write("-" * 30 + "\n")
                        for keyword, _lowered in keywords_snapshot:
                            count = keyword_counts.get(keyword, 0)
                            if count > 0:
                                handle.write(f"  {keyword}: {count}회\n")
                        handle.write("\n")

                    handle.write("=" * 50 + "\n")

                utils.atomic_write_text_via_writer(filepath, writer, encoding="utf-8")

            self._save_in_background(
                do_save,
                path,
                "통계 내보내기 완료!",
                "통계 저장 실패",
            )

    def _generate_smart_filename(self, extension: str) -> str:
            """URL과 현재 시간 기반 스마트 파일명 생성 (#28)"""
            # 위원회명 추출 (현재 URL에서 자동 감지)
            current_url = self._get_capture_source_url(fallback_to_current=True)
            committee_name = self._get_capture_source_committee(fallback_to_url=True)
            return utils.generate_filename(committee_name, extension)

    def _save_txt(self):
            prepared_entries = self._build_persistent_entries_snapshot()
            runtime_root, runtime_manifest = self._snapshot_runtime_stream_context()
            if not prepared_entries and not runtime_manifest:
                QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
                return

            filename = self._generate_smart_filename("txt")
            path, _ = QFileDialog.getSaveFileName(
                self, "TXT 저장", filename, "텍스트 (*.txt)"
            )

            if not path:
                return

            def do_save(filepath):
                def writer(handle) -> None:
                    for timestamp, text, should_print_ts in self._iter_display_session_rows(
                        prepared_entries,
                        runtime_root=runtime_root,
                        runtime_manifest=runtime_manifest,
                    ):
                        safe_text = sanitize_document_text(text)
                        if not safe_text.strip():
                            continue
                        if should_print_ts:
                            handle.write(f"[{timestamp.strftime('%H:%M:%S')}] {safe_text}\n")
                        else:
                            handle.write(f"{safe_text}\n")

                utils.atomic_write_text_via_writer(
                    filepath,
                    writer,
                    encoding="utf-8-sig",
                )

            self._save_in_background(do_save, path, "TXT 저장 완료!", "TXT 저장 실패")

    def _save_srt(self):
            prepared_entries = self._build_persistent_entries_snapshot()
            runtime_root, runtime_manifest = self._snapshot_runtime_stream_context()
            if not prepared_entries and not runtime_manifest:
                QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
                return

            filename = self._generate_smart_filename("srt")
            path, _ = QFileDialog.getSaveFileName(
                self, "SRT 저장", filename, "SubRip (*.srt)"
            )

            if not path:
                return

            def do_save(filepath):
                def writer(handle) -> None:
                    cue_index = 0
                    base_time = None
                    for start_time, end_time, timestamp, text in self._iter_full_session_timed_rows(
                        prepared_entries,
                        runtime_root=runtime_root,
                        runtime_manifest=runtime_manifest,
                    ):
                        cue_text = sanitize_subtitle_cue_text(text)
                        if not cue_text:
                            continue
                        cue_start, cue_end = resolve_cue_time_range(
                            start_time, end_time, timestamp
                        )
                        if base_time is None:
                            base_time = cue_start
                        cue_index += 1
                        start = format_srt_relative(
                            (cue_start - base_time).total_seconds()
                        )
                        end = format_srt_relative(
                            (cue_end - base_time).total_seconds()
                        )
                        handle.write(f"{cue_index}\n{start} --> {end}\n{cue_text}\n\n")
                    if cue_index <= 0:
                        raise RuntimeError("저장할 유효 자막이 없습니다.")

                utils.atomic_write_text_via_writer(filepath, writer, encoding="utf-8")

            self._save_in_background(do_save, path, "SRT 저장 완료!", "SRT 저장 실패")

    def _save_vtt(self):
            prepared_entries = self._build_persistent_entries_snapshot()
            runtime_root, runtime_manifest = self._snapshot_runtime_stream_context()
            if not prepared_entries and not runtime_manifest:
                QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
                return

            filename = self._generate_smart_filename("vtt")
            path, _ = QFileDialog.getSaveFileName(
                self, "VTT 저장", filename, "WebVTT (*.vtt)"
            )

            if not path:
                return

            def do_save(filepath):
                def writer(handle) -> None:
                    handle.write("WEBVTT\n\n")
                    cue_index = 0
                    base_time = None
                    for start_time, end_time, timestamp, text in self._iter_full_session_timed_rows(
                        prepared_entries,
                        runtime_root=runtime_root,
                        runtime_manifest=runtime_manifest,
                    ):
                        cue_text = sanitize_subtitle_cue_text(text)
                        if not cue_text:
                            continue
                        cue_start, cue_end = resolve_cue_time_range(
                            start_time, end_time, timestamp
                        )
                        if base_time is None:
                            base_time = cue_start
                        cue_index += 1
                        start = format_vtt_relative(
                            (cue_start - base_time).total_seconds()
                        )
                        end = format_vtt_relative(
                            (cue_end - base_time).total_seconds()
                        )
                        handle.write(f"{cue_index}\n{start} --> {end}\n{cue_text}\n\n")
                    if cue_index <= 0:
                        raise RuntimeError("저장할 유효 자막이 없습니다.")

                utils.atomic_write_text_via_writer(filepath, writer, encoding="utf-8")

            self._save_in_background(do_save, path, "VTT 저장 완료!", "VTT 저장 실패")
