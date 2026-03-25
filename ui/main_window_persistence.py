# -*- coding: utf-8 -*-

from ui.main_window_common import *
from ui.main_window_common import _import_optional_module
from ui.main_window_types import MainWindowHost
from core.hwpx_export import save_hwpx_document


class MainWindowPersistenceMixin(MainWindowHost):

    def _auto_backup(self):
            """자동 백업 실행"""
            prepared_entries = self._build_prepared_entries_snapshot()
            if not prepared_entries:
                return

            # UI 스레드가 멈추지 않도록(긴 세션/대용량) 파일 I/O는 백그라운드에서 처리
            if not self._auto_backup_lock.acquire(blocking=False):
                return  # 이미 백업 중

            try:
                backup_dir = Path(Config.BACKUP_DIR)
                backup_dir.mkdir(exist_ok=True)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_file = backup_dir / f"backup_{timestamp}.json"
                created_at = datetime.now().isoformat()
                current_url = self._get_current_url()

            except Exception as e:
                try:
                    self._auto_backup_lock.release()
                except Exception:
                    pass
                logger.error(f"자동 백업 준비 오류: {e}")
                return

            def write_backup():
                try:
                    utils.atomic_write_json_stream(
                        backup_file,
                        head_items=[
                            ("version", Config.VERSION),
                            ("created", created_at),
                            ("url", current_url),
                        ],
                        sequence_key="subtitles",
                        sequence_items=utils.iter_serialized_subtitles(prepared_entries),
                        ensure_ascii=False,
                    )

                    # 오래된 백업 삭제 (최대 개수 유지)
                    self._cleanup_old_backups()

                    logger.info(f"자동 백업 완료: {backup_file}")
                except Exception as e:
                    logger.error(f"자동 백업 오류: {e}")
                finally:
                    try:
                        self._auto_backup_lock.release()
                    except Exception:
                        pass

            started = self._start_background_thread(write_backup, "AutoBackupWorker")
            if not started:
                try:
                    self._auto_backup_lock.release()
                except Exception:
                    pass
                logger.info("종료 단계로 자동 백업 시작 생략")


    def _cleanup_old_backups(self):
            """오래된 백업 파일 정리"""
            try:
                backup_dir = Path(Config.BACKUP_DIR)
                backups = sorted(backup_dir.glob("backup_*.json"), reverse=True)

                # 최대 개수 초과분 삭제
                for old_backup in backups[Config.MAX_BACKUP_COUNT :]:
                    old_backup.unlink()
                    logger.debug(f"오래된 백업 삭제: {old_backup}")
            except Exception as e:
                logger.warning(f"백업 정리 중 오류: {e}")


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
                    self.message_queue.put(
                        ("toast", {"message": success_msg, "toast_type": "success"})
                    )
                except Exception as e:
                    logger.error(f"{error_prefix}: {e}")
                    self.message_queue.put(
                        (
                            "toast",
                            {
                                "message": f"{error_prefix}: {e}",
                                "toast_type": "error",
                                "duration": 5000,
                            },
                        )
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
            subtitles_snapshot = self._build_prepared_entries_snapshot()
            prepared_subtitles_snapshot = list(subtitles_snapshot)
            if not subtitles_snapshot:
                QMessageBox.warning(self, "알림", "내보낼 내용이 없습니다.")
                return

            # 스레드 안전하게 자막 스냅샷 생성
            with self.subtitle_lock:
                subtitles_snapshot = list(self.subtitles)
            subtitles_snapshot = prepared_subtitles_snapshot
            if not subtitles_snapshot:
                QMessageBox.warning(self, "알림", "내보낼 내용이 없습니다.")
                return
            keywords_snapshot = list(self.keywords)

            # 파일 저장
            filename = f"자막통계_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            path, _ = QFileDialog.getSaveFileName(
                self, "통계 내보내기", filename, "텍스트 (*.txt)"
            )

            if path:
                def do_save(filepath):
                    # 통계 계산
                    total_chars = sum(len(s.text) for s in subtitles_snapshot)
                    total_words = sum(len(s.text.split()) for s in subtitles_snapshot)

                    hour_counts = {}
                    for entry in subtitles_snapshot:
                        hour = entry.timestamp.hour
                        hour_counts[hour] = hour_counts.get(hour, 0) + 1

                    longest = max(subtitles_snapshot, key=lambda s: len(s.text))
                    shortest = min(subtitles_snapshot, key=lambda s: len(s.text))

                    generated_at = datetime.now().strftime("%Y년 %m월 %d일 %H:%M:%S")

                    lines = [
                        "=" * 50,
                        "        🏛️ 국회 자막 통계 보고서",
                        "=" * 50,
                        "",
                        f"생성 일시: {generated_at}",
                        "",
                        "📊 기본 통계",
                        "-" * 30,
                        f"  총 문장 수: {len(subtitles_snapshot):,}개",
                        f"  총 글자 수: {total_chars:,}자",
                        f"  총 공백 기준 단어 수: {total_words:,}개",
                        f"  평균 문장 길이: {total_chars / len(subtitles_snapshot):.1f}자",
                        f"  평균 공백 기준 단어 수: {total_words / len(subtitles_snapshot):.1f}개",
                        "",
                        "📏 문장 분석",
                        "-" * 30,
                        f"  가장 긴 문장: {len(longest.text)}자",
                        f'    "{longest.text[:50]}{"..." if len(longest.text) > 50 else ""}"',
                        f"  가장 짧은 문장: {len(shortest.text)}자",
                        f'    "{shortest.text}"',
                        "",
                    ]

                    if hour_counts:
                        lines.extend(["⏰ 시간대별 분포", "-" * 30])
                        for h in sorted(hour_counts.keys()):
                            bar = "█" * min(hour_counts[h] // 2, 20)
                            lines.append(f"  {h:02d}시: {bar} {hour_counts[h]}개")
                        lines.append("")

                    if keywords_snapshot:
                        lines.extend(["🔍 키워드 빈도", "-" * 30])
                        all_text = " ".join(s.text for s in subtitles_snapshot).lower()
                        for kw in keywords_snapshot:
                            count = all_text.count(kw.lower())
                            if count > 0:
                                lines.append(f"  {kw}: {count}회")
                        lines.append("")

                    lines.append("=" * 50)
                    utils.atomic_write_text(filepath, "\n".join(lines) + "\n", encoding="utf-8")

                self._save_in_background(
                    do_save,
                    path,
                    "통계 내보내기 완료!",
                    "통계 저장 실패",
                )


    def _generate_smart_filename(self, extension: str) -> str:
            """URL과 현재 시간 기반 스마트 파일명 생성 (#28)"""
            # 위원회명 추출 (현재 URL에서 자동 감지)
            current_url = self._get_current_url()
            committee_name = self._autodetect_tag(current_url)
            return utils.generate_filename(committee_name, extension)


    def _save_txt(self):
            prepared_entries = self._build_prepared_entries_snapshot()
            if not prepared_entries:
                QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
                return

            filename = self._generate_smart_filename("txt")
            path, _ = QFileDialog.getSaveFileName(
                self, "TXT 저장", filename, "텍스트 (*.txt)"
            )

            if path:
                # 스레드 안전하게 자막 스냅샷 생성 (UI 스레드에서)
                subtitles_snapshot = [
                    (entry.timestamp, entry.text) for entry in prepared_entries
                ]

                # 실제 저장 함수 정의
                def do_save(filepath):
                    lines = []
                    last_printed_ts = None
                    for i, (timestamp, text) in enumerate(subtitles_snapshot):
                        # 메인 윈도우와 동일: 1분 간격으로 타임스탬프 표시
                        should_print_ts = False
                        if last_printed_ts is None:
                            should_print_ts = True
                        elif (timestamp - last_printed_ts).total_seconds() >= 60:
                            should_print_ts = True

                        if should_print_ts:
                            lines.append(f"[{timestamp.strftime('%H:%M:%S')}] {text}\n")
                            last_printed_ts = timestamp
                        else:
                            lines.append(f"{text}\n")
                    utils.atomic_write_text(filepath, "".join(lines), encoding="utf-8-sig")

                # 백그라운드에서 저장 실행
                self._save_in_background(do_save, path, "TXT 저장 완료!", "TXT 저장 실패")


    def _save_srt(self):
            prepared_entries = self._build_prepared_entries_snapshot()
            if not prepared_entries:
                QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
                return

            filename = self._generate_smart_filename("srt")
            path, _ = QFileDialog.getSaveFileName(
                self, "SRT 저장", filename, "SubRip (*.srt)"
            )

            if path:
                # 스레드 안전하게 자막 스냅샷 생성 (UI 스레드에서)
                subtitles_snapshot = [
                    (entry.start_time, entry.end_time, entry.timestamp, entry.text)
                    for entry in prepared_entries
                ]

                def do_save(filepath):
                    lines = []
                    for i, (start_time, end_time, timestamp, text) in enumerate(
                        subtitles_snapshot, 1
                    ):
                        if start_time and end_time:
                            # [Fix] 밀리초 정밀도 개선
                            start = f"{start_time.strftime('%H:%M:%S')},{start_time.microsecond // 1000:03d}"
                            end = f"{end_time.strftime('%H:%M:%S')},{end_time.microsecond // 1000:03d}"
                        else:
                            start = f"{timestamp.strftime('%H:%M:%S')},{timestamp.microsecond // 1000:03d}"
                            fallback_end = timestamp + timedelta(seconds=3)
                            end = f"{fallback_end.strftime('%H:%M:%S')},{fallback_end.microsecond // 1000:03d}"
                        lines.append(f"{i}\n{start} --> {end}\n{text}\n\n")
                    utils.atomic_write_text(filepath, "".join(lines), encoding="utf-8")

                self._save_in_background(do_save, path, "SRT 저장 완료!", "SRT 저장 실패")


    def _save_vtt(self):
            prepared_entries = self._build_prepared_entries_snapshot()
            if not prepared_entries:
                QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
                return

            filename = self._generate_smart_filename("vtt")
            path, _ = QFileDialog.getSaveFileName(
                self, "VTT 저장", filename, "WebVTT (*.vtt)"
            )

            if path:
                subtitles_snapshot = [
                    (entry.start_time, entry.end_time, entry.timestamp, entry.text)
                    for entry in prepared_entries
                ]

                def do_save(filepath):
                    lines = ["WEBVTT\n\n"]
                    for i, (start_time, end_time, timestamp, text) in enumerate(
                        subtitles_snapshot, 1
                    ):
                        if start_time and end_time:
                            # [Fix] 밀리초 정밀도 개선
                            start = f"{start_time.strftime('%H:%M:%S')}.{start_time.microsecond // 1000:03d}"
                            end = f"{end_time.strftime('%H:%M:%S')}.{end_time.microsecond // 1000:03d}"
                        else:
                            start = f"{timestamp.strftime('%H:%M:%S')}.{timestamp.microsecond // 1000:03d}"
                            fallback_end = timestamp + timedelta(seconds=3)
                            end = f"{fallback_end.strftime('%H:%M:%S')}.{fallback_end.microsecond // 1000:03d}"
                        lines.append(f"{i}\n{start} --> {end}\n{text}\n\n")
                    utils.atomic_write_text(filepath, "".join(lines), encoding="utf-8")

                self._save_in_background(do_save, path, "VTT 저장 완료!", "VTT 저장 실패")


    def _save_docx(self):
            """DOCX (Word) 파일로 저장"""
            prepared_entries = self._build_prepared_entries_snapshot()
            if not prepared_entries:
                QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
                return

            try:
                docx_module = _import_optional_module("docx")
                docx_shared = _import_optional_module("docx.shared")
                docx_enum_text = _import_optional_module("docx.enum.text")
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

            if path:
                # 스레드 안전하게 자막 스냅샷 생성
                subtitles_snapshot = [
                    (entry.timestamp, entry.text) for entry in prepared_entries
                ]

                generated_at = datetime.now().strftime("%Y년 %m월 %d일 %H:%M:%S")
                total_chars = sum(len(text) for _, text in subtitles_snapshot)
                document_factory = cast(Callable[[], Any], docx_module.Document)
                point_factory = cast(Callable[[int], Any], docx_shared.Pt)
                paragraph_alignment = cast(Any, docx_enum_text.WD_ALIGN_PARAGRAPH)

                def do_save(filepath):
                    doc = document_factory()

                    # 제목
                    title = doc.add_heading("국회 의사중계 자막", 0)
                    title.alignment = paragraph_alignment.CENTER

                    # 생성 일시
                    doc.add_paragraph(f"생성 일시: {generated_at}")
                    doc.add_paragraph()

                    # 자막 내용 - 1분 간격으로 타임스탬프 표시
                    last_printed_ts = None
                    for timestamp, text in subtitles_snapshot:
                        should_print_ts = False
                        if last_printed_ts is None:
                            should_print_ts = True
                        elif (timestamp - last_printed_ts).total_seconds() >= 60:
                            should_print_ts = True

                        p = doc.add_paragraph()
                        if should_print_ts:
                            ts = timestamp.strftime("%H:%M:%S")
                            run = p.add_run(f"[{ts}] ")
                            run.font.size = point_factory(9)
                            run.font.color.rgb = None  # 기본 색상
                            last_printed_ts = timestamp
                        p.add_run(text)

                    # 통계
                    doc.add_paragraph()
                    doc.add_paragraph(
                        f"총 {len(subtitles_snapshot)}문장, {total_chars:,}자"
                    )

                    doc.save(filepath)

                self._save_in_background(do_save, path, "DOCX 저장 완료!", "DOCX 저장 실패")


    def _save_hwpx(self):
            """HWPX 파일로 저장"""
            prepared_entries = self._build_prepared_entries_snapshot()
            if not prepared_entries:
                QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
                return

            filename = self._generate_smart_filename("hwpx")
            path, _ = QFileDialog.getSaveFileName(
                self, "HWPX 저장", filename, "한글 문서 (*.hwpx)"
            )

            if path:
                subtitles_snapshot = [
                    (entry.timestamp, entry.text) for entry in prepared_entries
                ]
                generated_at = datetime.now()

                def do_save(filepath):
                    save_hwpx_document(filepath, subtitles_snapshot, generated_at)

                self._save_in_background(do_save, path, "HWPX 저장 완료!", "HWPX 저장 실패")


    def _save_hwp(self):
            """HWP 파일로 저장 (Hancom Office 필요)"""
            prepared_entries = self._build_prepared_entries_snapshot()
            if not prepared_entries:
                QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
                return

            try:
                win32_client = _import_optional_module("win32com.client")
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

            # 저장 대화상자
            filename = f"국회자막_{datetime.now().strftime('%Y%m%d_%H%M%S')}.hwp"
            path, _ = QFileDialog.getSaveFileName(
                self, "HWP 저장", filename, "HWP 문서 (*.hwp)"
            )

            if not path:
                return

            # 스레드 안전하게 자막 스냅샷 생성
            subtitles_snapshot = [
                (entry.timestamp, entry.text) for entry in prepared_entries
            ]

            generated_at = datetime.now().strftime("%Y년 %m월 %d일 %H:%M:%S")
            total_chars = sum(len(text) for _, text in subtitles_snapshot)

            def do_save(filepath):
                hwp = None
                pythoncom_module = None
                try:
                    try:
                        pythoncom_module = _import_optional_module("pythoncom")
                        pythoncom_module.CoInitialize()
                    except Exception:
                        pythoncom_module = None

                    # 동적 COM API는 스텁이 약하므로 getattr/cast로 접근한다.
                    dynamic_dispatch = getattr(win32_client, "dynamic", None)
                    if dynamic_dispatch is not None:
                        hwp = cast(Any, dynamic_dispatch).Dispatch("HWPFrame.HwpObject")
                    else:
                        hwp = cast(Any, win32_client).Dispatch("HWPFrame.HwpObject")
                    hwp.XHwpWindows.Item(0).Visible = True
                    hwp.RegisterModule(
                        "FilePathCheckDLL", "SecurityModule"
                    )  # 보안 모듈 등록 시도

                    # 새 문서 생성
                    hwp.HAction.Run("FileNew")

                    # 제목 입력
                    hwp.HAction.Run("CharShapeBold")
                    hwp.HAction.Run("ParagraphShapeAlignCenter")
                    hwp.HAction.GetDefault("InsertText", hwp.HParameterSet.HInsertText.HSet)
                    hwp.HParameterSet.HInsertText.Text = "국회 의사중계 자막\r\n"
                    hwp.HAction.Execute("InsertText", hwp.HParameterSet.HInsertText.HSet)

                    hwp.HAction.Run("CharShapeBold")
                    hwp.HAction.Run("ParagraphShapeAlignLeft")

                    # 생성 일시
                    hwp.HParameterSet.HInsertText.Text = (
                        f"생성 일시: {generated_at}\r\n\r\n"
                    )
                    hwp.HAction.Execute("InsertText", hwp.HParameterSet.HInsertText.HSet)

                    # 자막 내용 - 1분 간격으로 타임스탬프 표시
                    last_printed_ts = None
                    for timestamp, text in subtitles_snapshot:
                        should_print_ts = False
                        if last_printed_ts is None:
                            should_print_ts = True
                        elif (timestamp - last_printed_ts).total_seconds() >= 60:
                            should_print_ts = True

                        if should_print_ts:
                            ts = timestamp.strftime("%H:%M:%S")
                            hwp.HParameterSet.HInsertText.Text = f"[{ts}] {text}\r\n"
                            last_printed_ts = timestamp
                        else:
                            hwp.HParameterSet.HInsertText.Text = f"{text}\r\n"
                        hwp.HAction.Execute(
                            "InsertText", hwp.HParameterSet.HInsertText.HSet
                        )

                    # 통계
                    hwp.HParameterSet.HInsertText.Text = (
                        f"\r\n총 {len(subtitles_snapshot)}문장, {total_chars:,}자\r\n"
                    )
                    hwp.HAction.Execute("InsertText", hwp.HParameterSet.HInsertText.HSet)

                    # FileSaveAs_S 액션 사용
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
                            raise RuntimeError("저장된 파일이 확인되지 않습니다.")
                        return
                    except Exception as e:
                        last_error = e
                        logger.warning(f"HWP 저장 재시도 실패 ({attempt + 1}/2): {e}")
                        time.sleep(1)
                if last_error is None:
                    last_error = RuntimeError("HWP 저장이 완료되지 않았습니다.")
                self.message_queue.put(("hwp_save_failed", {"error": str(last_error)}))
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
            """유니코드 문자를 RTF 형식으로 인코딩 (특수문자 이스케이프)"""
            result = []
            for char in text:
                if char == "\\":
                    result.append("\\\\")
                elif char == "{":
                    result.append("\\{")
                elif char == "}":
                    result.append("\\}")
                else:
                    result.append(char)
            return "".join(result)


    def _save_rtf(self):
            """RTF 파일로 저장 (HWP에서 열기 가능)"""
            prepared_entries = self._build_prepared_entries_snapshot()
            if not prepared_entries:
                QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
                return

            filename = self._generate_smart_filename("rtf")
            path, _ = QFileDialog.getSaveFileName(
                self, "RTF 저장", filename, "RTF 문서 (*.rtf)"
            )

            if path:
                # 스레드 안전하게 자막 스냅샷 생성
                subtitles_snapshot = list(prepared_entries)
                if not subtitles_snapshot:
                    QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
                    return

                def do_save(filepath):
                    # RTF 내용을 메모리에서 구성한 뒤 원자적으로 저장한다.
                    chunks = []
                    # RTF 헤더 (유니코드 지원)
                    chunks.append(b"{\\rtf1\\ansi\\ansicpg949\\deff0")
                    chunks.append(
                        b"{\\fonttbl{\\f0\\fnil\\fcharset129 \\'b8\\'c0\\'c0\\'ba \\'b0\\'ed\\'b5\\'f1;}}"
                    )
                    chunks.append(
                        b"{\\colortbl;\\red0\\green0\\blue0;\\red128\\green128\\blue128;}"
                    )
                    chunks.append(b"\n")

                    # 제목
                    title = self._rtf_encode("국회 의사중계 자막")
                    chunks.append(b"\\pard\\qc\\b\\fs28 ")
                    chunks.append(title.encode("cp949", errors="replace"))
                    chunks.append(b"\\b0\\par\n")

                    # 생성 일시
                    date_str = self._rtf_encode(
                        f"생성 일시: {datetime.now().strftime('%Y년 %m월 %d일 %H:%M:%S')}"
                    )
                    chunks.append(b"\\pard\\ql\\fs20 ")
                    chunks.append(date_str.encode("cp949", errors="replace"))
                    chunks.append(b"\\par\\par\n")

                    # 자막 내용
                    for entry in subtitles_snapshot:
                        timestamp = entry.timestamp.strftime("%H:%M:%S")
                        text = self._rtf_encode(entry.text)
                        chunks.append(b"\\cf2[")
                        chunks.append(timestamp.encode("cp949", errors="replace"))
                        chunks.append(b"]\\cf1 ")
                        chunks.append(text.encode("cp949", errors="replace"))
                        chunks.append(b"\\par\n")

                    # 통계
                    total_chars = sum(len(s.text) for s in subtitles_snapshot)
                    stats = self._rtf_encode(f"총 {len(subtitles_snapshot)}문장, {total_chars:,}자")
                    chunks.append(b"\\par\\fs18 ")
                    chunks.append(stats.encode("cp949", errors="replace"))
                    chunks.append(b"\\par}")

                    utils.atomic_write_bytes(filepath, b"".join(chunks))

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

            prepared_entries = self._build_prepared_entries_snapshot()
            has_subtitles = bool(prepared_entries)
            if not has_subtitles:
                QMessageBox.warning(self, "알림", "저장할 내용이 없습니다.")
                return

            if self._session_save_in_progress:
                self._show_toast("이미 세션 저장이 진행 중입니다.", "info")
                return

            filename = (
                f"{Config.SESSION_DIR}/세션_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            path, _ = QFileDialog.getSaveFileName(
                self, "세션 저장", filename, "JSON (*.json)"
            )

            if not path:
                return

            try:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                QMessageBox.critical(self, "오류", f"세션 저장 경로 준비 실패: {e}")
                return

            self._session_save_in_progress = True
            self._set_status("세션 저장 중...", "running")

            current_url = self._get_current_url()
            committee_name = self._autodetect_tag(current_url) or ""
            duration = int(time.time() - self.start_time) if self.start_time else 0

            def background_save():
                try:
                    created_at = datetime.now().isoformat()
                    utils.atomic_write_json_stream(
                        path,
                        head_items=[
                            ("version", Config.VERSION),
                            ("created", created_at),
                            ("url", current_url),
                            ("committee_name", committee_name),
                        ],
                        sequence_key="subtitles",
                        sequence_items=utils.iter_serialized_subtitles(prepared_entries),
                        ensure_ascii=False,
                    )

                    db_saved = False
                    db_error = ""
                    db = self.db
                    if db is not None:
                        try:
                            db_data = {
                                "url": current_url,
                                "committee_name": committee_name,
                                "subtitles": prepared_entries,
                                "version": Config.VERSION,
                                "duration_seconds": duration,
                            }
                            db.save_session(db_data)
                            db_saved = True
                        except Exception as db_exc:
                            db_error = str(db_exc)

                    self.message_queue.put(
                        (
                            "session_save_done",
                            {
                                "path": path,
                                "saved_count": len(prepared_entries),
                                "db_saved": db_saved,
                                "db_error": db_error,
                            },
                        )
                    )
                except Exception as e:
                    logger.error(f"세션 저장 오류: {e}")
                    self.message_queue.put(
                        ("session_save_failed", {"path": path, "error": str(e)})
                    )

            started = self._start_background_thread(background_save, "SessionSaveWorker")
            if not started:
                self._session_save_in_progress = False
                self._set_status("세션 저장 시작 거부 (종료 중)", "warning")
                self._show_toast("종료 중이라 세션 저장을 시작할 수 없습니다.", "warning")
                return
            self._show_toast(f"💾 세션 저장 시작: {Path(path).name}", "info", 1500)


    def _load_session(self):
            if self._is_runtime_mutation_blocked("세션 불러오기"):
                return
            if self._is_background_shutdown_active():
                self._show_toast("종료 중이라 세션 불러오기를 시작할 수 없습니다.", "warning")
                return

            if self._session_load_in_progress:
                self._show_toast("이미 세션 불러오기가 진행 중입니다.", "info")
                return

            path, _ = QFileDialog.getOpenFileName(
                self, "세션 불러오기", f"{Config.SESSION_DIR}/", "JSON (*.json)"
            )

            if not path:
                return

            self._session_load_in_progress = True
            self._set_status("세션 불러오기 중...", "running")

            def background_load():
                try:
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                    except json.JSONDecodeError as json_err:
                        self.message_queue.put(
                            (
                                "session_load_json_error",
                                {"path": path, "error": str(json_err)},
                            )
                        )
                        return

                    session_version = data.get("version", "unknown")
                    new_subtitles, skipped = self._deserialize_subtitles(
                        data.get("subtitles", []),
                        source=f"session:{path}",
                    )

                    self.message_queue.put(
                        (
                            "session_load_done",
                            {
                                "path": path,
                                "version": session_version,
                                "created_at": data.get("created", ""),
                                "url": data.get("url", ""),
                                "committee_name": data.get("committee_name", ""),
                                "subtitles": new_subtitles,
                                "skipped": skipped,
                            },
                        )
                    )
                except Exception as e:
                    logger.error(f"세션 불러오기 오류: {e}")
                    self.message_queue.put(
                        ("session_load_failed", {"path": path, "error": str(e)})
                    )

            started = self._start_background_thread(background_load, "SessionLoadWorker")
            if not started:
                self._session_load_in_progress = False
                self._set_status("세션 불러오기 시작 거부 (종료 중)", "warning")
                self._show_toast("종료 중이라 세션 불러오기를 시작할 수 없습니다.", "warning")
                return
            self._show_toast(f"📂 세션 불러오기 시작: {Path(path).name}", "info", 1500)


    def _deserialize_subtitles(
            self, serialized_items, source: str = ""
        ) -> tuple[list[SubtitleEntry], int]:
            """직렬화된 자막 목록을 SubtitleEntry 리스트로 변환한다."""
            entries: list[SubtitleEntry] = []
            skipped = 0

            if serialized_items is None:
                return entries, skipped

            if not isinstance(serialized_items, (list, tuple)):
                logger.warning("자막 목록 타입 오류 (%s): %s", source, type(serialized_items))
                return entries, 1

            for item in serialized_items:
                try:
                    entries.append(SubtitleEntry.from_dict(item))
                except (ValueError, TypeError, KeyError) as e:
                    logger.warning("손상된 자막 항목 건너뜀 (%s): %s", source, e)
                    skipped += 1

            return entries, skipped


    def _clean_newlines(self):
            """줄넘김 정리: 문장 부호 분리 및 병합 (스마트 리플로우)"""
            if self._is_runtime_mutation_blocked("줄넘김 정리"):
                return
            # 자막이 없는 경우 처리
            if not self.subtitles:
                self._show_toast("정리할 자막이 없습니다.", "warning")
                return

            # 사용자 확인
            reply = QMessageBox.question(
                self,
                "줄넘김 정리 (Smart Reflow)",
                "자막 재정렬을 수행하시겠습니까?\n\n"
                "기능:\n"
                "1. 텍스트 내 타임스탬프([HH:MM:SS])를 감지하여 분리\n"
                "2. 문장 부호(. ? !) 기준으로 줄 바꿈\n"
                "3. 끊어진 문장 병합\n\n"
                "(주의: 되돌리기는 지원되지 않습니다.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                return

            # 병합/분리 로직 (utils 모듈 위임)
            try:
                old_count = len(self.subtitles)

                # 스레드 안전하게 복사본 생성 후 처리
                with self.subtitle_lock:
                    current_subs = list(self.subtitles)

                # 처리 (시간 소요 가능성 있으므로 락 밖에서 수행 권장하지만, 데이터가 크지 않아 즉시 수행)
                new_subtitles = utils.reflow_subtitles(current_subs)

                if not new_subtitles:
                    return

                # 원본과 개수 차이 확인
                logger.info(f"스마트 리플로우: {old_count} -> {len(new_subtitles)}")

                self._replace_subtitles_and_refresh(new_subtitles)

                # 결과 알림
                self._show_toast(f"정리 완료! ({len(new_subtitles)}개 문장)", "success")

            except Exception as e:
                logger.error(f"리플로우 중 오류: {e}")
                self._show_toast(f"오류 발생: {e}", "error")


    def _merge_sessions(
            self,
            file_paths: list,
            remove_duplicates: bool = True,
            sort_by_time: bool = True,
            existing_subtitles: list[SubtitleEntry] | None = None,
            dedupe_mode: str = "legacy_bucket",
        ) -> list[SubtitleEntry]:
            """여러 세션 파일을 병합

            Args:
                file_paths: 병합할 파일 경로 목록
                remove_duplicates: 중복 자막 제거 여부
                sort_by_time: 시간순 정렬 여부
                existing_subtitles: 기존 자막 리스트 (선택)

            Returns:
                List[SubtitleEntry]: 병합된 자막 목록
            """
            all_entries: list[SubtitleEntry] = []

            # 기존 자막 추가
            if existing_subtitles:
                all_entries.extend(existing_subtitles)

            for path in file_paths:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    entries, skipped = self._deserialize_subtitles(
                        data.get("subtitles", []),
                        source=str(path),
                    )
                    all_entries.extend(entries)
                    if skipped:
                        logger.warning("자막 항목 %s개 건너뜀 (%s)", skipped, path)

                except Exception as e:
                    logger.warning(f"파일 로드 실패 ({path}): {e}")

            # 시간순 정렬
            if sort_by_time:
                all_entries.sort(key=lambda e: e.timestamp)

            # 중복 제거
            if remove_duplicates:
                seen = set()
                unique_entries = []
                for entry in all_entries:
                    text_normalized = utils.normalize_subtitle_text(entry.text).lower()
                    timestamp = entry.timestamp if entry and entry.timestamp else datetime.min
                    if dedupe_mode == "conservative_same_second":
                        if timestamp == datetime.min:
                            time_bucket = 0
                        else:
                            time_bucket = int(timestamp.timestamp())
                    else:
                        bucket_seconds = max(
                            1, int(Config.MERGE_DEDUP_TIME_BUCKET_SECONDS)
                        )
                        if timestamp == datetime.min:
                            time_bucket = 0
                        else:
                            time_bucket = int(timestamp.timestamp() // bucket_seconds)
                    dedupe_key = (text_normalized, time_bucket)
                    if dedupe_key not in seen:
                        seen.add(dedupe_key)
                        unique_entries.append(entry)
                all_entries = unique_entries

            logger.info(f"병합 완료: {len(all_entries)}개 자막")
            return all_entries
