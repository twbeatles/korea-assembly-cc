# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportAssignmentType=false

from __future__ import annotations

import json
import re
import time
from importlib import import_module
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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
        api_url = (
            "https://assembly.webcast.go.kr/main/service/live_list.asp"
            f"?vv={int(time.time())}"
        )
        try:
            req = Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=10) as response:
                payload = response.read().decode("utf-8", errors="replace")
            data = json.loads(payload)
            if isinstance(data, dict):
                return data.get("xlist", [])
        except (HTTPError, URLError, json.JSONDecodeError) as e:
            logger.debug(f"live_list API 오류: {e}")
        except Exception as e:
            logger.debug(f"live_list 처리 오류: {e}")
        return []

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
        broadcasts = self._fetch_live_list()
        if not broadcasts:
            return original_url

        current_xcgcd = self._get_query_param(original_url, "xcgcd").strip()
        target_norm = target_xcode.strip().upper() if target_xcode else ""

        def is_live_broadcast(item) -> bool:
            return (
                str(item.get("xstat", "")).strip() == "1"
                and bool(str(item.get("xcgcd", "")).strip())
            )

        if current_xcgcd and not target_norm:
            for bc in broadcasts:
                bc_xcgcd = str(bc.get("xcgcd", "")).strip()
                if bc_xcgcd and bc_xcgcd == current_xcgcd and is_live_broadcast(bc):
                    bc_xcode = str(bc.get("xcode", "")).strip()
                    if bc_xcode:
                        new_url = self._set_query_param(original_url, "xcode", bc_xcode)
                        logger.info(f"live_list로 xcode 보완: xcode={bc_xcode}")
                        return new_url

        if target_norm:
            for bc in broadcasts:
                bc_xcode = str(bc.get("xcode", "")).strip()
                if bc_xcode.upper() == target_norm and is_live_broadcast(bc):
                    xcgcd = str(bc.get("xcgcd", "")).strip()
                    new_url = self._set_query_param(original_url, "xcgcd", xcgcd)
                    if not self._get_query_param(new_url, "xcode"):
                        new_url = self._set_query_param(new_url, "xcode", bc_xcode)
                    logger.info(f"live_list 매칭 성공: xcode={bc_xcode}, xcgcd={xcgcd}")
                    return new_url
            logger.warning(f"live_list에서 xcode={target_norm} 생중계 미발견")
        else:
            for bc in broadcasts:
                if is_live_broadcast(bc):
                    xcgcd = str(bc.get("xcgcd", "")).strip()
                    new_url = self._set_query_param(original_url, "xcgcd", xcgcd)
                    if not self._get_query_param(new_url, "xcode"):
                        bc_xcode = str(bc.get("xcode", "")).strip()
                        if bc_xcode:
                            new_url = self._set_query_param(new_url, "xcode", bc_xcode)
                    logger.info(f"live_list 첫 생중계 사용: xcgcd={xcgcd}")
                    return new_url

        return original_url

    def _detect_live_broadcast(self, driver, original_url: str) -> str:
        """현재 진행 중인 생중계의 xcgcd를 자동 감지"""
        capture_mod = _capture_public()
        try:
            existing_xcgcd = self._get_query_param(original_url, "xcgcd").strip()
            existing_xcode = self._get_query_param(original_url, "xcode").strip()

            if existing_xcgcd and existing_xcode:
                logger.info(f"URL에 이미 xcode/xcgcd 포함됨: {original_url}")
                return original_url

            self.message_queue.put(("status", "🔍 현재 생중계 감지 중..."))
            target_xcode = existing_xcode or None
            target_xcode_norm = target_xcode.upper() if target_xcode else None
            logger.info(f"xcgcd 탐색 시작 - target_xcode: {target_xcode}")

            resolved_url = self._resolve_live_url_from_list(original_url, target_xcode)
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
                try:
                    if target_xcode:
                        script = f"""
                        var links = document.querySelectorAll('a[href*="xcode={target_xcode}"][href*="xcgcd="]');
                        for(var i=0; i<links.length; i++) {{
                            var href = links[i].getAttribute('href');
                            var match = href.match(/xcgcd=([^&]+)/);
                            if(match) return match[1];
                        }}
                        return null;
                        """
                        result = driver.execute_script(script)
                        if result:
                            xcgcd = str(result)
                            logger.info(
                                f"페이지 요소에서 xcode={target_xcode} 매칭 xcgcd 발견: {xcgcd}"
                            )
                    else:
                        live_scripts = [
                            """
                            var links = document.querySelectorAll('a[href*="xcgcd="]');
                            for(var i=0; i<links.length; i++) {
                                var href = links[i].getAttribute('href');
                                if(href && href.includes('xcgcd=')) {
                                    var match = href.match(/xcgcd=([^&]+)/);
                                    if(match) return match[1];
                                }
                            }
                            return null;
                            """,
                            """
                            var iframe = document.querySelector('iframe[src*="xcgcd="]');
                            if(iframe) {
                                var src = iframe.getAttribute('src');
                                var match = src.match(/xcgcd=([^&]+)/);
                                if(match) return match[1];
                            }
                            return null;
                            """,
                            """
                            var input = document.querySelector('input[name="xcgcd"], input#xcgcd');
                            if(input) return input.value;
                            return null;
                            """,
                        ]

                        for script in live_scripts:
                            result = driver.execute_script(script)
                            if result:
                                xcgcd = str(result)
                                logger.info(f"페이지 요소에서 xcgcd 발견: {xcgcd}")
                                break
                except Exception as e:
                    logger.debug(f"생중계 목록 파싱 오류: {e}")

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

                    all_broadcasts_script = """
                    var results = [];
                    var links = document.querySelectorAll('a[href*="xcgcd="]');
                    for(var i=0; i<links.length; i++) {
                        var href = links[i].getAttribute('href');
                        var text = links[i].innerText || links[i].textContent || '';
                        if(href && href.includes('xcgcd=')) {
                            var xcgcdMatch = href.match(/xcgcd=([^&]+)/);
                            var xcodeMatch = href.match(/xcode=([^&]+)/);
                            if(xcgcdMatch) {
                                results.push({
                                    xcgcd: xcgcdMatch[1],
                                    xcode: xcodeMatch ? xcodeMatch[1] : null,
                                    text: text.trim()
                                });
                            }
                        }
                    }
                    return JSON.stringify(results);
                    """
                    broadcasts_json = driver.execute_script(all_broadcasts_script)
                    broadcasts = json.loads(broadcasts_json) if broadcasts_json else []
                    logger.info(f"발견된 생중계 목록: {len(broadcasts)}개")

                    if broadcasts:
                        if target_xcode:
                            for bc in broadcasts:
                                bc_xcode = str(bc.get("xcode", "")).strip()
                                if (
                                    target_xcode_norm
                                    and bc_xcode.upper() == target_xcode_norm
                                ):
                                    xcgcd = bc["xcgcd"]
                                    logger.info(
                                        f"xcode={target_xcode} 매칭 성공: xcgcd={xcgcd}"
                                    )
                                    break
                            if not xcgcd:
                                logger.warning(
                                    f"xcode={target_xcode}에 해당하는 생중계를 찾지 못함"
                                )
                        else:
                            xcgcd = broadcasts[0]["xcgcd"]
                            first_bc = broadcasts[0]
                            logger.info(
                                f"첫 번째 생중계 사용: xcgcd={xcgcd}, text={first_bc.get('text', '')[:30]}"
                            )
                except Exception as e:
                    logger.debug(f"메인 페이지 조회 오류: {e}")

            if not xcgcd and target_xcode:
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
