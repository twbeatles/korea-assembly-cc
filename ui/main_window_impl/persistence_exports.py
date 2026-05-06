# -*- coding: utf-8 -*-

import sys

from ui.main_window_common import *
from ui.main_window_common import _import_optional_module as _common_import_optional_module
from ui.main_window_types import MainWindowHost
from core.hwpx_export import save_hwpx_document


class MainWindowPersistenceExportsMixin(MainWindowHost):

    def _import_optional_module(self, module_name: str) -> Any:
            persistence_module = sys.modules.get("ui.main_window_persistence")
            helper = getattr(persistence_module, "_import_optional_module", None)
            if callable(helper):
                return helper(module_name)
            return _common_import_optional_module(module_name)

    def _save_in_background(
            self,
            save_func: Callable[[str], None],
            path: str,
            success_msg: str,
            error_prefix: str,
        ) -> None:
            """백그라운드에서 파일 저장 (자막 수집 중단 없이)

            Args:
                save_func: 실제 저장을 수행하는 함수 (path를 인자로 받음)
                path: 저장할 파일 경로
                success_msg: 성공 시 토스트 메시지
                error_prefix: 실패 시 에러 메시지 접두어
            """

            def background_save():
                try:
                    save_func(path)
                    # UI 스레드로 안전하게 전달 (Queue 기반)
                    self._emit_control_message(
                        "toast",
                        {"message": success_msg, "toast_type": "success"},
                    )
                except Exception as e:
                    logger.error(f"{error_prefix}: {e}")
                    self._emit_control_message(
                        "toast",
                        {
                            "message": f"{error_prefix}: {e}",
                            "toast_type": "error",
                            "duration": 5000,
                        },
                    )
            started = self._start_background_thread(background_save, "FileSaveWorker")
            if not started:
                self._show_toast("종료 중이라 새 저장 작업을 시작할 수 없습니다.", "warning")
                return

            # 저장 시작 알림 (즉시)
            self._show_toast(f"💾 저장 중... ({Path(path).name})", "info", 1500)

    def _get_accumulated_text(self):
            with self.subtitle_lock:
                return "\n".join(
                    text
                    for text in (
                        self._normalize_subtitle_text_for_option(s.text)
                        for s in self.subtitles
                    )
                    if text
                )

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
                        if should_print_ts:
                            handle.write(f"[{timestamp.strftime('%H:%M:%S')}] {text}\n")
                        else:
                            handle.write(f"{text}\n")

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
                    for index, (start_time, end_time, timestamp, text) in enumerate(
                        self._iter_full_session_timed_rows(
                            prepared_entries,
                            runtime_root=runtime_root,
                            runtime_manifest=runtime_manifest,
                        ),
                        1,
                    ):
                        if start_time and end_time:
                            start = f"{start_time.strftime('%H:%M:%S')},{start_time.microsecond // 1000:03d}"
                            end = f"{end_time.strftime('%H:%M:%S')},{end_time.microsecond // 1000:03d}"
                        else:
                            start = f"{timestamp.strftime('%H:%M:%S')},{timestamp.microsecond // 1000:03d}"
                            fallback_end = timestamp + timedelta(seconds=3)
                            end = f"{fallback_end.strftime('%H:%M:%S')},{fallback_end.microsecond // 1000:03d}"
                        handle.write(f"{index}\n{start} --> {end}\n{text}\n\n")

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
                    for index, (start_time, end_time, timestamp, text) in enumerate(
                        self._iter_full_session_timed_rows(
                            prepared_entries,
                            runtime_root=runtime_root,
                            runtime_manifest=runtime_manifest,
                        ),
                        1,
                    ):
                        if start_time and end_time:
                            start = f"{start_time.strftime('%H:%M:%S')}.{start_time.microsecond // 1000:03d}"
                            end = f"{end_time.strftime('%H:%M:%S')}.{end_time.microsecond // 1000:03d}"
                        else:
                            start = f"{timestamp.strftime('%H:%M:%S')}.{timestamp.microsecond // 1000:03d}"
                            fallback_end = timestamp + timedelta(seconds=3)
                            end = f"{fallback_end.strftime('%H:%M:%S')}.{fallback_end.microsecond // 1000:03d}"
                        handle.write(f"{index}\n{start} --> {end}\n{text}\n\n")

                utils.atomic_write_text_via_writer(filepath, writer, encoding="utf-8")

            self._save_in_background(do_save, path, "VTT 저장 완료!", "VTT 저장 실패")

    def _add_docx_multiline_text(self, paragraph: Any, text: str, break_types: Any) -> None:
            normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
            parts = normalized.split("\n")
            if not parts:
                paragraph.add_run("")
                return
            for index, part in enumerate(parts):
                paragraph.add_run(part)
                if index < len(parts) - 1:
                    paragraph.add_run().add_break(break_types.LINE)

    def _save_docx(self):
            """DOCX (Word) 파일로 저장"""
            prepared_entries = self._build_persistent_entries_snapshot()
            runtime_root, runtime_manifest = self._snapshot_runtime_stream_context()
            if not prepared_entries and not runtime_manifest:
                QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
                return

            try:
                docx_module = self._import_optional_module("docx")
                docx_shared = self._import_optional_module("docx.shared")
                docx_enum_text = self._import_optional_module("docx.enum.text")
            except ImportError:
                QMessageBox.warning(
                    self,
                    "라이브러리 필요",
                    "DOCX 저장을 위해 python-docx 라이브러리가 필요합니다.\n\n"
                    "설치: pip install python-docx",
                )
                return

            filename = self._generate_smart_filename("docx")
            path, _ = QFileDialog.getSaveFileName(
                self, "DOCX 저장", filename, "Word 문서 (*.docx)"
            )

            if not path:
                return

            generated_at = datetime.now().strftime("%Y년 %m월 %d일 %H:%M:%S")
            document_factory = cast(Callable[[], Any], docx_module.Document)
            point_factory = cast(Callable[[int], Any], docx_shared.Pt)
            paragraph_alignment = cast(Any, docx_enum_text.WD_ALIGN_PARAGRAPH)
            break_types = cast(Any, docx_enum_text.WD_BREAK)

            def do_save(filepath):
                doc = document_factory()

                title = doc.add_heading("국회 의사중계 자막", 0)
                title.alignment = paragraph_alignment.CENTER

                doc.add_paragraph(f"생성 일시: {generated_at}")
                doc.add_paragraph()

                total_count = 0
                total_chars = 0
                for timestamp, text, should_print_ts in self._iter_display_session_rows(
                    prepared_entries,
                    runtime_root=runtime_root,
                    runtime_manifest=runtime_manifest,
                ):
                    total_count += 1
                    total_chars += len(text)
                    paragraph = doc.add_paragraph()
                    if should_print_ts:
                        ts = timestamp.strftime("%H:%M:%S")
                        run = paragraph.add_run(f"[{ts}] ")
                        run.font.size = point_factory(9)
                        run.font.color.rgb = None
                    self._add_docx_multiline_text(paragraph, text, break_types)

                doc.add_paragraph()
                doc.add_paragraph(f"총 {total_count}문장, {total_chars:,}자")
                doc.save(filepath)

            self._save_in_background(do_save, path, "DOCX 저장 완료!", "DOCX 저장 실패")

    def _save_hwpx(self):
            """HWPX 파일로 저장"""
            prepared_entries = self._build_persistent_entries_snapshot()
            runtime_root, runtime_manifest = self._snapshot_runtime_stream_context()
            if not prepared_entries and not runtime_manifest:
                QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
                return

            filename = self._generate_smart_filename("hwpx")
            path, _ = QFileDialog.getSaveFileName(
                self, "HWPX 저장", filename, "한글 문서 (*.hwpx)"
            )

            if not path:
                return

            generated_at = datetime.now()

            def do_save(filepath):
                save_hwpx_document(
                    filepath,
                    self._iter_full_session_text_rows(
                        prepared_entries,
                        runtime_root=runtime_root,
                        runtime_manifest=runtime_manifest,
                    ),
                    generated_at,
                )

            self._save_in_background(do_save, path, "HWPX 저장 완료!", "HWPX 저장 실패")

    def _save_hwp(self):
            """HWP 파일로 저장 (Hancom Office 필요)"""
            prepared_entries = self._build_persistent_entries_snapshot()
            runtime_root, runtime_manifest = self._snapshot_runtime_stream_context()
            if not prepared_entries and not runtime_manifest:
                QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
                return

            try:
                win32_client = self._import_optional_module("win32com.client")
            except ImportError:
                QMessageBox.information(
                    self,
                    "HWP 대체 저장",
                    "한글(HWP) 저장은 Windows + pywin32 + 한컴오피스가 필요합니다.\n\n"
                    "HWPX 형식으로 저장합니다.\n"
                    "(.hwpx 파일은 한컴오피스 2018 이상에서 열 수 있습니다)",
                )
                self._save_hwpx()
                return

            filename = f"국회자막_{datetime.now().strftime('%Y%m%d_%H%M%S')}.hwp"
            path, _ = QFileDialog.getSaveFileName(
                self, "HWP 저장", filename, "HWP 문서 (*.hwp)"
            )

            if not path:
                return

            generated_at = datetime.now().strftime("%Y년 %m월 %d일 %H:%M:%S")

            def do_save(filepath):
                hwp = None
                pythoncom_module = None
                try:
                    try:
                        pythoncom_module = self._import_optional_module("pythoncom")
                        pythoncom_module.CoInitialize()
                    except Exception:
                        pythoncom_module = None

                    dynamic_dispatch = getattr(win32_client, "dynamic", None)
                    if dynamic_dispatch is not None:
                        hwp = cast(Any, dynamic_dispatch).Dispatch("HWPFrame.HwpObject")
                    else:
                        hwp = cast(Any, win32_client).Dispatch("HWPFrame.HwpObject")
                    hwp.XHwpWindows.Item(0).Visible = True
                    hwp.RegisterModule("FilePathCheckDLL", "SecurityModule")
                    hwp.HAction.Run("FileNew")
                    hwp.HAction.Run("CharShapeBold")
                    hwp.HAction.Run("ParagraphShapeAlignCenter")
                    hwp.HAction.GetDefault("InsertText", hwp.HParameterSet.HInsertText.HSet)
                    hwp.HParameterSet.HInsertText.Text = "국회 의사중계 자막\r\n"
                    hwp.HAction.Execute("InsertText", hwp.HParameterSet.HInsertText.HSet)
                    hwp.HAction.Run("CharShapeBold")
                    hwp.HAction.Run("ParagraphShapeAlignLeft")
                    hwp.HParameterSet.HInsertText.Text = f"생성 일시: {generated_at}\r\n\r\n"
                    hwp.HAction.Execute("InsertText", hwp.HParameterSet.HInsertText.HSet)

                    total_count = 0
                    total_chars = 0
                    for timestamp, text, should_print_ts in self._iter_display_session_rows(
                        prepared_entries,
                        runtime_root=runtime_root,
                        runtime_manifest=runtime_manifest,
                    ):
                        total_count += 1
                        total_chars += len(text)
                        if should_print_ts:
                            ts = timestamp.strftime("%H:%M:%S")
                            hwp.HParameterSet.HInsertText.Text = f"[{ts}] {text}\r\n"
                        else:
                            hwp.HParameterSet.HInsertText.Text = f"{text}\r\n"
                        hwp.HAction.Execute(
                            "InsertText", hwp.HParameterSet.HInsertText.HSet
                        )

                    hwp.HParameterSet.HInsertText.Text = (
                        f"\r\n총 {total_count}문장, {total_chars:,}자\r\n"
                    )
                    hwp.HAction.Execute("InsertText", hwp.HParameterSet.HInsertText.HSet)
                    hwp.HAction.GetDefault(
                        "FileSaveAs_S", hwp.HParameterSet.HFileOpenSave.HSet
                    )
                    hwp.HParameterSet.HFileOpenSave.filename = filepath
                    hwp.HParameterSet.HFileOpenSave.Format = "HWP"
                    hwp.HAction.Execute(
                        "FileSaveAs_S", hwp.HParameterSet.HFileOpenSave.HSet
                    )
                finally:
                    if hwp:
                        try:
                            hwp.Quit()
                        except Exception:
                            pass
                    if pythoncom_module:
                        try:
                            pythoncom_module.CoUninitialize()
                        except Exception:
                            pass

            def do_save_with_error(filepath):
                last_error: Exception | None = None
                for attempt in range(2):
                    try:
                        do_save(filepath)
                        saved_path = Path(filepath)
                        if not saved_path.exists() or saved_path.stat().st_size <= 0:
                            raise RuntimeError("저장된 파일을 확인할 수 없습니다.")
                        return
                    except Exception as e:
                        last_error = e
                        logger.warning(f"HWP 저장 재시도 실패 ({attempt + 1}/2): {e}")
                        time.sleep(1)
                if last_error is None:
                    last_error = RuntimeError("HWP 저장이 완료되지 않았습니다.")
                self._emit_control_message(
                    "hwp_save_failed",
                    {"error": str(last_error)},
                )
                raise last_error

            self._save_in_background(
                do_save_with_error, path, "HWP 저장 완료!", "HWP 저장 실패"
            )

    def _handle_hwp_save_failure(self, error: object) -> None:
            """HWP 저장 실패 시 대체 저장 안내"""
            error_msg = str(error).lower()
            logger.error(f"HWP 저장 실패: {error}")

            # 권한 문제 힌트 제공
            if "access denied" in error_msg or "권한" in str(error):
                advice = (
                    "\n\n관리자 권한으로 실행하거나 한글 프로그램을 먼저 실행해 보세요."
                )
            elif "server execution failed" in error_msg:
                advice = "\n\n한글 프로그램이 응답하지 않습니다. 한글을 종료하고 다시 시도하세요."
            else:
                advice = ""

            # 사용자에게 대체 저장 방식 제안
            reply = QMessageBox.question(
                self,
                "HWP 저장 실패",
                f"한글 파일 저장 중 오류가 발생했습니다: {error}{advice}\n\n"
                "대체 형식으로 저장하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )

            if reply == QMessageBox.StandardButton.Yes:
                items = ["HWPX (한글 호환, 권장)", "RTF (한글 호환)", "DOCX (Word)", "TXT (텍스트)"]
                item, ok = QInputDialog.getItem(
                    self, "형식 선택", "저장 형식:", items, 0, False
                )
                if ok and item:
                    if "HWPX" in item:
                        self._save_hwpx()
                    elif "RTF" in item:
                        self._save_rtf()
                    elif "DOCX" in item:
                        self._save_docx()
                    else:
                        self._save_txt()

    def _rtf_encode(self, text: str) -> str:
            """RTF 본문에 사용할 ASCII-safe 유니코드 문자열로 인코딩한다."""
            result = []
            normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
            for char in normalized:
                if char == "\\":
                    result.append("\\\\")
                elif char == "{":
                    result.append("\\{")
                elif char == "}":
                    result.append("\\}")
                elif char == "\n":
                    result.append("\\line ")
                elif char == "\t":
                    result.append("\\tab ")
                else:
                    codepoint = ord(char)
                    if 0x20 <= codepoint <= 0x7E:
                        result.append(char)
                        continue

                    utf16_units = char.encode("utf-16-le")
                    for idx in range(0, len(utf16_units), 2):
                        unit = int.from_bytes(
                            utf16_units[idx : idx + 2],
                            "little",
                            signed=False,
                        )
                        if unit >= 0x8000:
                            unit -= 0x10000
                        result.append(f"\\u{unit}?")
            return "".join(result)

    def _save_rtf(self):
            """RTF 파일로 저장 (HWP에서 열기 가능)"""
            prepared_entries = self._build_persistent_entries_snapshot()
            runtime_root, runtime_manifest = self._snapshot_runtime_stream_context()
            if not prepared_entries and not runtime_manifest:
                QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
                return

            filename = self._generate_smart_filename("rtf")
            path, _ = QFileDialog.getSaveFileName(
                self, "RTF 저장", filename, "RTF 문서 (*.rtf)"
            )

            if not path:
                return

            def do_save(filepath):
                total_count = 0
                total_chars = 0

                def writer(handle) -> None:
                    nonlocal total_count, total_chars
                    handle.write(b"{\\rtf1\\ansi\\deff0")
                    handle.write(b"{\\fonttbl{\\f0\\fnil\\fcharset0 Segoe UI;}}")
                    handle.write(
                        b"{\\colortbl;\\red0\\green0\\blue0;\\red128\\green128\\blue128;}\n"
                    )

                    title = self._rtf_encode("국회 의사중계 자막")
                    handle.write(f"\\pard\\qc\\b\\fs28 {title}\\b0\\par\n".encode("ascii"))

                    date_str = self._rtf_encode(
                        f"생성 일시: {datetime.now().strftime('%Y년 %m월 %d일 %H:%M:%S')}"
                    )
                    handle.write(f"\\pard\\ql\\fs20 {date_str}\\par\\par\n".encode("ascii"))

                    for timestamp, text in self._iter_full_session_text_rows(
                        prepared_entries,
                        runtime_root=runtime_root,
                        runtime_manifest=runtime_manifest,
                    ):
                        total_count += 1
                        total_chars += len(text)
                        encoded_text = self._rtf_encode(text)
                        handle.write(
                            (
                                f"\\cf2[{timestamp.strftime('%H:%M:%S')}]\\cf1 "
                                f"{encoded_text}\\par\n"
                            ).encode("ascii")
                        )

                    stats = self._rtf_encode(f"총 {total_count}문장, {total_chars:,}자")
                    handle.write(f"\\par\\fs18 {stats}\\par}}".encode("ascii"))

                utils.atomic_write_bytes_via_writer(filepath, writer)

            self._save_in_background(
                do_save,
                path,
                "RTF 저장 완료! (한글에서 열 수 있습니다)",
                "RTF 저장 실패",
            )

    def _save_session(self):
            if self._is_background_shutdown_active():
                self._show_toast("종료 중이라 세션 저장을 시작할 수 없습니다.", "warning")
                return

            prepared_entries = self._build_persistent_entries_snapshot()
            runtime_root, runtime_manifest = self._snapshot_runtime_stream_context()
            has_subtitles = bool(prepared_entries) or bool(runtime_manifest)
            if not has_subtitles:
                QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
                return

            if self._session_save_in_progress:
                self._show_toast("이미 세션 저장이 진행 중입니다.", "info")
                return

            try:
                path = self._choose_session_snapshot_path(dialog_title="세션 저장")
            except Exception as e:
                QMessageBox.critical(self, "오류", f"세션 저장 경로 준비 실패: {e}")
                return
            if not path:
                return
            self._start_async_session_snapshot_save(
                path,
                prepared_entries,
                runtime_root=runtime_root,
                runtime_manifest=runtime_manifest,
            )
