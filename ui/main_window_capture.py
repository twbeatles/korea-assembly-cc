# -*- coding: utf-8 -*-

from ui.main_window_common import *


class MainWindowCaptureMixin:

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
            api_url = f"https://assembly.webcast.go.kr/main/service/live_list.asp?vv={int(time.time())}"
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
            dialog = LiveBroadcastDialog(self)
            dialog.finished.connect(dialog.deleteLater)
            if dialog.exec():
                data = dialog.selected_broadcast
                if data:
                    # 선택된 방송 정보로 URL 생성
                    # player.asp?xcode={xcode}&xcgcd={xcgcd} 형식이 가장 안정적임
                    xcode = str(data.get("xcode", "")).strip()
                    xcgcd = str(data.get("xcgcd", "")).strip()

                    if xcode and xcgcd:
                        # 기본 URL
                        base_url = "https://assembly.webcast.go.kr/main/player.asp"
                        new_url = f"{base_url}?xcode={xcode}&xcgcd={xcgcd}"

                        # 콤보박스에 설정
                        name = data.get("xname", "").strip()
                        self._add_to_history(new_url, name)
                        idx = self.url_combo.findData(new_url)
                        if idx >= 0:
                            self.url_combo.setCurrentIndex(idx)
                        else:
                            self.url_combo.setEditText(new_url)

                        # 태그 자동 설정 (방송명) - _add_to_history에서 처리됨
                        # 바로 시작할지 물어보는 것도 좋지만, 일단 URL만 채워줌
                        # Toast 알림
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

            # xcgcd가 있으면 유효한 것으로 간주 (xstat 상태와 무관하게 시도)
            def is_valid_broadcast(item):
                return bool(str(item.get("xcgcd", "")).strip())

            if current_xcgcd and not target_norm:
                for bc in broadcasts:
                    bc_xcgcd = str(bc.get("xcgcd", "")).strip()
                    if bc_xcgcd and bc_xcgcd == current_xcgcd:
                        bc_xcode = str(bc.get("xcode", "")).strip()
                        if bc_xcode:
                            new_url = self._set_query_param(original_url, "xcode", bc_xcode)
                            logger.info(f"live_list로 xcode 보완: xcode={bc_xcode}")
                            return new_url

            if target_norm:
                for bc in broadcasts:
                    bc_xcode = str(bc.get("xcode", "")).strip()
                    # xcode가 일치하고 xcgcd가 있으면 사용 (xstat 조건 완화)
                    if bc_xcode.upper() == target_norm and is_valid_broadcast(bc):
                        xcgcd = str(bc.get("xcgcd", "")).strip()
                        new_url = self._set_query_param(original_url, "xcgcd", xcgcd)
                        if not self._get_query_param(new_url, "xcode"):
                            new_url = self._set_query_param(new_url, "xcode", bc_xcode)
                        logger.info(f"live_list 매칭 성공: xcode={bc_xcode}, xcgcd={xcgcd}")
                        return new_url
                logger.warning(f"live_list에서 xcode={target_norm} 생중계 미발견")
            else:
                for bc in broadcasts:
                    if is_valid_broadcast(bc):
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
            """현재 진행 중인 생중계의 xcgcd를 자동 감지

            Args:
                driver: Selenium WebDriver
                original_url: 원래 요청된 URL

            Returns:
                str: 감지된 xcgcd를 포함한 URL, 감지 실패 시 원래 URL 반환
            """
            try:
                existing_xcgcd = self._get_query_param(original_url, "xcgcd").strip()
                existing_xcode = self._get_query_param(original_url, "xcode").strip()

                # 원래 URL에 xcode/xcgcd가 모두 있으면 그대로 사용
                if existing_xcgcd and existing_xcode:
                    logger.info(f"URL에 이미 xcode/xcgcd 포함됨: {original_url}")
                    return original_url

                self.message_queue.put(("status", "🔍 현재 생중계 감지 중..."))

                # xcode 추출 (모든 방법에서 공통으로 사용)
                target_xcode = existing_xcode or None
                target_xcode_norm = target_xcode.upper() if target_xcode else None
                logger.info(f"xcgcd 탐색 시작 - target_xcode: {target_xcode}")

                # 방법 0: live_list API로 생중계 정보 확인 (사이트 구조 기반)
                resolved_url = self._resolve_live_url_from_list(original_url, target_xcode)
                if resolved_url != original_url and self._get_query_param(
                    resolved_url, "xcgcd"
                ):
                    logger.info(f"live_list 기반 URL 감지 성공: {resolved_url}")
                    return resolved_url

                # xcgcd에서 xcode 추출하는 헬퍼 함수
                # xcgcd 형식: DCM0000XX... 여기서 XX가 xcode 부분 (예: IO, 25 등)
                def extract_xcode_from_xcgcd(xcgcd_val):
                    """xcgcd 값에서 xcode 부분 추출 시도"""
                    if not xcgcd_val:
                        return None
                    # DCM0000 접두사 이후 부분 추출 시도
                    # 예: DCM0000IO224310401 -> IO
                    # 예: DCM000025224310401 -> 25
                    match = re.search(r"DCM0000([A-Za-z0-9]+)", xcgcd_val)
                    if match:
                        code = match.group(1)
                        # 숫자+나머지 패턴 (예: 25224310401 -> 25)
                        num_match = re.match(r"^(\d{2})", code)
                        if num_match:
                            return num_match.group(1)
                        # 문자+나머지 패턴 (예: IO224310401 -> IO)
                        alpha_match = re.match(r"^([A-Za-z]+)", code)
                        if alpha_match:
                            return alpha_match.group(1)
                    return None

                # 방법 1: 현재 페이지의 JavaScript 변수에서 xcgcd 가져오기
                scripts = [
                    # 전역 변수에서 xcgcd 찾기
                    "return typeof xcgcd !== 'undefined' ? xcgcd : null;",
                    "return typeof XCGCD !== 'undefined' ? XCGCD : null;",
                    "return window.xcgcd || null;",
                    "return window.XCGCD || null;",
                    # URL 파라미터에서 추출
                    "return new URLSearchParams(window.location.search).get('xcgcd');",
                    # 현재 스트림 정보에서 추출
                    "if(typeof streamInfo !== 'undefined' && streamInfo.xcgcd) return streamInfo.xcgcd; return null;",
                    # 플레이어 정보에서 추출
                    "if(typeof playerConfig !== 'undefined' && playerConfig.xcgcd) return playerConfig.xcgcd; return null;",
                ]

                xcgcd = None
                for script in scripts:
                    try:
                        result = driver.execute_script(script)
                        if result:
                            found_xcgcd = str(result)
                            # target_xcode가 있으면 xcgcd의 xcode 부분 검증
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

                # 방법 2: URL이 리다이렉트 되었는지 확인
                if not xcgcd:
                    current_url = driver.current_url
                    found_xcgcd = self._get_query_param(current_url, "xcgcd").strip()
                    if found_xcgcd:
                        # target_xcode 검증
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

                # 방법 3: 페이지 내 생중계 목록에서 현재 방송 찾기
                # 주의: 이 페이지에 여러 방송 링크가 있을 수 있으므로 xcode 검증 필요
                # (target_xcode는 이미 위에서 추출됨)
                if not xcgcd:
                    try:
                        if target_xcode:
                            # target_xcode가 있으면 해당 xcode가 포함된 링크만 검색
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
                            # target_xcode가 없으면(본회의 등) 기존 로직 사용
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

                # 방법 4: 메인 페이지에서 오늘의 생중계 정보 가져오기 (개선됨)
                # (target_xcode는 이미 위에서 추출됨)
                navigated_to_main = False
                if not xcgcd:
                    try:
                        # 메인 페이지로 이동
                        main_url = "https://assembly.webcast.go.kr/main/"
                        self.message_queue.put(
                            ("status", "🔍 메인 페이지에서 생중계 목록 확인 중...")
                        )
                        driver.get(main_url)
                        navigated_to_main = True

                        # 동적 콘텐츠 로딩 대기 (최대 10초)
                        try:
                            wait = WebDriverWait(driver, 10)
                            wait.until(
                                EC.presence_of_element_located(
                                    (By.CSS_SELECTOR, 'a[href*="xcgcd="]')
                                )
                            )
                        except Exception:
                            # 타임아웃 시 기본 대기 (종료 신호에 즉시 반응)
                            self.stop_event.wait(timeout=3)

                        # 모든 생중계 링크 수집
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
                            # target_xcode가 있으면 해당 xcode 매칭 우선
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
                                # target_xcode가 있는데 매칭 실패하면 xcgcd를 설정하지 않음
                                if not xcgcd:
                                    logger.warning(
                                        f"xcode={target_xcode}에 해당하는 생중계를 찾지 못함"
                                    )
                            else:
                                # target_xcode가 없는 경우(본회의 등)에만 첫 번째 생중계 사용
                                xcgcd = broadcasts[0]["xcgcd"]
                                first_bc = broadcasts[0]
                                logger.info(
                                    f"첫 번째 생중계 사용: xcgcd={xcgcd}, text={first_bc.get('text', '')[:30]}"
                                )

                    except Exception as e:
                        logger.debug(f"메인 페이지 조회 오류: {e}")

                # 방법 5: 메인 페이지 리다이렉트 시 화면의 '생중계' 버튼 자동 클릭 (개선됨)
                if not xcgcd and target_xcode:
                    # 현재 URL이 메인 페이지인지 확인 (player.asp가 아님)
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

                            # 동적 콘텐츠 로딩 대기 (최대 10초) - onair 클래스가 나타날 때까지
                            try:
                                WebDriverWait(driver, 10).until(
                                    EC.presence_of_element_located(
                                        (By.CSS_SELECTOR, ".onair")
                                    )
                                )
                            except Exception:
                                logger.debug(
                                    "onair 요소 대기 타임아웃 (생중계가 없거나 로딩 지연)"
                                )

                            # 1. onair 버튼 찾기 (xcode 매칭)
                            # 다양한 선택자 시도 - 더 포괄적으로
                            selectors = [
                                f'a.onair[href*="xcode={target_xcode}"]',
                                f'a.btn[href*="xcode={target_xcode}"]',  # onair 클래스가 없을 수도 있음
                                f'div.onair a[href*="xcode={target_xcode}"]',
                                f'a[href*="xcode={target_xcode}"]:has(.icon_onair)',
                                f'a[href*="xcode={target_xcode}"]',  # 최후의 수단: 그냥 링크 찾기
                            ]

                            btn = None
                            for sel in selectors:
                                try:
                                    elems = driver.find_elements(By.CSS_SELECTOR, sel)
                                    # onair 클래스가 있는 요소 우선 선택
                                    for elem in elems:
                                        if "onair" in elem.get_attribute(
                                            "class"
                                        ) or elem.find_elements(By.CSS_SELECTOR, ".onair"):
                                            btn = elem
                                            break

                                    if btn:
                                        break

                                    # onair가 없더라도 첫 번째 요소 선택 (클릭해보는 것이 나음)
                                    if elems and not btn:
                                        btn = elems[0]
                                        break
                                except Exception:
                                    continue

                            if btn:
                                # 2. 스크롤하여 요소 보이게 하기
                                driver.execute_script(
                                    "arguments[0].scrollIntoView({block: 'center'});", btn
                                )
                                # 스크롤 후 안정화 대기 (종료 신호에 즉시 반응)
                                self.stop_event.wait(timeout=1.0)

                                # 3. 클릭 (JavaScript 사용이 더 안정적)
                                driver.execute_script("arguments[0].click();", btn)
                                logger.info(
                                    f"메인 페이지에서 생중계 버튼 자동 클릭 성공: xcode={target_xcode}"
                                )
                                self.message_queue.put(
                                    ("status", "✅ 생중계 버튼 자동 클릭 성공")
                                )

                                # 4. 페이지 전환 대기
                                try:
                                    WebDriverWait(driver, 5).until(
                                        lambda d: "player.asp" in d.current_url
                                    )
                                    # 페이지 전환 후 URL 반환
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
                            # 버튼 클릭도 실패한 경우 원래 URL로 복귀
                            # 단, 버튼 클릭으로 페이지가 이동했다면 복귀하지 않음
                            if (
                                navigated_to_main
                                and not xcgcd
                                and "/main/player.asp" not in driver.current_url
                            ):
                                try:
                                    # 이미 버튼 클릭 시도로 URL이 바뀌었을 수 있으므로 체크
                                    if original_url not in driver.current_url:
                                        driver.get(original_url)
                                        self.stop_event.wait(timeout=2)
                                        logger.info(f"원래 URL로 복귀: {original_url}")
                                except Exception as e:
                                    logger.debug(f"원래 URL 복귀 실패: {e}")

                # xcgcd를 찾았으면 URL 업데이트 (유효성 검증 포함)
                if (
                    xcgcd and len(xcgcd) >= 10
                ):  # 최소 길이 검증 (유효한 xcgcd는 보통 20자 이상)
                    new_url = self._set_query_param(original_url, "xcgcd", xcgcd)
                    if not self._get_query_param(new_url, "xcode"):
                        inferred_xcode = target_xcode or extract_xcode_from_xcgcd(xcgcd)
                        if inferred_xcode:
                            new_url = self._set_query_param(
                                new_url, "xcode", inferred_xcode
                            )

                    display_xcgcd = xcgcd[:15] + "..." if len(xcgcd) > 15 else xcgcd
                    self.message_queue.put(
                        ("status", f"✅ 생중계 감지 성공! (xcgcd={display_xcgcd})")
                    )
                    logger.info(f"생중계 URL 업데이트: {new_url}")
                    return new_url
                else:
                    # target_xcode 정보를 포함하여 더 구체적인 메시지 표시
                    target_xcode = (
                        self._get_query_param(original_url, "xcode").strip() or None
                    )

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


    def _get_reconnect_delay(self, attempt: int) -> float:
            """지수 백오프 기반 재연결 대기 시간(초) 계산"""
            if attempt <= 0:
                return 0.0
            delay = Config.RECONNECT_BASE_DELAY * (2 ** (attempt - 1))
            return min(delay, Config.RECONNECT_MAX_DELAY)


    def _is_recoverable_webdriver_error(self, error: Exception) -> bool:
            """재연결로 복구 가능한 웹드라이버 오류인지 판단"""
            msg = str(error).lower()
            markers = [
                "invalid session",
                "no such execution context",
                "chrome not reachable",
                "disconnected",
                "target closed",
                "session deleted",
                "connection reset",
                "connection refused",
                "web view not found",
            ]
            return any(marker in msg for marker in markers)


    def _ping_driver(self, driver):
            """웹드라이버 응답 시간을 측정 (ms). 실패 시 None 반환."""
            start = time.time()
            try:
                driver.execute_script("return 1")
            except Exception:
                return None
            return int((time.time() - start) * 1000)


    def _extraction_worker(self, url, selector, headless):
            """자막 추출 워커 스레드 (Legacy Logic Restoration)"""
            driver = None

            try:
                options = Options()
                options.add_argument("--log-level=3")
                options.add_argument("--disable-blink-features=AutomationControlled")
                options.add_experimental_option(
                    "excludeSwitches", ["enable-logging", "enable-automation"]
                )
                options.add_experimental_option("useAutomationExtension", False)

                # 헤드리스 모드
                if headless:
                    options.add_argument("--headless=new")
                    options.add_argument("--window-size=1280,720")
                    self.message_queue.put(("status", "헤드리스 모드로 시작 중..."))

                try:
                    driver = webdriver.Chrome(options=options)
                    self.driver = driver
                    self.message_queue.put(("status", "Chrome 시작 완료"))
                except Exception as e:
                    self.message_queue.put(("error", f"Chrome 오류: {e}"))
                    return

                self.message_queue.put(("status", "페이지 로딩 중..."))
                driver.get(url)

                if not self._get_query_param(url, "xcgcd").strip():
                    try:
                        resolved_url = self._detect_live_broadcast(driver, url)
                        if isinstance(resolved_url, str):
                            resolved_url = resolved_url.strip()
                        if resolved_url and resolved_url != url:
                            url = resolved_url
                            self.message_queue.put(("resolved_url", url))
                            self.message_queue.put(
                                ("status", "감지된 생중계 URL로 재접속 중...")
                            )
                            driver.get(url)
                    except Exception as live_err:
                        logger.warning("생중계 자동 감지 실패: %s", live_err)

                self.stop_event.wait(timeout=3)
                resolved_url = self._detect_live_broadcast(driver, url)
                if resolved_url and resolved_url != url:
                    url = resolved_url
                    self.message_queue.put(("status", "감지된 생중계 주소로 재진입 중..."))
                    driver.get(url)
                    self.stop_event.wait(timeout=2)

                self.message_queue.put(("status", "AI 자막 활성화 중..."))
                self._activate_subtitle(driver)

                self.message_queue.put(("status", "자막 요소 검색 중..."))
                wait = WebDriverWait(driver, 20)

                found = False
                selector_candidates = self._build_subtitle_selector_candidates(selector)
                active_selector = ""
                for sel in selector_candidates:
                    try:
                        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                        self.message_queue.put(("status", f"자막 요소 찾음: {sel}"))
                        active_selector = sel
                        found = True
                        break
                    except Exception:
                        continue

                if not found:
                    detected_selector = self._find_subtitle_selector(driver)
                    if detected_selector:
                        selector_candidates = self._build_subtitle_selector_candidates(
                            detected_selector, selector_candidates
                        )
                        active_selector = selector_candidates[0]
                        self.message_queue.put(
                            ("status", f"자막 요소 자동 감지: {active_selector}")
                        )
                        found = True

                if not found:
                    self.message_queue.put(("error", "자막 요소를 찾을 수 없습니다."))
                    return

                self.message_queue.put(("status", "자막 모니터링 중"))

                # MutationObserver 주입 (하이브리드 아키텍처)
                observer_active, observer_frame_path = self._inject_mutation_observer(
                    driver, ",".join(selector_candidates)
                )
                observer_retry_interval = 3.0
                last_observer_retry = time.time()
                last_selector_refresh = time.time()

                last_check = time.time()
                last_connection_check = time.time()
                # [Fix] 지역 변수로 변경 - 스레드 안전성 확보 (Race condition 방지)
                worker_last_raw_text = ""
                worker_last_raw_compact = ""
                reconnect_attempt = 0
                last_keepalive_emit = 0.0

                # stop_event 사용으로 더 빠른 종료 응답
                while not self.stop_event.is_set():
                    try:
                        now = time.time()

                        # 연결 상태 모니터링 (#5) - 5초마다 체크
                        if now - last_connection_check >= 5.0:
                            ping_time = self._ping_driver(driver)
                            if ping_time is not None:
                                self.message_queue.put(
                                    (
                                        "connection_status",
                                        {"status": "connected", "latency": ping_time},
                                    )
                                )
                                reconnect_attempt = 0  # 연결 성공 시 재연결 횟수 초기화
                            else:
                                self.message_queue.put(
                                    ("connection_status", {"status": "disconnected"})
                                )
                            last_connection_check = now

                        if now - last_check >= 0.2:
                            changes_processed = False
                            used_structured_probe = False
                            if observer_active:
                                observer_changes = self._collect_observer_changes(
                                    driver, observer_frame_path
                                )
                                if observer_changes is None:
                                    observer_active = False
                                    logger.warning(
                                        "MutationObserver 비활성화, polling fallback"
                                    )
                                elif observer_changes:
                                    used_structured_probe = False
                                    should_reset = any(
                                        change == "__SUBTITLE_CLEARED__"
                                        or (
                                            isinstance(change, dict)
                                            and str(change.get("kind") or "").strip()
                                            == "reset"
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
                                        changes_processed = True

                            if not used_structured_probe:
                                preferred_frame_path = (
                                    observer_frame_path if observer_active else ()
                                ) or getattr(self, "_last_subtitle_frame_path", ())
                                probe = self._read_subtitle_probe_by_selectors(
                                    driver,
                                    selector_candidates,
                                    preferred_frame_path=preferred_frame_path,
                                )
                                text = utils.clean_text_display(
                                    str(probe.get("text", "") or "")
                                ).strip()
                                matched_selector = str(
                                    probe.get("matched_selector", "") or ""
                                )
                                selector_found = bool(probe.get("found", False))
                                text_compact = utils.compact_subtitle_text(text)

                                if selector_found:
                                    reconnect_attempt = 0
                                    if matched_selector and matched_selector != active_selector:
                                        active_selector = matched_selector
                                        selector_candidates = (
                                            self._build_subtitle_selector_candidates(
                                                active_selector, selector_candidates
                                            )
                                        )
                                elif now - last_selector_refresh >= 5.0:
                                    detected_selector = self._find_subtitle_selector(driver)
                                    if detected_selector:
                                        selector_candidates = (
                                            self._build_subtitle_selector_candidates(
                                                detected_selector, selector_candidates
                                            )
                                        )
                                        active_selector = selector_candidates[0]
                                        logger.info(
                                            "자막 선택자 자동 전환: %s",
                                            active_selector,
                                        )
                                    last_selector_refresh = now

                                if (
                                    not observer_active
                                    and now - last_observer_retry >= observer_retry_interval
                                ):
                                    observer_active, observer_frame_path = self._inject_mutation_observer(
                                        driver, ",".join(selector_candidates)
                                    )
                                    last_observer_retry = now

                                if (
                                    text
                                    and text_compact
                                    and text_compact != worker_last_raw_compact
                                ):
                                    worker_last_raw_text = text
                                    worker_last_raw_compact = text_compact
                                    last_keepalive_emit = now
                                    self.message_queue.put(
                                        (
                                            "preview",
                                            self._build_preview_payload_from_probe(probe),
                                        )
                                    )
                                    changes_processed = True
                                elif (
                                    text
                                    and text_compact
                                    and text_compact == worker_last_raw_compact
                                    and (
                                        now - last_keepalive_emit
                                        >= Config.SUBTITLE_KEEPALIVE_INTERVAL
                                    )
                                ):
                                    self.message_queue.put(("keepalive", text))
                                    last_keepalive_emit = now
                                    changes_processed = True
                                elif (
                                    not text
                                    and selector_found
                                    and worker_last_raw_compact
                                ):
                                    self.message_queue.put(
                                        ("subtitle_reset", "polling_cleared")
                                    )
                                    worker_last_raw_text = ""
                                    worker_last_raw_compact = ""
                                    last_keepalive_emit = 0.0
                                    changes_processed = True

                            last_check = now
                            self.stop_event.wait(timeout=0.05)
                            continue

                            # 1단계: MutationObserver 버퍼에서 수집 (이벤트 기반)
                            if observer_active:
                                observer_changes = self._collect_observer_changes(
                                    driver, observer_frame_path
                                )
                                if observer_changes is None:
                                    # Observer가 죽었으면 비활성화 후 폴링 fallback
                                    observer_active = False
                                    logger.warning("MutationObserver 비활성화, 폴링 fallback")
                                elif observer_changes:
                                    for change_text in observer_changes:
                                        # 클리어 마커 감지 (발언자 전환)
                                        if change_text == "__SUBTITLE_CLEARED__":
                                            self.message_queue.put(
                                                ("subtitle_reset", "observer_cleared")
                                            )
                                            worker_last_raw_text = ""
                                            worker_last_raw_compact = ""
                                            last_keepalive_emit = 0.0
                                            continue
                                        c_text = utils.clean_text_display(change_text)
                                        c_compact = utils.compact_subtitle_text(c_text)
                                        if (
                                            c_text
                                            and c_compact
                                            and c_compact != worker_last_raw_compact
                                        ):
                                            worker_last_raw_text = c_text
                                            worker_last_raw_compact = c_compact
                                            last_keepalive_emit = now
                                            self.message_queue.put(("preview", c_text))
                                            changes_processed = True

                            # 2단계: Observer 결과가 없으면 기존 폴링 fallback
                            if not changes_processed:
                                text, matched_selector, selector_found = (
                                    self._read_subtitle_text_by_selectors(
                                        driver, selector_candidates
                                    )
                                )
                                if selector_found:
                                    reconnect_attempt = 0
                                    if matched_selector and matched_selector != active_selector:
                                        active_selector = matched_selector
                                        selector_candidates = (
                                            self._build_subtitle_selector_candidates(
                                                active_selector, selector_candidates
                                            )
                                        )
                                elif now - last_selector_refresh >= 5.0:
                                    # 셀렉터 변화 대응: 주기적 자동 재탐색
                                    detected_selector = self._find_subtitle_selector(driver)
                                    if detected_selector:
                                        selector_candidates = (
                                            self._build_subtitle_selector_candidates(
                                                detected_selector, selector_candidates
                                            )
                                        )
                                        active_selector = selector_candidates[0]
                                        logger.info(
                                            "자막 셀렉터 자동 전환: %s", active_selector
                                        )
                                    last_selector_refresh = now

                                if (
                                    not observer_active
                                    and now - last_observer_retry >= observer_retry_interval
                                ):
                                    observer_active, observer_frame_path = self._inject_mutation_observer(
                                        driver, ",".join(selector_candidates)
                                    )
                                    last_observer_retry = now

                                text = utils.clean_text_display(text)
                                text_compact = utils.compact_subtitle_text(text)

                                if (
                                    text
                                    and text_compact
                                    and text_compact != worker_last_raw_compact
                                ):
                                    worker_last_raw_text = text
                                    worker_last_raw_compact = text_compact
                                    last_keepalive_emit = now
                                    self.message_queue.put(("preview", text))
                                elif (
                                    text
                                    and text_compact
                                    and text_compact == worker_last_raw_compact
                                    and (
                                        now - last_keepalive_emit
                                        >= Config.SUBTITLE_KEEPALIVE_INTERVAL
                                    )
                                ):
                                    self.message_queue.put(("keepalive", text))
                                    last_keepalive_emit = now
                                elif (
                                    not text
                                    and selector_found
                                    and worker_last_raw_compact
                                ):
                                    # 폴링에서도 빈 텍스트 감지 (발언자 전환)
                                    self.message_queue.put(
                                        ("subtitle_reset", "polling_cleared")
                                    )
                                    worker_last_raw_text = ""
                                    worker_last_raw_compact = ""
                                    last_keepalive_emit = 0.0

                            last_check = now

                        # stop_event 대기 (0.05초, 즉시 응답 가능)
                        self.stop_event.wait(timeout=0.05)

                    except Exception as e:
                        if self.stop_event.is_set():
                            break

                        # 자동 재연결 로직 (#4)
                        if (
                            self.auto_reconnect_enabled
                            and self._is_recoverable_webdriver_error(e)
                        ):
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
                                    f"WebDriver 연결 오류, {delay}초 후 재연결 시도 ({reconnect_attempt}/{Config.MAX_RECONNECT_ATTEMPTS})"
                                )

                                # 기존 드라이버 정리
                                if driver:
                                    try:
                                        driver.quit()
                                    except Exception as quit_err:
                                        logger.debug(
                                            f"드라이버 종료 실패, detached 목록에 추가: {quit_err}"
                                        )
                                        with self._detached_drivers_lock:
                                            self._detached_drivers.append(driver)

                                # 대기 후 재연결 (종료 신호에 즉시 반응)
                                if self.stop_event.wait(timeout=delay):
                                    break

                                try:
                                    driver = webdriver.Chrome(options=options)
                                    self.driver = driver
                                    driver.get(url)
                                    if not self._get_query_param(url, "xcgcd").strip():
                                        try:
                                            resolved_url = self._detect_live_broadcast(
                                                driver, url
                                            )
                                            if isinstance(resolved_url, str):
                                                resolved_url = resolved_url.strip()
                                            if resolved_url and resolved_url != url:
                                                url = resolved_url
                                                self.message_queue.put(
                                                    ("resolved_url", url)
                                                )
                                                self.message_queue.put(
                                                    (
                                                        "status",
                                                        "감지된 생중계 URL로 재접속 중...",
                                                    )
                                                )
                                                driver.get(url)
                                        except Exception as live_err:
                                            logger.warning(
                                                "재연결 후 생중계 자동 감지 실패: %s",
                                                live_err,
                                            )
                                    if self.stop_event.wait(timeout=2):
                                        break
                                    resolved_url = self._detect_live_broadcast(driver, url)
                                    if resolved_url and resolved_url != url:
                                        url = resolved_url
                                        driver.get(url)
                                        if self.stop_event.wait(timeout=2):
                                            break
                                    self._activate_subtitle(driver)
                                    self.message_queue.put(
                                        (
                                            "status",
                                            f"✅ 재연결 성공 (시도 {reconnect_attempt})",
                                        )
                                    )
                                    self.message_queue.put(
                                        ("connection_status", {"status": "connected"})
                                    )
                                    last_check = time.time()
                                    last_connection_check = time.time()
                                    worker_last_raw_text = ""
                                    worker_last_raw_compact = ""
                                    last_keepalive_emit = 0.0
                                    detected_selector = self._find_subtitle_selector(driver)
                                    if detected_selector:
                                        selector_candidates = (
                                            self._build_subtitle_selector_candidates(
                                                detected_selector, selector_candidates
                                            )
                                        )
                                        active_selector = selector_candidates[0]
                                    # 재연결 후 MutationObserver 재주입
                                    observer_active, observer_frame_path = self._inject_mutation_observer(
                                        driver, ",".join(selector_candidates)
                                    )
                                    last_observer_retry = time.time()
                                    continue
                                except Exception as reconnect_error:
                                    logger.error(f"재연결 실패: {reconnect_error}")
                            else:
                                self.message_queue.put(
                                    (
                                        "error",
                                        f"최대 재연결 시도 횟수({Config.MAX_RECONNECT_ATTEMPTS}) 초과",
                                    )
                                )
                                break
                        else:
                            # 복구 불가능한 오류
                            logger.warning(f"모니터링 중 오류: {e}")
                            self.stop_event.wait(timeout=0.5)

            except Exception as e:
                if not self.stop_event.is_set():
                    self.message_queue.put(("error", str(e)))

            finally:
                if driver:
                    try:
                        driver.quit()
                    except Exception as e:
                        logger.debug(f"WebDriver 종료 오류: {e}")
                    self.driver = None
                self.message_queue.put(("finished", ""))


    def _build_subtitle_selector_candidates(
            self, primary_selector: str, extras: list[str] | None = None
        ) -> list[str]:
            """우선순위가 반영된 자막 CSS 셀렉터 후보 목록을 생성한다."""
            candidates = []

            def _add(sel: str) -> None:
                if not isinstance(sel, str):
                    return
                norm = sel.strip()
                if not norm or norm in candidates:
                    return
                candidates.append(norm)

            _add(primary_selector or "")
            for sel in [
                "#viewSubtit .smi_word:last-child",
                "#viewSubtit .smi_word",
                "#viewSubtit .incont",
                "#viewSubtit span",
                "#viewSubtit",
                ".subtitle_area",
                ".ai_subtitle",
                "[class*='subtitle']",
            ]:
                _add(sel)

            if extras:
                for sel in extras:
                    _add(sel)

            # 컨테이너형 셀렉터보다 실제 자막 라인(.smi_word)을 우선한다.
            broad_selectors = {
                "#viewSubtit .incont",
                "#viewSubtit",
                ".subtitle_area",
                ".ai_subtitle",
                "[class*='subtitle']",
            }
            priority = {
                "#viewSubtit .smi_word:last-child": 0,
                "#viewSubtit .smi_word": 1,
                "#viewSubtit span": 2,
                "#viewSubtit .incont": 7,
                "#viewSubtit": 8,
                ".subtitle_area": 9,
                ".ai_subtitle": 10,
                "[class*='subtitle']": 11,
            }
            primary_norm = (primary_selector or "").strip()

            order_map = {sel: idx for idx, sel in enumerate(candidates)}

            def _weight(sel: str) -> tuple[int, int]:
                original_idx = order_map.get(sel, 999)
                if sel in priority:
                    return priority[sel], original_idx
                if sel == primary_norm and sel not in broad_selectors:
                    return 3, original_idx
                if sel in broad_selectors:
                    return 12, original_idx
                return 4, original_idx

            return sorted(candidates, key=_weight)


    def _read_subtitle_probe_by_selectors(
            self,
            driver,
            selectors: list[str],
            preferred_frame_path: tuple[int, ...] = (),
            filter_unconfirmed_enabled: bool = True,
        ) -> dict[str, Any]:
            """Return structured subtitle probe data aligned with the Chrome extension."""

            def _normalize_rows(rows: object) -> list[ObservedSubtitleRow]:
                observed: list[ObservedSubtitleRow] = []
                if not isinstance(rows, list):
                    return observed
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    text = utils.clean_text_display(str(row.get("text", ""))).strip()
                    if not utils.compact_subtitle_text(text):
                        continue
                    node_key = str(row.get("nodeKey", "") or "").strip()
                    if not node_key:
                        continue
                    speaker_channel = str(row.get("speakerChannel") or "unknown")
                    if speaker_channel not in ("primary", "secondary", "unknown"):
                        speaker_channel = "unknown"
                    observed.append(
                        ObservedSubtitleRow(
                            node_key=node_key,
                            text=text,
                            speaker_color=str(row.get("speakerColor", "") or ""),
                            speaker_channel=speaker_channel,
                            unstable_key=bool(row.get("unstableKey", False)),
                        )
                    )
                return observed

            def _probe_in_current_context() -> dict[str, Any]:
                try:
                    result = driver.execute_script(
                        """
                        return (function(selectorsArg, filterUnconfirmedArg) {
                            function normalizeText(value) {
                                return String(value || '').replace(/\\s+/g, ' ').trim();
                            }
                            function compactText(value) {
                                return normalizeText(value).replace(/\\s+/g, '');
                            }
                            function queryAllSafe(selector) {
                                try { return Array.from(document.querySelectorAll(selector)); }
                                catch (e) { return []; }
                            }
                            function queryOneSafe(selector) {
                                try { return document.querySelector(selector); }
                                catch (e) { return null; }
                            }
                            function normalizeSpeakerColor(color) {
                                var probe = document.createElement('span');
                                probe.style.color = String(color || '').trim();
                                (document.body || document.documentElement).appendChild(probe);
                                var normalized = window.getComputedStyle(probe).color;
                                probe.remove();
                                return normalized;
                            }
                            function classifySpeakerChannel(color) {
                                var normalized = normalizeSpeakerColor(color);
                                if (normalized === 'rgb(35, 124, 147)') return 'primary';
                                if (normalized === 'rgb(30, 30, 30)') return 'secondary';
                                return 'unknown';
                            }
                            function hasOpaqueBackground(backgroundColor) {
                                var normalized = String(backgroundColor || '').replace(/\\s+/g, '').toLowerCase();
                                return Boolean(normalized) && normalized !== 'transparent' && normalized !== 'rgba(0,0,0,0)';
                            }
                            function isConfirmedSubtitleNode(node) {
                                var bg = window.getComputedStyle(node).backgroundColor;
                                if (hasOpaqueBackground(bg)) return false;
                                var descendants = Array.from(node.querySelectorAll('*'));
                                var limit = Math.min(descendants.length, 48);
                                for (var i = 0; i < limit; i++) {
                                    var childBg = window.getComputedStyle(descendants[i]).backgroundColor;
                                    if (hasOpaqueBackground(childBg)) return false;
                                }
                                return true;
                            }
                            function normalizeRowQuery(selector) {
                                return String(selector || '')
                                    .replace(/:last-child/g, '')
                                    .replace(/:last-of-type/g, '')
                                    .trim();
                            }
                            function getSmiWordNodes(selector) {
                                var query = normalizeRowQuery(selector) || '#viewSubtit .smi_word';
                                var nodes = queryAllSafe(query);
                                return nodes.length ? nodes : queryAllSafe('#viewSubtit .smi_word');
                            }
                            function extractClassNodeKey(node) {
                                var classes = String(node.className || '')
                                    .split(/\\s+/)
                                    .map(function(token) { return token.trim(); })
                                    .filter(function(token) { return token && token !== 'smi_word'; });
                                return classes[0] || '';
                            }
                            function extractAttributeNodeKey(node) {
                                var candidates = [node.getAttribute('data-id'), node.getAttribute('data-key'), node.id];
                                for (var i = 0; i < candidates.length; i++) {
                                    var candidate = String(candidates[i] || '').trim();
                                    if (candidate) return candidate;
                                }
                                return '';
                            }
                            function ensureGeneratedNodeKey(node) {
                                if (!node.dataset.assemblyRowKey) {
                                    node.dataset.assemblyRowKey = 'row_' + Math.random().toString(36).slice(2, 9) + '_' + Date.now();
                                }
                                return node.dataset.assemblyRowKey;
                            }
                            function readObservedRows(selector) {
                                var rows = [];
                                var nodes = getSmiWordNodes(selector);
                                var classKeyCounts = new Map();
                                nodes.forEach(function(node) {
                                    var classKey = extractClassNodeKey(node);
                                    if (!classKey) return;
                                    classKeyCounts.set(classKey, (classKeyCounts.get(classKey) || 0) + 1);
                                });
                                nodes.forEach(function(node) {
                                    if (filterUnconfirmedArg && !isConfirmedSubtitleNode(node)) {
                                        return;
                                    }
                                    var text = normalizeText(node.innerText || node.textContent || '');
                                    if (!compactText(text)) return;
                                    var classNodeKey = extractClassNodeKey(node);
                                    var attrNodeKey = extractAttributeNodeKey(node);
                                    var uniqueClassKey = Boolean(classNodeKey) && classKeyCounts.get(classNodeKey) === 1;
                                    var nodeKey = uniqueClassKey
                                        ? 'class:' + classNodeKey
                                        : (attrNodeKey ? 'attr:' + attrNodeKey : ensureGeneratedNodeKey(node));
                                    var speakerNode = node.querySelector('span') || node.querySelector('[style*="color"]') || node;
                                    var speakerColor = normalizeSpeakerColor(window.getComputedStyle(speakerNode).color);
                                    var row = {
                                        nodeKey: nodeKey,
                                        text: text,
                                        speakerColor: speakerColor,
                                        speakerChannel: classifySpeakerChannel(speakerColor),
                                        unstableKey: !uniqueClassKey && !attrNodeKey
                                    };
                                    var previous = rows.length ? rows[rows.length - 1] : null;
                                    if (
                                        previous &&
                                        compactText(previous.text) === compactText(row.text) &&
                                        (previous.nodeKey === row.nodeKey || (previous.unstableKey && row.unstableKey))
                                    ) {
                                        rows[rows.length - 1] = row;
                                        return;
                                    }
                                    rows.push(row);
                                });
                                return rows;
                            }
                            function buildPreview(rows) {
                                return rows.slice(-3).map(function(row) { return row.text; }).filter(Boolean).join(' ').trim();
                            }
                            function normalizeContainerText(node) {
                                var raw = node ? (node.innerText || node.textContent || '') : '';
                                var text = normalizeText(raw);
                                if (!text) return '';
                                if (text.length <= 400) return text;
                                var lines = String(raw || '').split('\\n').map(normalizeText).filter(Boolean);
                                return lines.slice(-3).join(' ');
                            }
                            function shouldBlockContainerFallback() {
                                if (!filterUnconfirmedArg) return false;
                                var smiNodes = queryAllSafe('#viewSubtit .smi_word');
                                if (!smiNodes.length) return false;
                                return readObservedRows('#viewSubtit .smi_word').length === 0;
                            }
                            var selectors = Array.isArray(selectorsArg) ? selectorsArg : [];
                            var blockContainerFallback = shouldBlockContainerFallback();
                            var fallbackSelectors = [
                                '#viewSubtit .incont',
                                '#viewSubtit',
                                '.subtitle_area',
                                '.ai_subtitle',
                                "[class*='subtitle']"
                            ];
                            for (var i = 0; i < selectors.length; i++) {
                                var selector = String(selectors[i] || '').trim();
                                if (!selector) continue;
                                if (selector.indexOf('.smi_word') >= 0) {
                                    var rows = readObservedRows(selector);
                                    var preview = buildPreview(rows);
                                    if (preview) {
                                        return { text: preview, matchedSelector: selector, found: true, rows: rows, sourceMode: 'smi-window' };
                                    }
                                    continue;
                                }
                                if (blockContainerFallback) continue;
                                var node = queryOneSafe(selector);
                                if (!node) continue;
                                var text = normalizeContainerText(node);
                                if (!text) continue;
                                return { text: text, matchedSelector: selector, found: true, rows: [], sourceMode: 'container' };
                            }
                            if (!blockContainerFallback) {
                                for (var j = 0; j < fallbackSelectors.length; j++) {
                                    var fallbackSelector = fallbackSelectors[j];
                                    var fallbackNode = queryOneSafe(fallbackSelector);
                                    if (!fallbackNode) continue;
                                    var fallbackText = normalizeContainerText(fallbackNode);
                                    if (!fallbackText) continue;
                                    return { text: fallbackText, matchedSelector: fallbackSelector, found: true, rows: [], sourceMode: 'container' };
                                }
                            }
                            return { text: '', matchedSelector: '', found: false, rows: [], sourceMode: '' };
                        })(arguments[0], arguments[1]);
                        """,
                        selectors,
                        bool(filter_unconfirmed_enabled),
                    )
                except Exception as e:
                    logger.debug("subtitle probe error: %s", e)
                    return {
                        "text": "",
                        "matched_selector": "",
                        "found": False,
                        "rows": [],
                        "source_mode": "",
                    }
                result = result or {}
                return {
                    "text": utils.clean_text_display(str(result.get("text", ""))).strip(),
                    "matched_selector": str(result.get("matchedSelector", "") or ""),
                    "found": bool(result.get("found", False)),
                    "rows": _normalize_rows(result.get("rows", [])),
                    "source_mode": str(result.get("sourceMode", "") or ""),
                }

            frame_paths: list[tuple[int, ...]] = []
            if preferred_frame_path:
                frame_paths.append(preferred_frame_path)
            frame_paths.append(())
            for frame_path in self._iter_frame_paths(driver, max_depth=3, max_frames=60):
                if frame_path not in frame_paths:
                    frame_paths.append(frame_path)

            for frame_path in frame_paths:
                try:
                    if frame_path:
                        if not self._switch_to_frame_path(driver, frame_path):
                            continue
                    else:
                        try:
                            driver.switch_to.default_content()
                        except Exception:
                            pass
                    result = _probe_in_current_context()
                    if result.get("found"):
                        self._last_subtitle_frame_path = frame_path
                        result["frame_path"] = frame_path
                        return result
                finally:
                    try:
                        driver.switch_to.default_content()
                    except Exception:
                        pass

            return {
                "text": "",
                "matched_selector": "",
                "found": False,
                "rows": [],
                "source_mode": "",
                "frame_path": (),
            }


    def _read_subtitle_text_by_selectors(
            self,
            driver,
            selectors: list[str],
            preferred_frame_path: tuple[int, ...] = (),
        ) -> tuple[str, str, bool]:
            """여러 셀렉터를 순차 시도해 자막 텍스트를 읽는다.

            Returns:
                (text, matched_selector, found_element)
            """
            def _read_in_current_context() -> tuple[str, str, bool]:
                def _read_smi_word_window(sel: str) -> tuple[str, bool]:
                    """`.smi_word` 전체를 수집해 최근 창(window) 텍스트를 반환한다.

                    확장프로그램(Assembly Webcast Subtitle Saver)처럼 단일 노드가 아닌
                    `.smi_word` 목록을 기준으로 최신 변화를 추적해 첫 문장 이후 정체를 줄인다.
                    """
                    try:
                        rows = driver.execute_script(
                            """
                            return (function(selectorArg) {
                                function normalizeText(v) {
                                    return String(v || '').replace(/\\s+/g, ' ').trim();
                                }
                                var q = String(selectorArg || '').trim();
                                if (!q) q = '#viewSubtit .smi_word';
                                q = q.replace(/:last-child/g, '').replace(/:last-of-type/g, '');
                                var nodes = [];
                                try { nodes = Array.from(document.querySelectorAll(q)); } catch (e) {}
                                if ((!nodes || !nodes.length) && q !== '#viewSubtit .smi_word') {
                                    try { nodes = Array.from(document.querySelectorAll('#viewSubtit .smi_word')); } catch (e) {}
                                }
                                return nodes.map(function(el, idx) {
                                    var cls = String(el.className || '');
                                    var idPart = cls.replace(/\\bsmi_word\\b/g, '').trim();
                                    var text = normalizeText(el.innerText || el.textContent || '');
                                    return { id: idPart || String(idx), text: text };
                                });
                            })(arguments[0]);
                            """,
                            sel,
                        )
                    except Exception as e:
                        logger.debug("smi_word 수집 오류 (%s): %s", sel, e)
                        return "", False

                    if not isinstance(rows, list) or not rows:
                        return "", False

                    normalized_rows: list[tuple[str, str, str]] = []
                    for row in rows:
                        if isinstance(row, dict):
                            row_text = utils.clean_text_display(str(row.get("text", ""))).strip()
                            row_id = str(row.get("id", "")).strip()
                        else:
                            row_text = utils.clean_text_display(str(row)).strip()
                            row_id = ""
                        if not row_text:
                            continue

                        row_compact = utils.compact_subtitle_text(row_text)
                        if not row_compact:
                            continue

                        # 인접 중복(동일 compact)은 하나로 압축해 불필요한 정체를 줄인다.
                        if normalized_rows and normalized_rows[-1][2] == row_compact:
                            normalized_rows[-1] = (row_id, row_text, row_compact)
                        else:
                            normalized_rows.append((row_id, row_text, row_compact))

                    if not normalized_rows:
                        return "", False

                    tail_texts = [t for _, t, _ in normalized_rows[-3:]]
                    window_text = " ".join(tail_texts).strip()
                    if not window_text:
                        return "", False
                    return window_text, True

                for sel in selectors:
                    if ".smi_word" in sel:
                        smi_text, smi_found = _read_smi_word_window(sel)
                        if smi_found:
                            return smi_text, sel, True

                    try:
                        element = driver.find_element(By.CSS_SELECTOR, sel)
                    except (NoSuchElementException, StaleElementReferenceException):
                        continue
                    except Exception as e:
                        logger.debug("셀렉터 조회 오류 (%s): %s", sel, e)
                        continue

                    try:
                        text = (element.text or "").strip()
                    except StaleElementReferenceException:
                        continue
                    except Exception:
                        text = ""
                    return text, sel, True
                return "", "", False

            # 선호 프레임(Observer가 설치된 프레임)을 우선 확인
            if preferred_frame_path:
                try:
                    if self._switch_to_frame_path(driver, preferred_frame_path):
                        result = _read_in_current_context()
                        if result[2]:
                            self._last_subtitle_frame_path = preferred_frame_path
                            return result
                finally:
                    driver.switch_to.default_content()

            # 기본 문서 확인
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            result = _read_in_current_context()
            if result[2]:
                self._last_subtitle_frame_path = ()
                return result

            # 중첩 iframe/frame 순회 확인
            for frame_path in self._iter_frame_paths(driver, max_depth=3, max_frames=60):
                try:
                    if self._switch_to_frame_path(driver, frame_path):
                        result = _read_in_current_context()
                        if result[2]:
                            self._last_subtitle_frame_path = frame_path
                            return result
                finally:
                    try:
                        driver.switch_to.default_content()
                    except Exception:
                        pass

            return "", "", False


    def _switch_to_frame_path(self, driver, frame_path: tuple[int, ...]) -> bool:
            """frame index 경로로 이동한다. 실패 시 False."""
            try:
                driver.switch_to.default_content()
            except Exception:
                return False

            for idx in frame_path:
                try:
                    frames = driver.find_elements(By.CSS_SELECTOR, "iframe,frame")
                    if idx < 0 or idx >= len(frames):
                        return False
                    driver.switch_to.frame(frames[idx])
                except Exception:
                    return False
            return True


    def _iter_frame_paths(
            self, driver, max_depth: int = 3, max_frames: int = 60
        ) -> list[tuple[int, ...]]:
            """중첩 iframe/frame 경로 목록을 반환한다."""
            paths: list[tuple[int, ...]] = []

            def _walk(path: tuple[int, ...], depth: int) -> None:
                if len(paths) >= max_frames or depth > max_depth:
                    return
                if not self._switch_to_frame_path(driver, path):
                    return
                try:
                    frames = driver.find_elements(By.CSS_SELECTOR, "iframe,frame")
                except Exception:
                    return

                for idx in range(len(frames)):
                    child = path + (idx,)
                    paths.append(child)
                    if len(paths) >= max_frames:
                        return
                    _walk(child, depth + 1)

            try:
                _walk((), 0)
            finally:
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass

            return paths


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
                    var containerFirst = [
                        '#viewSubtit .incont',
                        '#viewSubtit',
                        '.subtitle_area',
                        '.ai_subtitle',
                        "[class*='subtitle']"
                    ];
                    for (var c = 0; c < containerFirst.length; c++) {
                        pushUnique(targetSelectors, containerFirst[c]);
                    }
                    for (var s = 0; s < selectors.length; s++) {
                        pushUnique(targetSelectors, selectors[s]);
                    }

                    var target = null;
                    for (var i = 0; i < targetSelectors.length; i++) {
                        try {
                            target = document.querySelector(targetSelectors[i]);
                        } catch (e) {
                            target = null;
                        }
                        if (target) break;
                    }

                    function normalizeText(text) {
                        return String(text || '').replace(/\\s+/g, ' ').trim();
                    }

                    function isLikelySubtitleText(text) {
                        if (!text) return false;
                        if (text.length < 3 || text.length > 320) return false;
                        if (!/[가-힣A-Za-z]/.test(text)) return false;
                        if (/^[\\d\\s:.,\\-_/()%]+$/.test(text)) return false;
                        return true;
                    }

                    function pickBestMutationText(mutations) {
                        var bestText = '';
                        var bestScore = -1;
                        for (var i = 0; i < mutations.length; i++) {
                            var m = mutations[i];
                            var node = m && m.target ? m.target : null;
                            var el = null;
                            if (node && node.nodeType === 1) el = node;
                            else if (node && node.parentElement) el = node.parentElement;
                            if (!el) continue;
                            if (el.tagName === 'SCRIPT' || el.tagName === 'STYLE') continue;
                            if (typeof el.closest === 'function') {
                                var bad = el.closest('script,style,head,noscript');
                                if (bad) continue;
                            }

                            var text = normalizeText(el.innerText || el.textContent || '');
                            if (!isLikelySubtitleText(text)) continue;

                            if (text.length > 120) {
                                var lines = String(el.innerText || '').split('\\n')
                                    .map(function(v) { return normalizeText(v); })
                                    .filter(function(v) { return !!v; });
                                if (lines.length) {
                                    var tail = lines[lines.length - 1];
                                    if (isLikelySubtitleText(tail)) text = tail;
                                }
                            }

                            var score = 0;
                            try {
                                var idClass = ((el.id || '') + ' ' + (el.className || '')).toLowerCase();
                                if (/subtit|subtitle|caption|script|stt|transcript|incont|viewsubtit/.test(idClass)) score += 6;
                                var rect = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
                                if (rect && rect.width > 0 && rect.height > 0) score += 2;
                                if (rect && rect.bottom >= (window.innerHeight * 0.35)) score += 1;
                            } catch (e) {}

                            score += Math.min(4, Math.floor(text.length / 25));

                            if (score > bestScore) {
                                bestScore = score;
                                bestText = text;
                            }
                        }
                        return bestText;
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
                                    window.__subtitleBuffer.push('__SUBTITLE_CLEARED__');
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

                    // 타겟을 못 찾은 경우: 주기적 selector 스캔으로 Observer 버퍼 브리지
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
                                window.__subtitleBuffer.push('__SUBTITLE_CLEARED__');
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
            """MutationObserver를 페이지에 주입하여 자막 변경을 이벤트 기반으로 캡처한다.

            Returns:
                (주입 성공 여부, observer frame 경로)
            """
            try:
                safe_selector = selector if isinstance(selector, str) else ""
                priority_paths: list[tuple[int, ...]] = []
                last_path = getattr(self, "_last_subtitle_frame_path", ())
                if isinstance(last_path, tuple):
                    priority_paths.append(last_path)
                priority_paths.append(())
                for p in self._iter_frame_paths(driver, max_depth=3, max_frames=60):
                    if p not in priority_paths:
                        priority_paths.append(p)

                # 1) 타겟 기반 Observer 우선 시도
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

                # 2) 타겟 미탐색 시 JS 폴링 브리지 fallback
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
            """MutationObserver 버퍼에서 변경된 텍스트를 수집한다.

            Returns:
                list: 변경된 텍스트 목록 (비어있을 수 있음)
                None: Observer가 죽었거나 오류 발생 (폴링 fallback 필요)
            """
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
                    return None  # Observer가 없음
                return result if isinstance(result, list) else []
            except Exception as e:
                logger.debug("Observer 버퍼 수집 오류: %s", e)
                return None
            finally:
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass


    def _activate_subtitle(self, driver) -> bool:
            """자막 레이어 활성화 - 다양한 방법 시도

            Returns:
                bool: 활성화 성공 여부
            """
            activation_scripts = [
                # 방법 1: layerSubtit 함수 호출
                "if(typeof layerSubtit==='function'){layerSubtit(); return true;} return false;",
                # 방법 2: 자막 버튼 클릭
                "var btn=document.querySelector('.btn_subtit'); if(btn){btn.click(); return true;} return false;",
                "var btn=document.querySelector('#btnSubtit'); if(btn){btn.click(); return true;} return false;",
                # 방법 3: AI 자막 버튼
                "var btn=document.querySelector('[data-action=\\'subtitle\\']'); if(btn){btn.click(); return true;} return false;",
                # 방법 4: 자막 레이어 직접 표시
                "var layer=document.querySelector('#viewSubtit'); if(layer){layer.style.display='block'; return true;} return false;",
            ]

            activated = False
            for idx, script in enumerate(activation_scripts, start=1):
                try:
                    result = driver.execute_script(script)
                    if result:
                        logger.info(
                            "자막 활성화 성공 (step=%s/%s): %s...",
                            idx,
                            len(activation_scripts),
                            script[:50],
                        )
                        activated = True
                        break
                    self.stop_event.wait(timeout=0.5)
                except Exception as e:
                    logger.debug(f"자막 활성화 스크립트 실패: {e}")

            # 추가 대기 - 자막 레이어 로딩 (종료 신호에 즉시 반응)
            self.stop_event.wait(timeout=2.0)
            return activated


    def _find_subtitle_selector(self, driver) -> str:
            """사용 가능한 자막 셀렉터 자동 감지

            Returns:
                str: 찾은 셀렉터. 찾지 못하면 빈 문자열.
            """
            # 우선순위대로 셀렉터 확인
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
