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



from ui.main_window_impl.persistence_exports_dispatch import ExportFailureHandled


class MainWindowPersistenceExportsDocumentsMixin(MainWindowHost):
    """문서 계열 내보내기 (SRP: DOCX/HWPX/HWP/RTF)."""

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
                    safe_text = sanitize_document_text(text)
                    if not safe_text.strip():
                        continue
                    total_count += 1
                    total_chars += len(safe_text)
                    paragraph = doc.add_paragraph()
                    if should_print_ts:
                        ts = timestamp.strftime("%H:%M:%S")
                        run = paragraph.add_run(f"[{ts}] ")
                        run.font.size = point_factory(9)
                        run.font.color.rgb = None
                    self._add_docx_multiline_text(paragraph, safe_text, break_types)

                doc.add_paragraph()
                doc.add_paragraph(f"총 {total_count}문장, {total_chars:,}자")

                # 비원자적 doc.save 대신 임시 파일 후 replace (부분 손상 파일 방지)
                target = Path(filepath)
                target.parent.mkdir(parents=True, exist_ok=True)
                fd, temp_path = tempfile.mkstemp(
                    prefix=f".{target.name}.",
                    suffix=".docx.tmp",
                    dir=str(target.parent),
                )
                os.close(fd)
                temp_file = Path(temp_path)
                try:
                    doc.save(str(temp_file))
                    os.replace(str(temp_file), str(target))
                except Exception:
                    try:
                        temp_file.unlink(missing_ok=True)
                    except Exception:
                        pass
                    raise

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

            filename = self._generate_smart_filename("hwp")
            path, _ = QFileDialog.getSaveFileName(
                self, "HWP 저장", filename, "HWP 문서 (*.hwp)"
            )

            if not path:
                return

            generated_at = datetime.now().strftime("%Y년 %m월 %d일 %H:%M:%S")

            # 대용량은 COM InsertText 가 매우 느려 HWPX 권장
            approx_count = len(prepared_entries) + sum(
                int(item.get("entry_count") or 0)
                for item in (runtime_manifest or [])
                if isinstance(item, dict)
            )
            if approx_count >= 2000:
                reply = QMessageBox.question(
                    self,
                    "대용량 HWP 저장",
                    f"자막 약 {approx_count:,}건입니다.\n"
                    "HWP(COM) 저장은 수 분 이상 걸릴 수 있습니다.\n\n"
                    "권장: HWPX로 저장할까요?\n"
                    "(예=HWPX, 아니오=HWP 계속)",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self._save_hwpx()
                    return

            def do_save(filepath):
                hwp_obj: Any | None = None
                pythoncom_module = None
                try:
                    try:
                        pythoncom_module = self._import_optional_module("pythoncom")
                        pythoncom_module.CoInitialize()
                    except Exception:
                        pythoncom_module = None

                    dynamic_dispatch = getattr(win32_client, "dynamic", None)
                    if dynamic_dispatch is not None:
                        hwp_obj = cast(Any, dynamic_dispatch).Dispatch("HWPFrame.HwpObject")
                    else:
                        hwp_obj = cast(Any, win32_client).Dispatch("HWPFrame.HwpObject")
                    # nested insert_text 가 non-optional 로 참조하도록 로컬 바인딩
                    hwp: Any = hwp_obj

                    def insert_text(value: str) -> None:
                        """한컴 일부 버전은 InsertText 전 GetDefault 재호출이 필요하다."""
                        hwp.HAction.GetDefault(
                            "InsertText", hwp.HParameterSet.HInsertText.HSet
                        )
                        hwp.HParameterSet.HInsertText.Text = value
                        hwp.HAction.Execute(
                            "InsertText", hwp.HParameterSet.HInsertText.HSet
                        )

                    # 가능하면 숨김 창 — 실패 시 Visible=True 폴백
                    try:
                        hwp.XHwpWindows.Item(0).Visible = False
                    except Exception:
                        try:
                            hwp.XHwpWindows.Item(0).Visible = True
                        except Exception:
                            pass
                    hwp.RegisterModule("FilePathCheckDLL", "SecurityModule")
                    hwp.HAction.Run("FileNew")
                    hwp.HAction.Run("CharShapeBold")
                    hwp.HAction.Run("ParagraphShapeAlignCenter")
                    insert_text("국회 의사중계 자막\r\n")
                    hwp.HAction.Run("CharShapeBold")
                    hwp.HAction.Run("ParagraphShapeAlignLeft")
                    insert_text(f"생성 일시: {generated_at}\r\n\r\n")

                    total_count = 0
                    total_chars = 0
                    for timestamp, text, should_print_ts in self._iter_display_session_rows(
                        prepared_entries,
                        runtime_root=runtime_root,
                        runtime_manifest=runtime_manifest,
                    ):
                        safe_text = normalize_hwp_insert_text(text)
                        if not safe_text.strip():
                            continue
                        total_count += 1
                        total_chars += len(safe_text.replace("\r\n", "\n"))
                        if should_print_ts:
                            ts = timestamp.strftime("%H:%M:%S")
                            insert_text(f"[{ts}] {safe_text}\r\n")
                        else:
                            insert_text(f"{safe_text}\r\n")

                    if total_count <= 0:
                        raise RuntimeError("저장할 유효 자막이 없습니다.")

                    insert_text(f"\r\n총 {total_count}문장, {total_chars:,}자\r\n")
                    hwp.HAction.GetDefault(
                        "FileSaveAs_S", hwp.HParameterSet.HFileOpenSave.HSet
                    )
                    hwp.HParameterSet.HFileOpenSave.filename = filepath
                    hwp.HParameterSet.HFileOpenSave.Format = "HWP"
                    hwp.HAction.Execute(
                        "FileSaveAs_S", hwp.HParameterSet.HFileOpenSave.HSet
                    )
                finally:
                    if hwp_obj is not None:
                        try:
                            hwp_obj.Quit()
                        except Exception:
                            pass
                    if pythoncom_module:
                        try:
                            pythoncom_module.CoUninitialize()
                        except Exception:
                            pass

            def do_save_with_error(filepath):
                last_error: Exception | None = None
                stop_event = self.__dict__.get("stop_event")
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
                        if stop_event is not None and hasattr(stop_event, "wait"):
                            if stop_event.wait(timeout=1.0):
                                break
                        else:
                            time.sleep(1)
                if last_error is None:
                    last_error = RuntimeError("HWP 저장이 완료되지 않았습니다.")
                # UI 다이얼로그만 사용 — 백그라운드 에러 토스트와 이중 통지 방지
                self._emit_control_message(
                    "hwp_save_failed",
                    {"error": str(last_error)},
                )
                raise ExportFailureHandled(str(last_error)) from last_error

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
                        safe_text = sanitize_document_text(text)
                        if not safe_text.strip():
                            continue
                        total_count += 1
                        total_chars += len(safe_text)
                        encoded_text = self._rtf_encode(safe_text)
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
