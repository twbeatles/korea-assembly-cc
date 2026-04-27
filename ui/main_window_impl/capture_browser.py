# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportAssignmentType=false

from __future__ import annotations

import time
from importlib import import_module
from typing import Any, Callable, cast

from selenium.webdriver.chrome.options import Options

from core import utils
from core.config import Config
from core.logging_utils import logger
from ui.main_window_common import RecoverableWebDriverError
from ui.main_window_impl.contracts import CaptureBrowserHost


def _capture_public() -> Any:
    return import_module("ui.main_window_capture")


CaptureBrowserBase = object


class MainWindowCaptureBrowserMixin(CaptureBrowserBase):
    def _get_reconnect_delay(self, attempt: int) -> float:
        """지수 백오프 기반 재연결 대기 시간(초) 계산"""
        if attempt <= 0:
            return 0.0
        delay = Config.RECONNECT_BASE_DELAY * (2 ** (attempt - 1))
        return min(delay, Config.RECONNECT_MAX_DELAY)

    def _is_recoverable_webdriver_error(self, error: Exception) -> bool:
        """재연결로 복구 가능한 웹드라이버 오류인지 판단"""
        if isinstance(error, RecoverableWebDriverError):
            return True
        msg = str(error).lower()
        markers = [
            "invalid session",
            "no such execution context",
            "no such window",
            "chrome not reachable",
            "disconnected",
            "target closed",
            "session deleted",
            "connection reset",
            "connection refused",
            "web view not found",
            "browser window not found",
        ]
        return any(marker in msg for marker in markers)

    def _raise_if_recoverable_webdriver_error(
        self, error: Exception, context: str
    ) -> None:
        if isinstance(error, RecoverableWebDriverError):
            raise error
        if self._is_recoverable_webdriver_error(error):
            raise RecoverableWebDriverError(f"{context}: {error}") from error

    def _build_chrome_options(self, headless: bool) -> Options:
        options = Options()
        options.add_argument("--log-level=3")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option(
            "excludeSwitches", ["enable-logging", "enable-automation"]
        )
        options.add_experimental_option("useAutomationExtension", False)

        for argument in Config.CHROME_STABILITY_ARGS:
            options.add_argument(argument)

        if headless:
            options.add_argument("--headless=new")
            options.add_argument(f"--window-size={Config.CHROME_WINDOW_SIZE}")
            self.message_queue.put(("status", "헤드리스 모드로 시작 중..."))

        try:
            setattr(options, "page_load_strategy", str(Config.CHROME_PAGE_LOAD_STRATEGY))
        except Exception:
            logger.debug("Chrome page load strategy 적용 실패", exc_info=True)

        return options

    def _configure_driver_timeouts(self, driver: Any) -> None:
        try:
            driver.set_page_load_timeout(Config.PAGE_LOAD_TIMEOUT)
        except Exception as e:
            logger.debug("page load timeout 적용 실패: %s", e)
        try:
            driver.set_script_timeout(Config.WEBDRIVER_SCRIPT_TIMEOUT)
        except Exception as e:
            logger.debug("script timeout 적용 실패: %s", e)
        try:
            driver.implicitly_wait(Config.WEBDRIVER_IMPLICIT_WAIT)
        except Exception as e:
            logger.debug("implicit wait 적용 실패: %s", e)

    def _ping_driver(self, driver):
        """웹드라이버 응답 시간을 측정 (ms). 실패 시 None 반환."""
        start = time.time()
        try:
            driver.execute_script("return document.readyState || 'complete';")
        except Exception as e:
            logger.debug("드라이버 ping 실패: %s", e)
            return None
        return int((time.time() - start) * 1000)

    def _create_chrome_driver(self, options: Options) -> Any:
        """webdriver monkeypatch 호환성을 유지하면서 Chrome 드라이버 생성"""
        capture_mod = _capture_public()
        chrome_factory = cast(Callable[..., Any], getattr(capture_mod.webdriver, "Chrome"))
        return chrome_factory(options=options)

    def _dispose_driver(
        self,
        driver: Any | None,
        *,
        source: str = "worker_dispose",
        timeout: float | None = None,
    ) -> bool:
        if not driver:
            return True
        quit_succeeded = False
        try:
            quit_timeout = (
                max(0.0, float(timeout))
                if timeout is not None
                else Config.DRIVER_QUIT_TIMEOUT
            )
            force_quit = getattr(self, "_force_quit_driver_with_timeout", None)
            if callable(force_quit):
                quit_succeeded = bool(
                    force_quit(driver, timeout=quit_timeout, source=source)
                )
            else:
                driver.quit()
                quit_succeeded = True
        except Exception as quit_err:
            logger.debug("드라이버 종료 실패, detached 목록에 추가: %s", quit_err)
        finally:
            if not quit_succeeded:
                register_detached = getattr(self, "_register_detached_driver", None)
                if callable(register_detached):
                    register_detached(driver)
                else:
                    with self._detached_drivers_lock:
                        if not any(existing is driver for existing in self._detached_drivers):
                            self._detached_drivers.append(driver)
                schedule_cleanup = getattr(self, "_schedule_detached_driver_cleanup", None)
                if callable(schedule_cleanup):
                    try:
                        schedule_cleanup(timeout=Config.DETACHED_DRIVER_QUIT_TIMEOUT)
                    except Exception:
                        logger.debug("detached driver cleanup 예약 실패", exc_info=True)
            self._clear_current_driver_if(driver)
        return quit_succeeded

    def _resolve_active_selector(
        self, driver: Any, selector_candidates: list[str]
    ) -> tuple[list[str], str]:
        capture_mod = _capture_public()
        wait = capture_mod.WebDriverWait(driver, Config.WEBDRIVER_WAIT_TIMEOUT)
        active_selector = ""

        for sel in selector_candidates:
            try:
                wait.until(
                    capture_mod.EC.presence_of_element_located(
                        (capture_mod.By.CSS_SELECTOR, sel)
                    )
                )
                self.message_queue.put(("status", f"자막 요소 찾음: {sel}"))
                active_selector = sel
                break
            except Exception as e:
                self._raise_if_recoverable_webdriver_error(e, f"자막 요소 대기 실패 ({sel})")
                continue

        if not active_selector:
            detected_selector = self._find_subtitle_selector(driver)
            if detected_selector:
                selector_candidates = self._build_subtitle_selector_candidates(
                    detected_selector, selector_candidates
                )
                active_selector = selector_candidates[0]
                self.message_queue.put(("status", f"자막 요소 자동 감지: {active_selector}"))

        return selector_candidates, active_selector

    def _open_capture_driver_session(
        self,
        options: Options,
        base_url: str,
        selector: str,
        *,
        reconnecting: bool = False,
        cached_live_url: str = "",
    ) -> tuple[Any, str, list[str], str, bool, tuple[int, ...]]:
        driver = None
        connected_url = str(cached_live_url or base_url or "").strip()
        selector_candidates = self._build_subtitle_selector_candidates(selector)

        try:
            driver = self._create_chrome_driver(options)
            self._configure_driver_timeouts(driver)
            self._set_current_driver(driver)
            self.message_queue.put(
                ("status", "Chrome 재시작 완료" if reconnecting else "Chrome 시작 완료")
            )

            self.message_queue.put(("status", "페이지 로딩 중..."))
            driver.get(connected_url)
            connected_url = self._resolve_live_url_for_driver(
                driver,
                connected_url,
                reconnecting=reconnecting,
            )

            self.message_queue.put(("status", "AI 자막 활성화 중..."))
            self._activate_subtitle(driver)
            self.message_queue.put(("status", "자막 요소 검색 중..."))
            selector_candidates, active_selector = self._resolve_active_selector(
                driver, selector_candidates
            )

            base_has_xcgcd = bool(self._get_query_param(base_url, "xcgcd").strip())
            connected_has_xcgcd = bool(
                self._get_query_param(connected_url, "xcgcd").strip()
            )
            should_force_live_refresh = (
                not active_selector
                and reconnecting
                and (bool(cached_live_url) or base_has_xcgcd or connected_has_xcgcd)
            )
            should_retry_live_detect = (
                not active_selector
                and (
                    (
                        bool(cached_live_url)
                        and cached_live_url != base_url
                        and not base_has_xcgcd
                    )
                    or should_force_live_refresh
                )
            )
            if should_retry_live_detect:
                refreshed_url = self._resolve_live_url_for_driver(
                    driver,
                    base_url if not base_has_xcgcd else connected_url,
                    reconnecting=reconnecting,
                    force_refresh=should_force_live_refresh,
                )
                if refreshed_url != connected_url:
                    connected_url = refreshed_url
                    self.message_queue.put(("status", "AI 자막 재활성화 중..."))
                    self._activate_subtitle(driver)
                    self.message_queue.put(("status", "자막 요소 재검색 중..."))
                    selector_candidates, active_selector = self._resolve_active_selector(
                        driver, selector_candidates
                    )

            if not active_selector:
                raise RuntimeError("자막 요소를 찾을 수 없습니다.")

            self.message_queue.put(("status", "자막 모니터링 중"))
            observer_active, observer_frame_path = self._inject_mutation_observer(
                driver, ",".join(selector_candidates)
            )
            return (
                driver,
                connected_url,
                selector_candidates,
                active_selector,
                observer_active,
                observer_frame_path,
            )
        except Exception:
            self._dispose_driver(driver, source="open_session_failure")
            raise

    def _check_driver_health(self, driver: Any) -> tuple[int | None, str]:
        try:
            window_handles = getattr(driver, "window_handles", None)
            if window_handles is not None and len(window_handles) == 0:
                return None, "no window handles"
        except Exception as e:
            return None, f"window_handles access failed: {e}"

        try:
            current_url = str(getattr(driver, "current_url", "") or "").strip()
        except Exception as e:
            return None, f"current_url access failed: {e}"

        ping_latency = self._ping_driver(driver)
        if ping_latency is None:
            return None, f"script ping failed: {current_url or 'unknown-url'}"
        return ping_latency, current_url

    def _resolve_live_url_for_driver(
        self,
        driver: Any,
        url: str,
        *,
        reconnecting: bool = False,
        force_refresh: bool = False,
    ) -> str:
        if self._get_query_param(url, "xcgcd").strip() and not force_refresh:
            return url
        try:
            try:
                resolved_url = self._detect_live_broadcast(
                    driver,
                    url,
                    force_refresh=force_refresh,
                )
            except TypeError as type_error:
                if "force_refresh" not in str(type_error):
                    raise
                resolved_url = self._detect_live_broadcast(driver, url)
            if isinstance(resolved_url, str):
                resolved_url = resolved_url.strip()
            if resolved_url and resolved_url != url:
                self.message_queue.put(("resolved_url", resolved_url))
                self.message_queue.put(("status", "감지된 생중계 URL로 재접속 중..."))
                driver.get(resolved_url)
                return resolved_url
        except Exception as live_err:
            self._raise_if_recoverable_webdriver_error(live_err, "생중계 자동 감지 실패")
            if reconnecting:
                logger.warning("재연결 후 생중계 자동 감지 실패: %s", live_err)
            else:
                logger.warning("생중계 자동 감지 실패: %s", live_err)
        return url

    def _extraction_worker(self, url, selector, headless, run_id: int | None = None):
        """자막 추출 워커 스레드 (Legacy Logic Restoration)"""
        driver = None
        terminal_success = True
        terminal_error = ""
        terminal_finalize_preview = True
        run_id = int(run_id) if run_id is not None else self._ensure_active_capture_run()
        set_worker_run_id = getattr(self.message_queue, "set_worker_run_id", None)
        clear_worker_run_id = getattr(self.message_queue, "clear_worker_run_id", None)
        if callable(set_worker_run_id):
            set_worker_run_id(run_id)

        try:
            requested_url = str(url or "").strip()
            connected_url = requested_url
            options = self._build_chrome_options(headless)

            try:
                (
                    driver,
                    connected_url,
                    selector_candidates,
                    active_selector,
                    observer_active,
                    observer_frame_path,
                ) = self._open_capture_driver_session(
                    options,
                    requested_url,
                    selector,
                    reconnecting=False,
                )
            except Exception as e:
                terminal_success = False
                terminal_error = str(e)
                terminal_finalize_preview = False
                return

            observer_retry_interval = 3.0
            last_observer_retry = time.time()
            last_selector_refresh = time.time()
            last_check = time.time()
            last_connection_check = time.time() - Config.DRIVER_HEALTH_CHECK_INTERVAL
            worker_last_raw_text = ""
            worker_last_raw_compact = ""
            reconnect_attempt = 0
            consecutive_health_failures = 0
            last_keepalive_emit = 0.0

            while not self.stop_event.is_set():
                try:
                    if driver is None:
                        raise RecoverableWebDriverError("브라우저 세션이 없습니다.")

                    now = time.time()

                    if now - last_connection_check >= Config.DRIVER_HEALTH_CHECK_INTERVAL:
                        ping_time, health_detail = self._check_driver_health(driver)
                        if ping_time is not None:
                            self.message_queue.put(
                                ("connection_status", {"status": "connected", "latency": ping_time})
                            )
                            reconnect_attempt = 0
                            consecutive_health_failures = 0
                        else:
                            self.message_queue.put(
                                ("connection_status", {"status": "disconnected"})
                            )
                            consecutive_health_failures += 1
                            logger.warning(
                                "드라이버 헬스체크 실패 (%s/%s): %s",
                                consecutive_health_failures,
                                Config.DRIVER_HEALTH_FAILURE_THRESHOLD,
                                health_detail,
                            )
                            if (
                                consecutive_health_failures
                                >= Config.DRIVER_HEALTH_FAILURE_THRESHOLD
                            ):
                                raise RecoverableWebDriverError(
                                    f"브라우저 헬스체크 실패: {health_detail}"
                                )
                        last_connection_check = now

                    if now - last_check >= Config.SUBTITLE_CHECK_INTERVAL:
                        used_structured_probe = False
                        if observer_active:
                            observer_changes = self._collect_observer_changes(
                                driver, observer_frame_path
                            )
                            if observer_changes is None:
                                observer_active = False
                                logger.warning("MutationObserver 비활성화, polling fallback")
                            elif observer_changes:
                                should_reset = any(
                                    change == "__SUBTITLE_CLEARED__"
                                    or (
                                        isinstance(change, dict)
                                        and str(change.get("kind") or "").strip() == "reset"
                                    )
                                    for change in observer_changes
                                )
                                if should_reset:
                                    used_structured_probe = True
                                    self.message_queue.put(
                                        ("subtitle_reset", "observer_cleared")
                                    )
                                    worker_last_raw_text = ""
                                    worker_last_raw_compact = ""
                                    last_keepalive_emit = 0.0

                        if not used_structured_probe:
                            preferred_frame_path = (
                                observer_frame_path if observer_active else ()
                            ) or getattr(self, "_last_subtitle_frame_path", ())
                            probe = self._read_subtitle_probe_by_selectors(
                                driver,
                                selector_candidates,
                                preferred_frame_path=preferred_frame_path,
                            )
                            text = self._normalize_subtitle_text_for_option(
                                probe.get("text", "") or ""
                            ).strip()
                            matched_selector = str(probe.get("matched_selector", "") or "")
                            selector_found = bool(probe.get("found", False))
                            text_compact = utils.compact_subtitle_text(text)

                            if selector_found:
                                reconnect_attempt = 0
                                consecutive_health_failures = 0
                                if matched_selector and matched_selector != active_selector:
                                    active_selector = matched_selector
                                    selector_candidates = self._build_subtitle_selector_candidates(
                                        active_selector, selector_candidates
                                    )
                            elif now - last_selector_refresh >= 5.0:
                                detected_selector = self._find_subtitle_selector(driver)
                                if detected_selector:
                                    selector_candidates = self._build_subtitle_selector_candidates(
                                        detected_selector, selector_candidates
                                    )
                                    active_selector = selector_candidates[0]
                                    logger.info("자막 선택자 자동 전환: %s", active_selector)
                                last_selector_refresh = now

                            if (
                                not observer_active
                                and now - last_observer_retry >= observer_retry_interval
                            ):
                                observer_active, observer_frame_path = self._inject_mutation_observer(
                                    driver, ",".join(selector_candidates)
                                )
                                last_observer_retry = now

                            if text and text_compact and text_compact != worker_last_raw_compact:
                                worker_last_raw_text = text
                                worker_last_raw_compact = text_compact
                                last_keepalive_emit = now
                                self.message_queue.put(
                                    ("preview", self._build_preview_payload_from_probe(probe))
                                )
                            elif (
                                text
                                and text_compact
                                and text_compact == worker_last_raw_compact
                                and (now - last_keepalive_emit >= Config.SUBTITLE_KEEPALIVE_INTERVAL)
                            ):
                                self.message_queue.put(("keepalive", text))
                                last_keepalive_emit = now
                            elif not text and selector_found and worker_last_raw_compact:
                                self.message_queue.put(
                                    ("subtitle_reset", "polling_cleared")
                                )
                                worker_last_raw_text = ""
                                worker_last_raw_compact = ""
                                last_keepalive_emit = 0.0

                        last_check = now

                    self.stop_event.wait(timeout=0.05)

                except Exception as e:
                    if self.stop_event.is_set():
                        break

                    recoverable_error = self._is_recoverable_webdriver_error(e)
                    if self.auto_reconnect_enabled and recoverable_error:
                        reconnect_attempt += 1
                        if reconnect_attempt <= Config.MAX_RECONNECT_ATTEMPTS:
                            delay = self._get_reconnect_delay(reconnect_attempt)
                            self.message_queue.put(
                                (
                                    "reconnecting",
                                    {
                                        "attempt": reconnect_attempt,
                                        "max_attempts": Config.MAX_RECONNECT_ATTEMPTS,
                                        "delay": delay,
                                    },
                                )
                            )
                            logger.warning(
                                "WebDriver 연결 오류, %s초 후 재연결 시도 (%s/%s)",
                                delay,
                                reconnect_attempt,
                                Config.MAX_RECONNECT_ATTEMPTS,
                            )

                            self._dispose_driver(
                                driver,
                                source=f"reconnect_attempt_{reconnect_attempt}",
                            )
                            driver = None

                            if self.stop_event.wait(timeout=delay):
                                break

                            try:
                                (
                                    driver,
                                    connected_url,
                                    selector_candidates,
                                    active_selector,
                                    observer_active,
                                    observer_frame_path,
                                ) = self._open_capture_driver_session(
                                    options,
                                    requested_url,
                                    selector,
                                    reconnecting=True,
                                    cached_live_url=connected_url,
                                )
                                self.message_queue.put(
                                    ("status", f"✅ 재연결 성공 (시도 {reconnect_attempt})")
                                )
                                self.message_queue.put(
                                    (
                                        "reconnected",
                                        {"attempt": reconnect_attempt, "url": connected_url},
                                    )
                                )
                                self.message_queue.put(
                                    ("connection_status", {"status": "connected"})
                                )
                                now = time.time()
                                last_check = now
                                last_connection_check = (
                                    now - Config.DRIVER_HEALTH_CHECK_INTERVAL
                                )
                                last_selector_refresh = now
                                last_observer_retry = now
                                worker_last_raw_text = ""
                                worker_last_raw_compact = ""
                                last_keepalive_emit = 0.0
                                consecutive_health_failures = 0
                                continue
                            except Exception as reconnect_error:
                                logger.error(f"재연결 실패: {reconnect_error}")
                                driver = None
                        else:
                            terminal_success = False
                            terminal_error = (
                                f"최대 재연결 시도 횟수({Config.MAX_RECONNECT_ATTEMPTS}) 초과"
                            )
                            break
                    elif recoverable_error:
                        logger.error("재연결 비활성 상태에서 WebDriver 오류로 수집 종료: %s", e)
                        self.message_queue.put(("connection_status", {"status": "disconnected"}))
                        terminal_success = False
                        terminal_error = f"Chrome 연결이 끊겨 수집을 종료합니다: {e}"
                        break
                    else:
                        logger.warning(f"모니터링 중 오류: {e}")
                        self.stop_event.wait(timeout=0.5)

        except Exception as e:
            if not self.stop_event.is_set():
                terminal_success = False
                terminal_error = str(e)

        finally:
            preserve_driver = False
            if driver is not None and bool(
                self.__dict__.get("_preserve_driver_on_worker_stop", False)
            ):
                try:
                    preserve_driver = self._get_current_driver() is driver
                except Exception:
                    preserve_driver = False
            if not preserve_driver:
                self._dispose_driver(driver, source="worker_finally")
            if callable(clear_worker_run_id):
                clear_worker_run_id()
            self.message_queue.put(
                (
                    "finished",
                    {
                        "success": terminal_success,
                        "error": terminal_error,
                        "finalize_preview": terminal_finalize_preview,
                    },
                )
            )
