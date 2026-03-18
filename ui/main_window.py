# -*- coding: utf-8 -*-

from typing import TYPE_CHECKING

from ui.main_window_common import *
from ui.main_window_capture import MainWindowCaptureMixin
from ui.main_window_database import MainWindowDatabaseMixin
from ui.main_window_persistence import MainWindowPersistenceMixin
from ui.main_window_pipeline import MainWindowPipelineMixin
from ui.main_window_ui import MainWindowUIMixin
from ui.main_window_view import MainWindowViewMixin
import ui.main_window_capture as capture_mod

MainWindowQtBase = object if TYPE_CHECKING else QMainWindow


class MainWindow(  # pyright: ignore[reportGeneralTypeIssues]
    MainWindowQtBase,
    MainWindowUIMixin,
    MainWindowCaptureMixin,
    MainWindowPipelineMixin,
    MainWindowViewMixin,
    MainWindowPersistenceMixin,
    MainWindowDatabaseMixin,
):

    def _sync_capture_compat_globals(self) -> None:
            # Preserve legacy tests that monkeypatch symbols on ui.main_window.
            capture_mod.webdriver = webdriver
            capture_mod.WebDriverWait = WebDriverWait
            capture_mod.EC = EC
            capture_mod.By = By

    def _activate_subtitle(self, driver: Any) -> bool:
            self._sync_capture_compat_globals()
            return MainWindowCaptureMixin._activate_subtitle(self, driver)

    def _detect_live_broadcast(self, driver: Any, original_url: str) -> str:
            self._sync_capture_compat_globals()
            return MainWindowCaptureMixin._detect_live_broadcast(
                self, driver, original_url
            )

    def _read_subtitle_probe_by_selectors(
        self,
        driver: Any,
        selectors: list[str],
        preferred_frame_path: tuple[int, ...] = (),
        filter_unconfirmed_enabled: bool = True,
    ) -> dict[str, Any]:
            self._sync_capture_compat_globals()
            return MainWindowCaptureMixin._read_subtitle_probe_by_selectors(
                self,
                driver,
                selectors,
                preferred_frame_path=preferred_frame_path,
                filter_unconfirmed_enabled=filter_unconfirmed_enabled,
            )

    def _read_subtitle_text_by_selectors(
        self,
        driver: Any,
        selectors: list[str],
        preferred_frame_path: tuple[int, ...] = (),
    ) -> tuple[str, str, bool]:
            self._sync_capture_compat_globals()
            return MainWindowCaptureMixin._read_subtitle_text_by_selectors(
                self,
                driver,
                selectors,
                preferred_frame_path=preferred_frame_path,
            )

    def _extraction_worker(self, url: str, selector: str, headless: bool) -> None:
            self._sync_capture_compat_globals()
            return MainWindowCaptureMixin._extraction_worker(
                self, url, selector, headless
            )

    def _is_auto_clean_newlines_enabled(self) -> bool:
            checkbox = self.__dict__.get("auto_clean_newlines_check")
            if checkbox is not None:
                try:
                    return bool(checkbox.isChecked())
                except Exception:
                    pass
            return bool(
                self.__dict__.get(
                    "auto_clean_newlines_enabled",
                    Config.AUTO_CLEAN_NEWLINES_DEFAULT,
                )
            )

    def _normalize_subtitle_text_for_option(self, text: object) -> str:
            raw = "" if text is None else str(text)
            if self._is_auto_clean_newlines_enabled():
                return utils.flatten_subtitle_text(raw)
            return utils.clean_text_display(raw)

    def _toggle_auto_clean_newlines_option(self) -> None:
            enabled = self._is_auto_clean_newlines_enabled()
            self.auto_clean_newlines_enabled = enabled
            settings = self.__dict__.get("settings")
            if settings is not None:
                settings.setValue("auto_clean_newlines", enabled)

    def __init__(self):
            super().__init__()
            self.setWindowTitle(f"{Config.APP_NAME} v{Config.VERSION}")
            self.setMinimumSize(1100, 750)
            self.resize(1200, 800)

            # 설정
            self.settings = QSettings("AssemblySubtitle", "Extractor")
            self.is_dark_theme = self.settings.value("dark_theme", True, type=bool)
            self.font_size = self.settings.value(
                "font_size", Config.DEFAULT_FONT_SIZE, type=int
            )
            self.minimize_to_tray = self.settings.value(
                "minimize_to_tray", False, type=bool
            )
            self.auto_clean_newlines_enabled = self.settings.value(
                "auto_clean_newlines",
                Config.AUTO_CLEAN_NEWLINES_DEFAULT,
                type=bool,
            )

            # 메시지 큐
            self.message_queue: queue.Queue[tuple[str, Any]] = queue.Queue()

            # 상태
            self.worker = None
            self.driver = None
            self.is_running = False
            self.stop_event = threading.Event()  # 스레드 안전한 종료 시그널
            self.subtitle_lock = threading.Lock()  # 자막 리스트 접근 동기화
            self._auto_backup_lock = threading.Lock()  # 자동 백업 중복 실행 방지
            self.start_time = None
            self.last_subtitle = ""
            self._last_raw_text = ""
            self._last_processed_raw = ""
            self._stream_start_time = None

            # [NEW] 글로벌 히스토리 + Suffix 매칭 (#GlobalHistorySuffix)
            self._confirmed_compact = ""  # 확정된 모든 텍스트 (compact, 공백 제거)
            self._trailing_suffix = ""  # 히스토리의 마지막 N자 (suffix 매칭용)
            self._suffix_length = 50  # suffix 길이
            self._preview_desync_count = 0
            self._preview_ambiguous_skip_count = 0
            self._last_good_raw_compact = ""
            self._preview_resync_threshold = 10
            self._preview_ambiguous_resync_threshold = 6

            # [Fix] 자막 중복 방지 프로세서 (#SubtitleRepetitionFix)
            self.subtitle_processor = SubtitleProcessor()

            # 저장된 키워드 로드
            saved_keywords = self.settings.value("highlight_keywords", "")
            if not saved_keywords:
                legacy_keywords = self.settings.value("keywords", "", type=str)
                if legacy_keywords:
                    saved_keywords = legacy_keywords
                    self.settings.setValue("highlight_keywords", legacy_keywords)
                    self.settings.remove("keywords")
            self.keywords = (
                [k.strip() for k in saved_keywords.split(",") if k.strip()]
                if saved_keywords
                else []
            )
            saved_alert = self.settings.value("alert_keywords", "")
            self.alert_keywords = (
                [k.strip() for k in saved_alert.split(",") if k.strip()]
                if saved_alert
                else []
            )
            self._alert_keywords_cache = []
            self._rebuild_alert_keyword_cache(
                self.alert_keywords, update_settings=False
            )
            self.last_update_time = 0  # 마지막 자막 업데이트 시간

            # 성능 최적화: QTextCharFormat 캐싱
            self._highlight_fmt = QTextCharFormat()
            self._highlight_fmt.setBackground(QColor("#ffd700"))  # 골드 배경
            self._highlight_fmt.setForeground(QColor("#000000"))  # 검정 글자
            self._highlight_fmt.setFontWeight(QFont.Weight.Bold)
            self._normal_fmt = QTextCharFormat()
            self._timestamp_fmt = QTextCharFormat()
            self._timestamp_fmt.setForeground(QColor("#888888"))

            # 성능 최적화: 키워드 패턴 캐싱
            self._keyword_pattern = None  # 컴파일된 정규식 패턴
            self._keywords_lower_set = set()  # 빠른 검색용 set
            self._rebuild_keyword_cache(self.keywords, update_settings=False, refresh=False)

            # 성능 최적화: 통계 캐싱
            self._cached_total_chars = 0
            self._cached_total_words = 0

            # 렌더링 상태 캐싱
            self._last_rendered_count = 0
            self._last_rendered_last_text = ""
            self._last_render_offset = 0
            self._last_render_show_ts = None
            self._last_render_chunk_specs: list[tuple[str, str, str]] = []

            # 토스트 스택 관리
            self.active_toasts: list[ToastWidget] = []

            # 실시간 저장
            self.realtime_file = None
            self._realtime_error_count = 0  # 실시간 저장 연속 오류 카운트 (#3)

            # 중지 시 브라우저 유지용 (종료 시 정리)
            self.capture_state: CaptureSessionState = create_empty_capture_state()
            self.subtitles: list[SubtitleEntry] = self.capture_state.entries
            self.live_capture_ledger = create_empty_live_capture_ledger()
            self._pending_subtitle_reset_source = ""
            self._pending_subtitle_reset_timer = QTimer(self)
            self._pending_subtitle_reset_timer.setSingleShot(True)
            self._pending_subtitle_reset_timer.timeout.connect(
                self._commit_scheduled_subtitle_reset
            )
            self._detached_drivers: list[Any] = []
            self._detached_drivers_lock = threading.Lock()
            self._last_subtitle_frame_path = ()

            # 연결 상태 모니터링 (#30)
            self.connection_status = "disconnected"  # connected, disconnected, reconnecting
            self.last_ping_time = 0
            self.ping_latency = 0  # ms

            # 자동 재연결 (#31)
            self.reconnect_attempts = 0
            self.auto_reconnect_enabled = self.settings.value(
                "auto_reconnect", True, type=bool
            )
            self.current_url = ""  # 현재 연결 중인 URL 저장

            # 스마트 스크롤 상태 (사용자가 위로 스크롤하면 자동 스크롤 일시 중지)
            self._user_scrolled_up = False
            self._is_stopping = False
            self._last_status_message = ""
            self._session_save_in_progress = False
            self._session_load_in_progress = False
            self._db_history_dialog_state: dict[str, Any] | None = None
            self._active_background_threads: set[threading.Thread] = set()
            self._active_background_threads_lock = threading.Lock()
            self._background_shutdown_initiated = False

            # URL 히스토리
            self.url_history = self._load_url_history()

            # UI 생성
            self._create_menu()
            self._create_ui()
            self._apply_theme()
            self._setup_shortcuts()

            # 타이머
            self.queue_timer = QTimer(self)
            self.queue_timer.timeout.connect(self._process_message_queue)
            self.queue_timer.start(Config.QUEUE_PROCESS_INTERVAL)

            self.stats_timer = QTimer(self)
            self.stats_timer.timeout.connect(self._update_stats)

            # 자동 백업 타이머
            self.backup_timer = QTimer(self)
            self.backup_timer.timeout.connect(self._auto_backup)

            # 디렉토리 생성
            Path(Config.SESSION_DIR).mkdir(exist_ok=True)
            Path(Config.REALTIME_DIR).mkdir(exist_ok=True)
            Path(Config.BACKUP_DIR).mkdir(exist_ok=True)

            # 데이터베이스 매니저 초기화 (#26)
            self.db: DatabaseProtocol | None = None
            self._db_tasks_inflight: set[str] = set()
            if DB_AVAILABLE and DatabaseManagerClass is not None:
                try:
                    db_factory = cast(Callable[[str], DatabaseProtocol], DatabaseManagerClass)
                    self.db = db_factory(Config.DATABASE_PATH)
                except Exception as e:
                    logger.error(f"데이터베이스 초기화 실패: {e}")

            # 창 위치/크기 복원
            geometry = self.settings.value("geometry")
            if geometry:
                self.restoreGeometry(geometry)
            state = self.settings.value("windowState")
            if state:
                self.restoreState(state)

            # 시스템 트레이 설정
            self._setup_tray()


    def _start(self):
            if self.is_running:
                return

            url = self._get_current_url().strip()
            selector = self.selector_combo.currentText().strip()

            if not url or not selector:
                QMessageBox.warning(self, "오류", "URL과 선택자를 입력하세요.")
                return

            if not url.startswith(("http://", "https://")):
                QMessageBox.warning(self, "오류", "올바른 URL을 입력하세요.")
                return

            try:
                # 히스토리에 추가
                self._add_to_history(url)
                self.current_url = url

                # 초기화
                self.subtitle_text.clear()
                self.capture_state = create_empty_capture_state()
                self._bind_subtitles_to_capture_state()
                self.live_capture_ledger = create_empty_live_capture_ledger()
                self._cancel_scheduled_subtitle_reset()
                self._cached_total_chars = 0
                self._cached_total_words = 0
                self._last_rendered_count = 0
                self._last_rendered_last_text = ""
                self._last_render_offset = 0
                self._last_render_show_ts = None
                self._last_render_chunk_specs = []
                self._last_printed_ts = None
                self._update_count_label()

                self.last_subtitle = ""
                self.last_update_time = 0
                self._last_raw_text = ""
                self._last_processed_raw = ""
                self._stream_start_time = None
                self._confirmed_compact = ""
                self._trailing_suffix = ""
                self._preview_desync_count = 0
                self._preview_ambiguous_skip_count = 0
                self._last_good_raw_compact = ""
                self._is_stopping = False
                self._clear_preview()
                self.start_time = time.time()

                # 큐 비우기
                self._clear_message_queue()

                # 실시간 저장 설정 (예외 처리 추가)
                self.realtime_file = None
                if self.realtime_save_check.isChecked():
                    try:
                        Path(Config.REALTIME_DIR).mkdir(exist_ok=True)
                        filename = f"{Config.REALTIME_DIR}/자막_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                        self.realtime_file = open(
                            filename, "w", encoding="utf-8-sig"
                        )  # BOM 포함 (#12)
                        self._set_status(f"실시간 저장: {filename}", "success")
                    except Exception as e:
                        logger.error(f"실시간 저장 파일 생성 오류: {e}")

                # UI 업데이트
                self.is_running = True
                self.stop_event.clear()  # 종료 이벤트 초기화
                self.start_btn.setEnabled(False)
                self.stop_btn.setEnabled(True)
                self.url_combo.setEnabled(False)
                self.selector_combo.setEnabled(False)
                self.progress.show()

                self._set_status("Chrome 브라우저 시작 중...", "running")
                self._update_tray_status("🟢 추출 중")

                # UI 값을 시작 시점에 복사 (스레드 안전성)
                headless = self.headless_check.isChecked()

                # 워커 시작
                self.worker = threading.Thread(
                    target=self._extraction_worker,
                    args=(url, selector, headless),
                    daemon=True,
                )
                self.worker.start()

                # 타이머 시작
                self.stats_timer.start(Config.STATS_UPDATE_INTERVAL)
                self.backup_timer.start(Config.AUTO_BACKUP_INTERVAL)

                # 시작 시 자동으로 상단 UI 접기 (사용자 요청)
                if self.top_header_container.isVisible():
                    self._toggle_top_header()

            except Exception as e:
                logger.exception(f"시작 오류: {e}")
                # 파일 핸들 정리
                if self.realtime_file:
                    try:
                        self.realtime_file.close()
                    except Exception as close_err:
                        logger.debug(f"실시간 저장 파일 닫기 오류: {close_err}")
                    self.realtime_file = None
                self._reset_ui()
                QMessageBox.critical(self, "오류", f"시작 중 오류 발생: {e}")


    def _stop(self, for_app_exit: bool = False):
            if not self.is_running:
                return

            try:
                self.is_running = False
                self.stop_event.set()  # 워커 스레드에 종료 신호
                self._set_status("중지 중...", "warning")
                self._is_stopping = True
                self._cancel_scheduled_subtitle_reset()

                # 종료 직전 큐 preview 소진 + 마지막 자막 확정
                self._drain_pending_previews(requeue_others=True)
                self._materialize_pending_preview()
                finalize_session(
                    self.capture_state,
                    datetime.now(),
                    self._current_capture_settings(),
                )
                self._sync_capture_state_entries(force_refresh=False)
                self._finalize_pending_subtitle()

                force_driver_quit = for_app_exit or (not Config.KEEP_BROWSER_ON_STOP)

                # 앱 종료 또는 브라우저 미유지 설정일 때는 워커 대기 전에 드라이버를 먼저 정리
                if force_driver_quit and self.driver:
                    driver = self.driver
                    self.driver = None
                    self._force_quit_driver_with_timeout(
                        driver, timeout=2.0, source="stop_initial"
                    )

                worker_stopped = self._wait_worker_shutdown(
                    timeout=Config.THREAD_STOP_TIMEOUT
                )

                # 수동 중지 + 브라우저 유지 모드에서 종료가 지연되면 1회 에스컬레이션
                if not worker_stopped and not force_driver_quit and self.driver:
                    logger.warning("워커 스레드 종료 지연 감지 - 드라이버 강제 종료 후 재대기")
                    driver = self.driver
                    self.driver = None
                    self._force_quit_driver_with_timeout(
                        driver, timeout=2.0, source="stop_escalation"
                    )
                    worker_stopped = self._wait_worker_shutdown(timeout=1.0)

                if not worker_stopped:
                    logger.warning("워커 스레드가 시간 내에 종료되지 않음(종료 계속 진행)")

                # 종료 후에도 남아있던 preview 처리
                self._drain_pending_previews(requeue_others=True)
                self._materialize_pending_preview()
                finalize_session(
                    self.capture_state,
                    datetime.now(),
                    self._current_capture_settings(),
                )
                self._sync_capture_state_entries(force_refresh=False)
                self._finalize_pending_subtitle()
                self._clear_preview()

                # 실시간 저장 종료
                if self.realtime_file:
                    try:
                        self.realtime_file.close()
                    except Exception as e:
                        logger.debug(f"파일 닫기 오류: {e}")
                    self.realtime_file = None

                # 중지 이후 남아있을 수 있는 detached WebDriver 정리
                self._cleanup_detached_drivers_with_timeout(timeout=2.0)

                self._clear_message_queue()
                self._reset_ui()
                self._set_status("중지됨", "warning")
                self._update_tray_status("⚪ 대기 중")
            except Exception as e:
                logger.error(f"중지 중 오류 발생: {e}")
                self._reset_ui()
            finally:
                self._is_stopping = False


    def _force_quit_driver_with_timeout(
            self, driver, timeout: float = 2.0, source: str = "shutdown"
        ) -> bool:
            """WebDriver quit()를 타임박스로 실행해 UI 스레드 무기한 대기를 방지한다."""
            if not driver:
                return True

            done = threading.Event()
            error_holder: dict[str, Exception | None] = {"error": None}

            def _quit_driver():
                try:
                    driver.quit()
                except Exception as e:
                    error_holder["error"] = e
                finally:
                    done.set()

            threading.Thread(
                target=_quit_driver,
                daemon=True,
                name=f"DriverQuitThread-{source}",
            ).start()

            if not done.wait(timeout=timeout):
                logger.warning(
                    "WebDriver 종료 타임아웃 (source=%s, timeout=%.1fs)",
                    source,
                    timeout,
                )
                return False

            if error_holder["error"] is not None:
                logger.debug(
                    "WebDriver 종료 오류 (source=%s): %s",
                    source,
                    error_holder["error"],
                )
                return False

            return True


    def _wait_worker_shutdown(self, timeout: float) -> bool:
            """워커 스레드 종료를 제한 시간 동안 대기한다."""
            if not self.worker or not self.worker.is_alive():
                return True
            self.worker.join(timeout=timeout)
            return not self.worker.is_alive()


    def _cleanup_detached_drivers_with_timeout(self, timeout: float = 2.0) -> None:
            """분리된(detached) 드라이버를 타임박스로 종료한다."""
            with self._detached_drivers_lock:
                detached_drivers = list(self._detached_drivers)
                self._detached_drivers.clear()

            for idx, drv in enumerate(detached_drivers, start=1):
                self._force_quit_driver_with_timeout(
                    drv,
                    timeout=timeout,
                    source=f"detached_{idx}",
                )


    def _ensure_background_registry(self) -> None:
            """백그라운드 스레드 레지스트리를 지연 초기화한다."""
            if not hasattr(self, "_active_background_threads") or self._active_background_threads is None:
                self._active_background_threads = set()
            if (
                not hasattr(self, "_active_background_threads_lock")
                or self._active_background_threads_lock is None
            ):
                self._active_background_threads_lock = threading.Lock()
            if not hasattr(self, "_background_shutdown_initiated"):
                self._background_shutdown_initiated = False


    def _begin_background_shutdown(self) -> None:
            """종료 단계 진입: 신규 백그라운드 작업 시작을 차단한다."""
            self._ensure_background_registry()
            with self._active_background_threads_lock:
                self._background_shutdown_initiated = True


    def _is_background_shutdown_active(self) -> bool:
            self._ensure_background_registry()
            with self._active_background_threads_lock:
                return bool(self._background_shutdown_initiated)


    def _unregister_background_thread(self, thread: threading.Thread | None) -> None:
            self._ensure_background_registry()
            if thread is None:
                return
            with self._active_background_threads_lock:
                self._active_background_threads.discard(thread)


    def _start_background_thread(self, target, name: str) -> bool:
            """공통 레지스트리에 등록되는 non-daemon 백그라운드 스레드를 시작한다."""
            self._ensure_background_registry()
            with self._active_background_threads_lock:
                if self._background_shutdown_initiated:
                    logger.info("종료 단계에서 백그라운드 작업 시작 거부: %s", name)
                    return False

                def runner():
                    try:
                        target()
                    finally:
                        self._unregister_background_thread(threading.current_thread())

                worker_thread = threading.Thread(target=runner, daemon=False, name=name)
                self._active_background_threads.add(worker_thread)

            worker_thread.start()
            return True


    def _wait_active_background_threads(self, timeout: float) -> None:
            """실행 중인 백그라운드 스레드 종료를 제한 시간 동안 대기한다."""
            self._ensure_background_registry()
            deadline = time.time() + max(0.0, float(timeout))
            current_thread = threading.current_thread()

            while True:
                with self._active_background_threads_lock:
                    live_threads = [
                        t
                        for t in self._active_background_threads
                        if t is not None and t is not current_thread and t.is_alive()
                    ]
                    if not live_threads:
                        self._active_background_threads = {
                            t for t in self._active_background_threads if t.is_alive()
                        }
                        return

                remaining = deadline - time.time()
                if remaining <= 0:
                    logger.warning(
                        "백그라운드 작업 종료 대기 타임아웃: %s개", len(live_threads)
                    )
                    return

                for thread in live_threads:
                    thread.join(timeout=min(0.2, remaining))


    def _wait_active_save_threads(self, timeout: float) -> None:
            """하위 호환: 저장 스레드 대기 호출은 공통 백그라운드 대기로 위임한다."""
            self._wait_active_background_threads(timeout=timeout)


    def closeEvent(self, a0: QCloseEvent | None) -> None:
            if a0 is None:
                return
            event = a0
            # 트레이 최소화 모드
            if self.minimize_to_tray and self.tray_icon.isVisible():
                self.hide()
                self.tray_icon.showMessage(
                    Config.APP_NAME,
                    "프로그램이 트레이로 최소화되었습니다.\n트레이 아이콘을 더블클릭하여 다시 열 수 있습니다.",
                    QSystemTrayIcon.MessageIcon.Information,
                    2000,
                )
                event.ignore()
                return

            # 추출 중이면 종료 확인 후 먼저 안전 중지(큐 소진/마지막 자막 확정)
            if self.is_running:
                reply = QMessageBox.question(
                    self,
                    "종료",
                    "추출 중입니다. 종료하시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.No:
                    event.ignore()
                    return
                self._stop(for_app_exit=True)

            with self.subtitle_lock:
                subtitle_count = len(self.subtitles)

            # 저장하지 않은 자막이 있으면 확인
            if subtitle_count:
                reply = QMessageBox.question(
                    self,
                    "종료 확인",
                    f"저장하지 않은 자막 {subtitle_count}개가 있습니다.\n\n"
                    "저장하시겠습니까?",
                    QMessageBox.StandardButton.Save
                    | QMessageBox.StandardButton.Discard
                    | QMessageBox.StandardButton.Cancel,
                )
                if reply == QMessageBox.StandardButton.Cancel:
                    event.ignore()
                    return
                elif reply == QMessageBox.StandardButton.Save:
                    # 저장 대화상자에서 취소하면 종료도 취소
                    filename = f"국회자막_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    path, _ = QFileDialog.getSaveFileName(
                        self, "TXT 저장", filename, "텍스트 (*.txt)"
                    )
                    if not path:  # 사용자가 취소한 경우
                        event.ignore()
                        return
                    # 파일 저장 (스레드 안전하게 자막 복사)
                    try:
                        with self.subtitle_lock:
                            subtitles_snapshot = list(self.subtitles)
                        lines = [
                            f"[{entry.timestamp.strftime('%H:%M:%S')}] {entry.text}\n"
                            for entry in subtitles_snapshot
                        ]
                        utils.atomic_write_text(path, "".join(lines), encoding="utf-8")
                    except Exception as e:
                        QMessageBox.critical(self, "오류", f"저장 실패: {e}")
                        event.ignore()
                        return

            # 종료 단계 진입: 신규 백그라운드 작업 차단 -> inflight 작업 대기
            self._begin_background_shutdown()
            self._wait_active_background_threads(timeout=Config.SAVE_THREAD_SHUTDOWN_TIMEOUT)

            # 창 위치/크기 저장
            self.settings.setValue("geometry", self.saveGeometry())
            self.settings.setValue("windowState", self.saveState())

            # 타이머 정리
            self.queue_timer.stop()
            self.stats_timer.stop()
            self.backup_timer.stop()

            if self.realtime_file:
                try:
                    self.realtime_file.close()
                except Exception as e:
                    logger.debug(f"파일 닫기 오류: {e}")
                self.realtime_file = None

            # closeEvent 시에는 실행 여부와 무관하게 드라이버 정리를 시도한다.
            if self.driver:
                driver = self.driver
                self.driver = None
                self._force_quit_driver_with_timeout(
                    driver, timeout=2.0, source="close_event_idle"
                )
            self._cleanup_detached_drivers_with_timeout(timeout=2.0)

            # 데이터베이스 연결 정리
            db = self.db
            if db is not None:
                try:
                    db.close_all()
                except Exception as e:
                    logger.debug(f"DB 연결 종료 오류: {e}")

            logger.info("프로그램 종료")
            event.accept()
