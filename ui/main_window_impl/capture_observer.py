# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import TYPE_CHECKING

from core.logging_utils import logger
from ui.main_window_impl.contracts import CaptureObserverHost


CaptureObserverBase = CaptureObserverHost if TYPE_CHECKING else object


class MainWindowCaptureObserverMixin(CaptureObserverBase):
    def _inject_mutation_observer_here(
        self, driver, selector: str, allow_poll_fallback: bool = False
    ) -> bool:
        """현재 문맥(현재 frame)에서 Observer를 주입한다."""
        default_selector = (
            "#viewSubtit .smi_word:last-child, #viewSubtit .smi_word, "
            "#viewSubtit .incont, #viewSubtit, .subtitle_area"
        )
        safe_selector = (
            selector if isinstance(selector, str) and selector.strip() else default_selector
        )
        result = driver.execute_script(
            """
            return (function(selectorArg, allowPollFallbackArg) {
                if (window.__subtitleObserver) {
                    try { window.__subtitleObserver.disconnect(); } catch(e) {}
                }
                if (window.__subtitlePollTimer) {
                    try { clearInterval(window.__subtitlePollTimer); } catch(e) {}
                    window.__subtitlePollTimer = null;
                }
                window.__subtitleBuffer = [];
                window.__subtitleLastText = '';
                window.__subtitleLastEmitTs = 0;

                var rawSelector = (typeof selectorArg === 'string') ? selectorArg : '';
                var allowPollFallback = !!allowPollFallbackArg;
                var selectors = rawSelector
                    .split(',')
                    .map(function(s) { return (s || '').trim(); })
                    .filter(function(s) { return s.length > 0; });
                if (!selectors.length) {
                    selectors = [
                        '#viewSubtit .smi_word:last-child',
                        '#viewSubtit .smi_word',
                        '#viewSubtit .incont',
                        '#viewSubtit',
                        '.subtitle_area',
                        '.ai_subtitle',
                        "[class*='subtitle']"
                    ];
                }

                var targetSelectors = [];
                function pushUnique(arr, value) {
                    if (!value) return;
                    for (var i = 0; i < arr.length; i++) {
                        if (arr[i] === value) return;
                    }
                    arr.push(value);
                }
                for (var s = 0; s < selectors.length; s++) {
                    pushUnique(targetSelectors, selectors[s]);
                }
                var containerFallback = [
                    '#viewSubtit .incont',
                    '#viewSubtit',
                    '.subtitle_area',
                    '.ai_subtitle',
                    "[class*='subtitle']"
                ];
                for (var c = 0; c < containerFallback.length; c++) {
                    pushUnique(targetSelectors, containerFallback[c]);
                }

                var target = null;
                var matchedTargetSelector = '';
                for (var i = 0; i < targetSelectors.length; i++) {
                    try {
                        target = document.querySelector(targetSelectors[i]);
                    } catch (e) {
                        target = null;
                    }
                    if (target) {
                        matchedTargetSelector = targetSelectors[i];
                        break;
                    }
                }

                function normalizeText(text) {
                    return String(text || '').replace(/\\s+/g, ' ').trim();
                }

                function isLikelySubtitleText(text) {
                    // 파이프라인 is_meaningful_subtitle_text 와 정렬:
                    // 한글/영문이 1자라도 있으면 길이 하한 없이 허용 (네/예 등)
                    if (!text) return false;
                    if (text.length > 320) return false;
                    if (!/[가-힣A-Za-z]/.test(text)) return false;
                    if (/^[\\d\\s:.,\\-_/()%]+$/.test(text)) return false;
                    return true;
                }

                function pushResetEvent(selector, previousText) {
                    window.__subtitleBuffer.push({
                        kind: 'reset',
                        source: 'observer_cleared',
                        selector: selector || '',
                        previousLength: String(previousText || '').length
                    });
                }

                if (target) {
                    window.__subtitleObserver = new MutationObserver(function() {
                        try {
                            var text = target.innerText || target.textContent || '';
                            text = normalizeText(text);
                            if (text && text.length > 400) {
                                var lines = String(target.innerText || '').split('\\n')
                                    .map(function(v) { return normalizeText(v); })
                                    .filter(function(v) { return !!v; });
                                if (lines.length) {
                                    text = lines.slice(-3).join(' ');
                                }
                            }
                            if (!text && window.__subtitleLastText) {
                                pushResetEvent(matchedTargetSelector, window.__subtitleLastText);
                                window.__subtitleLastText = '';
                                return;
                            }
                            if (text && text !== window.__subtitleLastText) {
                                window.__subtitleLastText = text;
                                window.__subtitleBuffer.push(text);
                                if (window.__subtitleBuffer.length > 100) {
                                    window.__subtitleBuffer = window.__subtitleBuffer.slice(-50);
                                }
                            }
                        } catch (e) {}
                    });

                    window.__subtitleObserver.observe(target, {
                        childList: true,
                        subtree: true,
                        characterData: true,
                        attributes: true
                    });
                    return true;
                }

                var root = document.body || document.documentElement;
                if (!root || !allowPollFallback) return false;

                window.__subtitlePollTimer = setInterval(function() {
                    try {
                        var now = Date.now();
                        if (now - (window.__subtitleLastEmitTs || 0) < 100) {
                            return;
                        }
                        var liveTarget = null;
                        for (var i = 0; i < selectors.length; i++) {
                            try {
                                liveTarget = document.querySelector(selectors[i]);
                            } catch (e) {
                                liveTarget = null;
                            }
                            if (liveTarget) break;
                        }
                        if (!liveTarget) {
                            return;
                        }

                        var text = normalizeText(liveTarget.innerText || liveTarget.textContent || '');
                        if (!text && window.__subtitleLastText) {
                            pushResetEvent('', window.__subtitleLastText);
                            window.__subtitleLastText = '';
                            window.__subtitleLastEmitTs = now;
                            return;
                        }
                        if (!text || !isLikelySubtitleText(text)) {
                            return;
                        }
                        if (text && text !== window.__subtitleLastText) {
                            window.__subtitleLastText = text;
                            window.__subtitleLastEmitTs = now;
                            window.__subtitleBuffer.push(text);
                            if (window.__subtitleBuffer.length > 100) {
                                window.__subtitleBuffer = window.__subtitleBuffer.slice(-50);
                            }
                        }
                    } catch (e) {
                    }
                }, 180);
                return true;
            })(arguments[0], arguments[1]);
            """,
            safe_selector,
            allow_poll_fallback,
        )
        return bool(result)

    def _inject_mutation_observer(self, driver, selector: str) -> tuple[bool, tuple[int, ...]]:
        """MutationObserver를 페이지에 주입하여 자막 변경을 이벤트 기반으로 캡처한다."""
        try:
            safe_selector = selector if isinstance(selector, str) else ""
            priority_paths: list[tuple[int, ...]] = []
            last_path = getattr(self, "_last_subtitle_frame_path", ())
            if isinstance(last_path, tuple):
                priority_paths.append(last_path)
            priority_paths.append(())
            for path in self._iter_frame_paths(driver, max_depth=3, max_frames=60):
                if path not in priority_paths:
                    priority_paths.append(path)

            for frame_path in priority_paths:
                if not self._switch_to_frame_path(driver, frame_path):
                    continue
                if self._inject_mutation_observer_here(
                    driver, safe_selector, allow_poll_fallback=False
                ):
                    location = "default" if frame_path == () else f"frame={frame_path}"
                    logger.info(
                        "MutationObserver 주입 성공: %s (%s)", location, safe_selector
                    )
                    return True, frame_path

            for frame_path in priority_paths:
                if not self._switch_to_frame_path(driver, frame_path):
                    continue
                if self._inject_mutation_observer_here(
                    driver, safe_selector, allow_poll_fallback=True
                ):
                    location = "default" if frame_path == () else f"frame={frame_path}"
                    logger.info(
                        "MutationObserver 폴링 브리지 활성화: %s (%s)",
                        location,
                        safe_selector,
                    )
                    return True, frame_path

            logger.warning("MutationObserver 주입 실패: 대상 요소 없음 (%s)", safe_selector)
            return False, ()
        except Exception as e:
            self._raise_if_recoverable_webdriver_error(e, "MutationObserver 주입 오류")
            logger.warning("MutationObserver 주입 오류: %s", e)
            return False, ()
        finally:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass

    def _collect_observer_changes(
        self, driver, frame_path: tuple[int, ...] = ()
    ) -> list | None:
        """MutationObserver 버퍼에서 변경된 텍스트를 수집한다."""
        try:
            if not self._switch_to_frame_path(driver, frame_path):
                return None
            result = driver.execute_script(
                """
                if (!window.__subtitleBuffer) return null;
                var buf = window.__subtitleBuffer;
                window.__subtitleBuffer = [];
                return buf;
                """
            )
            if result is None:
                return None
            return result if isinstance(result, list) else []
        except Exception as e:
            self._raise_if_recoverable_webdriver_error(e, "Observer 버퍼 수집 오류")
            logger.debug("Observer 버퍼 수집 오류: %s", e)
            return None
        finally:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass

    def _activate_subtitle(self, driver) -> bool:
        """자막 레이어 활성화.

        크롬 확장(subtitle-layer)과 같이:
        - AI 버튼을 일반 자막보다 우선
        - 이미 ON(active)인 컨트롤은 재클릭하지 않음 (토글 OFF 방지)
        - layerSubtit() 만으로 끝내지 않고 AI active를 재확인
        """
        # 단일 스크립트로 active 검사 + 클릭 우선순위를 처리한다.
        # (querySelector 성공 ≠ 활성화 성공 — ON 상태 재클릭 금지)
        activation_script = """
            return (function() {
                function isActive(el) {
                    if (!el) return false;
                    var className = String(el.className || '');
                    var title = String(el.getAttribute('title') || '');
                    var aria = String(el.getAttribute('aria-pressed') || '');
                    return /\\bon\\b/i.test(className)
                        || /(끄기|닫기)/.test(title)
                        || aria === 'true';
                }
                function query(sel) {
                    try { return document.querySelector(sel); } catch (e) { return null; }
                }
                var aiSelectors = ['.btn_subtit_ai', '.btn_subtit_def'];
                var genericSelectors = [
                    '.btn_subtit', '#smi_btn', '#btnSubtit',
                    "[data-action='subtitle']", '.Subtitle'
                ];

                // 1) 이미 AI/자막 컨트롤이 ON 이면 성공 (클릭 없음)
                for (var i = 0; i < aiSelectors.length; i++) {
                    var a = query(aiSelectors[i]);
                    if (a && isActive(a)) {
                        return { ok: true, method: 'already-active', selector: aiSelectors[i] };
                    }
                }

                // 2) 페이지 함수 (레이어 오픈 시도) — 이후 AI active 재확인
                if (typeof layerSubtit === 'function') {
                    try { layerSubtit(); } catch (e) {}
                }
                for (var j = 0; j < aiSelectors.length; j++) {
                    var a2 = query(aiSelectors[j]);
                    if (a2 && isActive(a2)) {
                        return { ok: true, method: 'layerSubtit', selector: aiSelectors[j] };
                    }
                }

                // 3) AI 버튼: inactive 일 때만 클릭
                for (var k = 0; k < aiSelectors.length; k++) {
                    var btn = query(aiSelectors[k]);
                    if (!btn) continue;
                    if (isActive(btn)) {
                        return { ok: true, method: 'already-active', selector: aiSelectors[k] };
                    }
                    try { btn.click(); } catch (e) { continue; }
                    return { ok: true, method: 'click', selector: aiSelectors[k] };
                }

                // 4) 일반 자막 컨트롤
                for (var g = 0; g < genericSelectors.length; g++) {
                    var gbtn = query(genericSelectors[g]);
                    if (!gbtn) continue;
                    if (isActive(gbtn)) {
                        return { ok: true, method: 'already-active', selector: genericSelectors[g] };
                    }
                    try { gbtn.click(); } catch (e) { continue; }
                    return { ok: true, method: 'click', selector: genericSelectors[g] };
                }

                // 5) 최후: 레이어 display (토글 위험 없는 스타일 강제)
                var layer = query('#viewSubtit');
                if (layer) {
                    try { layer.style.display = 'block'; } catch (e) {}
                    return { ok: true, method: 'display-block', selector: '#viewSubtit' };
                }
                return { ok: false, method: 'none', selector: '' };
            })();
        """

        activated = False
        try:
            result = driver.execute_script(activation_script)
            if isinstance(result, dict):
                activated = bool(result.get("ok"))
                if activated:
                    logger.info(
                        "자막 활성화 성공 (method=%s, selector=%s)",
                        result.get("method"),
                        result.get("selector"),
                    )
                else:
                    logger.warning("자막 활성화 실패: 컨트롤/레이어 없음")
            else:
                activated = bool(result)
        except Exception as e:
            logger.debug(f"자막 활성화 스크립트 실패: {e}")

        self.stop_event.wait(timeout=2.0)
        return activated

    def _find_subtitle_selector(self, driver) -> str:
        """사용 가능한 자막 셀렉터 자동 감지"""
        selectors = [
            "#viewSubtit .smi_word:last-child",
            "#viewSubtit .smi_word",
            "#viewSubtit .incont",
            "#viewSubtit span",
            "#viewSubtit",
            ".subtitle_area",
            ".ai_subtitle",
            "[class*='subtitle']",
        ]

        text, matched_selector, found = self._read_subtitle_text_by_selectors(
            driver, selectors
        )
        if found and matched_selector:
            if text and len(text) > 2:
                logger.info(f"자막 셀렉터 발견: {matched_selector}")
            return matched_selector
        return ""
