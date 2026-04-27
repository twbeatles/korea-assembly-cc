# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportAssignmentType=false

from __future__ import annotations

import json
import re
from importlib import import_module
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.config import Config
from core.live_list import (
    apply_live_broadcast_to_url,
    build_live_list_url,
    make_live_list_error_payload,
    normalize_live_list_row,
    parse_live_list_payload,
    select_live_broadcast_row,
    summarize_live_selection_issue,
)
from core.logging_utils import logger
from ui.main_window_impl.contracts import CaptureLiveHost


def _capture_public() -> Any:
    return import_module("ui.main_window_capture")


CaptureLiveBase = object


class MainWindowCaptureLiveMixin(CaptureLiveBase):
    def _get_query_param(self, url: str, name: str) -> str:
        """URL 쿼리 파라미터 값 추출 (없으면 빈 문자열)"""
        match = re.search(r"(?:^|[?&])" + re.escape(name) + r"=([^&]*)", url)
        return match.group(1) if match else ""

    def _set_query_param(self, url: str, name: str, value: str) -> str:
        """URL 쿼리 파라미터 설정/교체"""
        base_url = url.strip().rstrip("&")
        pattern = re.compile(r"([?&])" + re.escape(name) + r"=[^&]*")
        if pattern.search(base_url):
            return pattern.sub(
                lambda m: f"{m.group(1)}{name}={value}", base_url, count=1
            )
        sep = "&" if "?" in base_url else "?"
        return f"{base_url}{sep}{name}={value}"

    def _fetch_live_list(self):
        """국회 생중계 목록 API에서 현재 방송 목록 가져오기"""
        api_url = build_live_list_url()
        try:
            req = Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=Config.LIVE_LIST_REQUEST_TIMEOUT_MS / 1000.0) as response:
                payload = response.read()
            return parse_live_list_payload(payload)
        except HTTPError as exc:
            logger.debug(f"live_list API 오류: {exc}")
            return make_live_list_error_payload("http_error", str(exc))
        except URLError as exc:
            logger.debug(f"live_list API 오류: {exc}")
            return make_live_list_error_payload("network", str(exc))
        except Exception as e:
            logger.debug(f"live_list 처리 오류: {e}")
            return make_live_list_error_payload("unknown", str(e))

    def _notify_live_selection_issue(
        self,
        reason: str,
        *,
        target_xcode: str | None = None,
        candidate_count: int = 0,
    ) -> None:
        message = summarize_live_selection_issue(
            reason,
            target_xcode=target_xcode,
            candidate_count=candidate_count,
        )
        logger.warning(message)
        try:
            self.message_queue.put(("status", f"⚠️ {message}"))
        except Exception:
            pass
        try:
            self.message_queue.put(
                (
                    "toast",
                    {
                        "message": message,
                        "toast_type": "warning",
                        "duration": 4500,
                    },
                )
            )
        except Exception:
            pass

    def _resolve_live_url_from_payload(
        self,
        original_url: str,
        payload: dict[str, object] | object,
        target_xcode: str | None,
    ) -> tuple[str, dict[str, object] | None]:
        if isinstance(payload, list):
            payload = {"ok": True, "result": payload, "error_type": "none"}
        if not isinstance(payload, dict) or not payload.get("ok"):
            if isinstance(payload, dict):
                logger.debug(
                    "live_list 응답 무시 (%s): %s",
                    payload.get("error_type", "unknown"),
                    payload.get("error", "알 수 없는 오류"),
                )
            return original_url, None

        broadcasts = payload.get("result")
        if not isinstance(broadcasts, list) or not broadcasts:
            return original_url, None

        current_xcgcd = self._get_query_param(original_url, "xcgcd").strip()
        target_norm = target_xcode.strip() if target_xcode else ""
        selection = select_live_broadcast_row(
            broadcasts,
            target_xcode=target_norm or None,
            current_xcgcd=current_xcgcd or None,
        )
        if not selection.get("ok"):
            return original_url, selection

        row = selection.get("row")
        if not isinstance(row, dict):
            return original_url, None
        new_url = apply_live_broadcast_to_url(original_url, row)
        logger.info(
            "live_list 매칭 성공: reason=%s, xcode=%s, xcgcd=%s",
            selection.get("reason", "unknown"),
            row.get("xcode", ""),
            row.get("xcgcd", ""),
        )
        return new_url, selection

    def _show_live_dialog(self):
        """생중계 목록 다이얼로그 표시"""
        if self._is_runtime_mutation_blocked("생중계 목록 변경"):
            return
        capture_mod = _capture_public()
        dialog = capture_mod.LiveBroadcastDialog(self)
        dialog.finished.connect(dialog.deleteLater)
        if dialog.exec():
            data = dialog.selected_broadcast
            if data:
                xstat = str(data.get("xstat", "")).strip()
                if xstat != "1":
                    reply = capture_mod.QMessageBox.question(
                        self,
                        "종료/예정 방송 선택",
                        "선택한 항목은 현재 생중계 상태가 아닙니다.\n"
                        "그래도 URL을 입력하시겠습니까?",
                        capture_mod.QMessageBox.StandardButton.Yes
                        | capture_mod.QMessageBox.StandardButton.No,
                    )
                    if reply != capture_mod.QMessageBox.StandardButton.Yes:
                        return

                xcode = str(data.get("xcode", "")).strip()
                xcgcd = str(data.get("xcgcd", "")).strip()

                if xcode and xcgcd:
                    base_url = "https://assembly.webcast.go.kr/main/player.asp"
                    new_url = f"{base_url}?xcode={xcode}&xcgcd={xcgcd}"
                    name = data.get("xname", "").strip()
                    self._add_to_history(new_url, name)
                    idx = self.url_combo.findData(new_url)
                    if idx >= 0:
                        self.url_combo.setCurrentIndex(idx)
                    else:
                        self.url_combo.setEditText(new_url)
                    self._show_toast(
                        f"방송이 선택되었습니다:\n{name}", toast_type="success"
                    )

    def _resolve_live_url_from_list(
        self, original_url: str, target_xcode: str | None
    ) -> str:
        """live_list API로 xcgcd/xcode를 보완하여 URL 생성"""
        resolved_url, _selection = self._resolve_live_url_from_payload(
            original_url,
            self._fetch_live_list(),
            target_xcode,
        )
        return resolved_url

    def _extract_live_candidates_from_page(self, driver) -> list[dict[str, str]]:
        script = """
        var results = [];
        var seen = {};
        function addCandidate(xcgcd, xcode, name) {
            if (!xcgcd) return;
            var normalizedXcgcd = String(xcgcd).trim();
            if (!normalizedXcgcd) return;
            var normalizedXcode = xcode ? String(xcode).trim() : "";
            var key = normalizedXcgcd + "|" + normalizedXcode;
            if (seen[key]) return;
            seen[key] = true;
            results.push({
                xstat: "1",
                xcgcd: normalizedXcgcd,
                xcode: normalizedXcode,
                xname: name ? String(name).trim() : "",
                time: ""
            });
        }
        function extractQueryParam(value, key) {
            if (!value) return "";
            var match = String(value).match(new RegExp(key + "=([^&]+)"));
            return match ? match[1] : "";
        }
        var links = document.querySelectorAll('a[href*="xcgcd="]');
        for (var i = 0; i < links.length; i++) {
            var href = links[i].getAttribute('href') || "";
            addCandidate(
                extractQueryParam(href, "xcgcd"),
                extractQueryParam(href, "xcode"),
                links[i].innerText || links[i].textContent || ""
            );
        }
        var iframes = document.querySelectorAll('iframe[src*="xcgcd="]');
        for (var j = 0; j < iframes.length; j++) {
            var src = iframes[j].getAttribute('src') || "";
            addCandidate(
                extractQueryParam(src, "xcgcd"),
                extractQueryParam(src, "xcode"),
                iframes[j].getAttribute('title') || ""
            );
        }
        var input = document.querySelector('input[name="xcgcd"], input#xcgcd');
        if (input) {
            addCandidate(
                input.value || "",
                "",
                ""
            );
        }
        return JSON.stringify(results);
        """
        try:
            raw_payload = driver.execute_script(script)
            parsed = json.loads(raw_payload) if raw_payload else []
        except Exception as exc:
            logger.debug("페이지 생중계 후보 추출 오류: %s", exc)
            return []

        candidates: list[dict[str, str]] = []
        for item in parsed:
            normalized = normalize_live_list_row(item)
            if normalized is not None:
                candidates.append(normalized)
        return candidates

    def _detect_live_broadcast(
        self,
        driver,
        original_url: str,
        *,
        force_refresh: bool = False,
    ) -> str:
        """현재 진행 중인 생중계의 xcgcd를 자동 감지"""
        capture_mod = _capture_public()
        try:
            existing_xcgcd = self._get_query_param(original_url, "xcgcd").strip()
            existing_xcode = self._get_query_param(original_url, "xcode").strip()

            if existing_xcgcd and existing_xcode and not force_refresh:
                logger.info(f"URL에 이미 xcode/xcgcd 포함됨: {original_url}")
                return original_url

            self.message_queue.put(("status", "🔍 현재 생중계 감지 중..."))
            target_xcode = existing_xcode or None
            target_xcode_norm = target_xcode.upper() if target_xcode else None
            logger.info(f"xcgcd 탐색 시작 - target_xcode: {target_xcode}")

            live_list_issue: dict[str, object] | None = None
            resolved_url, live_list_issue = self._resolve_live_url_from_payload(
                original_url,
                self._fetch_live_list(),
                target_xcode,
            )
            if resolved_url != original_url and self._get_query_param(
                resolved_url, "xcgcd"
            ):
                logger.info(f"live_list 기반 URL 감지 성공: {resolved_url}")
                return resolved_url

            def extract_xcode_from_xcgcd(xcgcd_val):
                if not xcgcd_val:
                    return None
                match = re.search(r"DCM0000([A-Za-z0-9]+)", xcgcd_val)
                if match:
                    code = match.group(1)
                    num_match = re.match(r"^(\d{2})", code)
                    if num_match:
                        return num_match.group(1)
                    alpha_match = re.match(r"^([A-Za-z]+)", code)
                    if alpha_match:
                        return alpha_match.group(1)
                return None

            scripts = [
                "return typeof xcgcd !== 'undefined' ? xcgcd : null;",
                "return typeof XCGCD !== 'undefined' ? XCGCD : null;",
                "return window.xcgcd || null;",
                "return window.XCGCD || null;",
                "return new URLSearchParams(window.location.search).get('xcgcd');",
                "if(typeof streamInfo !== 'undefined' && streamInfo.xcgcd) return streamInfo.xcgcd; return null;",
                "if(typeof playerConfig !== 'undefined' && playerConfig.xcgcd) return playerConfig.xcgcd; return null;",
            ]

            xcgcd = None
            for script in scripts:
                try:
                    result = driver.execute_script(script)
                    if result:
                        found_xcgcd = str(result)
                        if target_xcode:
                            found_xcode = extract_xcode_from_xcgcd(found_xcgcd)
                            if (
                                found_xcode
                                and target_xcode_norm
                                and found_xcode.upper() != target_xcode_norm
                            ):
                                logger.warning(
                                    f"JavaScript xcgcd의 xcode({found_xcode})가 target({target_xcode})와 불일치 - 무시"
                                )
                                continue
                        xcgcd = found_xcgcd
                        logger.info(f"JavaScript에서 xcgcd 발견: {xcgcd}")
                        break
                except Exception as e:
                    logger.debug(f"Script 실행 오류: {e}")

            if not xcgcd:
                current_url = driver.current_url
                found_xcgcd = self._get_query_param(current_url, "xcgcd").strip()
                if found_xcgcd:
                    if target_xcode:
                        found_xcode = extract_xcode_from_xcgcd(found_xcgcd)
                        if (
                            found_xcode
                            and target_xcode_norm
                            and found_xcode.upper() != target_xcode_norm
                        ):
                            logger.warning(
                                f"리다이렉트된 xcgcd의 xcode({found_xcode})가 target({target_xcode})와 불일치 - 무시"
                            )
                        else:
                            xcgcd = found_xcgcd
                            logger.info(f"리다이렉트된 URL에서 xcgcd 발견: {xcgcd}")
                    else:
                        xcgcd = found_xcgcd
                        logger.info(f"리다이렉트된 URL에서 xcgcd 발견: {xcgcd}")

            if not xcgcd:
                current_page_candidates = self._extract_live_candidates_from_page(driver)
                if current_page_candidates:
                    logger.info(
                        "현재 페이지 생중계 후보 발견: %s개",
                        len(current_page_candidates),
                    )
                    selection = select_live_broadcast_row(
                        current_page_candidates,
                        target_xcode=target_xcode,
                    )
                    if selection.get("ok") and isinstance(selection.get("row"), dict):
                        row = selection["row"]
                        xcgcd = str(row.get("xcgcd", "")).strip()
                        logger.info(
                            "페이지 후보 매칭 성공: reason=%s, xcode=%s, xcgcd=%s",
                            selection.get("reason", "unknown"),
                            row.get("xcode", ""),
                            xcgcd,
                        )
                    else:
                        live_list_issue = selection

            navigated_to_main = False
            if not xcgcd:
                try:
                    main_url = "https://assembly.webcast.go.kr/main/"
                    self.message_queue.put(
                        ("status", "🔍 메인 페이지에서 생중계 목록 확인 중...")
                    )
                    driver.get(main_url)
                    navigated_to_main = True
                    try:
                        wait = capture_mod.WebDriverWait(driver, 10)
                        wait.until(
                            capture_mod.EC.presence_of_element_located(
                                (capture_mod.By.CSS_SELECTOR, 'a[href*="xcgcd="]')
                            )
                        )
                    except Exception:
                        self.stop_event.wait(timeout=3)

                    broadcasts = self._extract_live_candidates_from_page(driver)
                    logger.info(f"발견된 생중계 목록: {len(broadcasts)}개")

                    if broadcasts:
                        selection = select_live_broadcast_row(
                            broadcasts,
                            target_xcode=target_xcode,
                        )
                        if selection.get("ok") and isinstance(selection.get("row"), dict):
                            row = selection["row"]
                            xcgcd = str(row.get("xcgcd", "")).strip()
                            logger.info(
                                "메인 페이지 후보 매칭 성공: reason=%s, xcode=%s, xcgcd=%s",
                                selection.get("reason", "unknown"),
                                row.get("xcode", ""),
                                xcgcd,
                            )
                        else:
                            live_list_issue = selection
                except Exception as e:
                    logger.debug(f"메인 페이지 조회 오류: {e}")

            issue_reason = (
                str(live_list_issue.get("reason", "") or "").strip()
                if isinstance(live_list_issue, dict)
                else ""
            )
            if not xcgcd and target_xcode and issue_reason != "ambiguous_xcode":
                current_url = driver.current_url
                if "/main/player.asp" not in current_url:
                    try:
                        self.message_queue.put(
                            (
                                "status",
                                f"🖱️ 메인 화면에서 xcode={target_xcode} 버튼 탐색 중...",
                            )
                        )
                        logger.info(
                            f"메인 페이지 리다이렉트 감지 - 버튼 클릭 시도 (xcode={target_xcode})"
                        )
                        try:
                            capture_mod.WebDriverWait(driver, 10).until(
                                capture_mod.EC.presence_of_element_located(
                                    (capture_mod.By.CSS_SELECTOR, ".onair")
                                )
                            )
                        except Exception:
                            logger.debug(
                                "onair 요소 대기 타임아웃 (생중계가 없거나 로딩 지연)"
                            )

                        selectors = [
                            f'a.onair[href*="xcode={target_xcode}"]',
                            f'a.btn[href*="xcode={target_xcode}"]',
                            f'div.onair a[href*="xcode={target_xcode}"]',
                            f'a[href*="xcode={target_xcode}"]:has(.icon_onair)',
                            f'a[href*="xcode={target_xcode}"]',
                        ]

                        btn = None
                        for sel in selectors:
                            try:
                                elems = driver.find_elements(capture_mod.By.CSS_SELECTOR, sel)
                                for elem in elems:
                                    if "onair" in elem.get_attribute("class") or elem.find_elements(
                                        capture_mod.By.CSS_SELECTOR, ".onair"
                                    ):
                                        btn = elem
                                        break
                                if btn:
                                    break
                                if elems and not btn:
                                    btn = elems[0]
                                    break
                            except Exception:
                                continue

                        if btn:
                            driver.execute_script(
                                "arguments[0].scrollIntoView({block: 'center'});", btn
                            )
                            self.stop_event.wait(timeout=1.0)
                            driver.execute_script("arguments[0].click();", btn)
                            logger.info(
                                f"메인 페이지에서 생중계 버튼 자동 클릭 성공: xcode={target_xcode}"
                            )
                            self.message_queue.put(("status", "✅ 생중계 버튼 자동 클릭 성공"))
                            try:
                                capture_mod.WebDriverWait(driver, 5).until(
                                    lambda d: "player.asp" in d.current_url
                                )
                                return driver.current_url
                            except Exception:
                                logger.warning("버튼 클릭 후 페이지 전환 타임아웃")
                        else:
                            logger.warning(
                                f"메인 페이지에서 xcode={target_xcode} 생중계 버튼을 찾을 수 없음"
                            )
                    except Exception as e:
                        logger.warning(f"생중계 버튼 클릭 로직 실패: {e}")
                    finally:
                        if (
                            navigated_to_main
                            and not xcgcd
                            and "/main/player.asp" not in driver.current_url
                        ):
                            try:
                                if original_url not in driver.current_url:
                                    driver.get(original_url)
                                    self.stop_event.wait(timeout=2)
                                    logger.info(f"원래 URL로 복귀: {original_url}")
                            except Exception as e:
                                logger.debug(f"원래 URL 복귀 실패: {e}")

            if xcgcd and len(xcgcd) >= 10:
                new_url = self._set_query_param(original_url, "xcgcd", xcgcd)
                if not self._get_query_param(new_url, "xcode"):
                    inferred_xcode = target_xcode or extract_xcode_from_xcgcd(xcgcd)
                    if inferred_xcode:
                        new_url = self._set_query_param(new_url, "xcode", inferred_xcode)

                display_xcgcd = xcgcd[:15] + "..." if len(xcgcd) > 15 else xcgcd
                self.message_queue.put(
                    ("status", f"✅ 생중계 감지 성공! (xcgcd={display_xcgcd})")
                )
                logger.info(f"생중계 URL 업데이트: {new_url}")
                return new_url

            target_xcode = self._get_query_param(original_url, "xcode").strip() or None
            if isinstance(live_list_issue, dict):
                issue_reason = str(live_list_issue.get("reason", "") or "").strip()
                candidate_count = int(live_list_issue.get("candidate_count", 0) or 0)
                if issue_reason in {"ambiguous_live", "ambiguous_xcode"}:
                    self._notify_live_selection_issue(
                        issue_reason,
                        target_xcode=target_xcode,
                        candidate_count=candidate_count,
                    )
                    return original_url
            if target_xcode:
                self.message_queue.put(
                    (
                        "status",
                        f"⚠️ xcode={target_xcode} 위원회의 진행 중인 생중계를 찾을 수 없음",
                    )
                )
                logger.warning(
                    f"xcode={target_xcode}에 해당하는 생중계가 없음, 원래 URL 사용"
                )
            else:
                self.message_queue.put(
                    ("status", "⚠️ 생중계 정보를 찾을 수 없음 - 기본 URL 사용")
                )
                logger.warning("생중계 xcgcd를 찾을 수 없음, 원래 URL 사용")
            return original_url

        except Exception as e:
            logger.error(f"생중계 감지 오류: {e}")
            self.message_queue.put(("status", f"⚠️ 생중계 감지 실패: {e}"))
            return original_url
