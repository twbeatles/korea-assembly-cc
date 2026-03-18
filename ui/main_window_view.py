# -*- coding: utf-8 -*-

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost


class MainWindowViewMixin(MainWindowHost):

    def _rebuild_stats_cache(self) -> None:
            """현재 자막 리스트 기반으로 통계 캐시를 재계산.

            - 세션 로드/병합/삭제/편집 등으로 자막 리스트가 바뀌는 경우 호출한다.
            - 캐시는 UI 통계/카운트 라벨에서 재계산 비용을 줄이기 위해 사용된다.
            """
            with self.subtitle_lock:
                self._cached_total_chars = sum(s.char_count for s in self.subtitles)
                self._cached_total_words = sum(s.word_count for s in self.subtitles)


    def _set_preview_text(self, text: str) -> None:
            """미리보기 텍스트 표시/숨김"""
            if not hasattr(self, "preview_frame"):
                return
            content = (text or "").strip()
            if content:
                if self.preview_label.text() != content:
                    self.preview_label.setText(content)
                if not self.preview_frame.isVisible():
                    self.preview_frame.show()
            else:
                if self.preview_label.text():
                    self.preview_label.setText("")
                if self.preview_frame.isVisible():
                    self.preview_frame.hide()


    def _clear_preview(self) -> None:
            """미리보기 초기화"""
            self._set_preview_text("")


    def _update_preview(self, raw: str) -> None:
            """미리보기 업데이트 (별도 UI)"""
            self._set_preview_text(raw)


    def _build_render_chunk(
            self,
            entry: SubtitleEntry,
            previous_entry: SubtitleEntry | None,
            show_ts: bool,
            last_printed_ts: datetime | None,
        ) -> tuple[str, str, datetime | None]:
            separator = ""
            same_second = False
            if previous_entry is not None:
                same_second = entry.timestamp.replace(
                    microsecond=0
                ) == previous_entry.timestamp.replace(microsecond=0)
                separator = " " if same_second else "\n"

            prefix = ""
            next_last_printed_ts = last_printed_ts
            if show_ts and not same_second:
                should_print = False
                if last_printed_ts is None:
                    should_print = True
                elif (entry.timestamp - last_printed_ts).total_seconds() >= 60:
                    should_print = True

                if should_print:
                    prefix = f"[{entry.timestamp.strftime('%H:%M:%S')}] "
                    next_last_printed_ts = entry.timestamp

            return separator, prefix, next_last_printed_ts


    def _insert_render_chunk(
            self,
            cursor,
            separator: str,
            prefix: str,
            text: str,
        ) -> None:
            if separator:
                cursor.insertText(separator, self._normal_fmt)
            if prefix:
                cursor.insertText(prefix, self._timestamp_fmt)
            self._insert_highlighted_text(cursor, text)


    def _patch_last_render_chunk(self, text: str) -> bool:
            specs = getattr(self, "_last_render_chunk_specs", [])
            if not specs:
                return False

            document = self.subtitle_text.document()
            if document is None:
                return False

            start_pos = sum(len(sep) + len(prefix) + len(chunk_text) for sep, prefix, chunk_text in specs[:-1])
            cursor = self.subtitle_text.textCursor()
            cursor.setPosition(start_pos)
            cursor.setPosition(
                document.characterCount() - 1,
                QTextCursor.MoveMode.KeepAnchor,
            )
            cursor.removeSelectedText()

            separator, prefix, _old_text = specs[-1]
            self._insert_render_chunk(cursor, separator, prefix, text)
            specs[-1] = (separator, prefix, text)
            self._last_render_chunk_specs = specs
            return True


    def _render_subtitles(self, force_full: bool = False) -> None:
            """Render subtitles with incremental updates when possible."""
            scrollbar = self.subtitle_text.verticalScrollBar()
            assert scrollbar is not None
            preserve_scroll = self._user_scrolled_up
            saved_scroll = 0
            if preserve_scroll:
                saved_scroll = scrollbar.value()
                scrollbar.blockSignals(True)

            # Snapshot for rendering
            with self.subtitle_lock:
                subtitles_copy = list(self.subtitles)

            total_count = len(subtitles_copy)

            # 성능 최적화: 대량 자막 시 최근 항목만 렌더링 (#4)
            render_offset = 0
            if total_count > Config.MAX_RENDER_ENTRIES:
                render_offset = total_count - Config.MAX_RENDER_ENTRIES
                subtitles_copy = subtitles_copy[render_offset:]

            visible_count = len(subtitles_copy)
            last_text = subtitles_copy[-1].text if subtitles_copy else ""

            show_ts = self.timestamp_action.isChecked()

            # 마지막 출력된 타임스탬프 (희소 타임스탬프용)
            # 렌더링 시작 시 초기화
            if not hasattr(self, "_last_printed_ts"):
                self._last_printed_ts = None

            previous_visible_count = max(
                0, self._last_rendered_count - getattr(self, "_last_render_offset", 0)
            )
            offset_changed = render_offset != getattr(self, "_last_render_offset", 0)
            show_ts_changed = (
                self._last_render_show_ts is not None and show_ts != self._last_render_show_ts
            )
            tail_text_changed = (
                total_count == self._last_rendered_count
                and last_text != self._last_rendered_last_text
            )

            needs_full_render = (
                force_full
                or offset_changed
                or show_ts_changed
                or (total_count < self._last_rendered_count)
                or (previous_visible_count > visible_count)
            )

            if needs_full_render:
                self.subtitle_text.clear()
                self._last_printed_ts = None  # 풀 렌더링 시 초기화
                cursor = self.subtitle_text.textCursor()
                chunk_specs: list[tuple[str, str, str]] = []
                last_printed_ts = None

                for i, entry in enumerate(subtitles_copy):
                    prev_entry = subtitles_copy[i - 1] if i > 0 else None
                    separator, prefix, last_printed_ts = self._build_render_chunk(
                        entry,
                        prev_entry,
                        show_ts,
                        last_printed_ts,
                    )
                    self._insert_render_chunk(cursor, separator, prefix, entry.text)
                    chunk_specs.append((separator, prefix, entry.text))

                self._last_printed_ts = last_printed_ts
                self._last_render_chunk_specs = chunk_specs

            elif tail_text_changed and visible_count == previous_visible_count and visible_count > 0:
                if not self._patch_last_render_chunk(last_text):
                    self._render_subtitles(force_full=True)
                    return

            else:
                cursor = self.subtitle_text.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                chunk_specs = list(getattr(self, "_last_render_chunk_specs", []))
                last_printed_ts = self._last_printed_ts

                start_local_idx = min(previous_visible_count, visible_count)
                for local_idx in range(start_local_idx, visible_count):
                    entry = subtitles_copy[local_idx]
                    prev_entry = subtitles_copy[local_idx - 1] if local_idx > 0 else None
                    separator, prefix, last_printed_ts = self._build_render_chunk(
                        entry,
                        prev_entry,
                        show_ts,
                        last_printed_ts,
                    )
                    self._insert_render_chunk(cursor, separator, prefix, entry.text)
                    chunk_specs.append((separator, prefix, entry.text))

                self._last_printed_ts = last_printed_ts
                self._last_render_chunk_specs = chunk_specs

            self._last_rendered_count = total_count
            self._last_rendered_last_text = last_text
            self._last_render_offset = render_offset
            self._last_render_show_ts = show_ts

            if self.auto_scroll_check.isChecked() and not self._user_scrolled_up:
                self.subtitle_text.moveCursor(QTextCursor.MoveOperation.End)

            if preserve_scroll:
                scrollbar.setValue(min(saved_scroll, scrollbar.maximum()))
                scrollbar.blockSignals(False)


    def _on_scroll_changed(self) -> None:
            """스크롤바 위치 변경 감지 - 스마트 스크롤용"""
            scrollbar = self.subtitle_text.verticalScrollBar()
            assert scrollbar is not None
            # 스크롤이 맨 아래에서 일정 거리 이내면 자동 스크롤 활성화
            at_bottom = (
                scrollbar.value() >= scrollbar.maximum() - Config.SCROLL_BOTTOM_THRESHOLD
            )

            if at_bottom:
                self._user_scrolled_up = False
                if hasattr(self, "scroll_to_bottom_btn"):
                    self.scroll_to_bottom_btn.hide()
            else:
                # 사용자가 위로 스크롤한 경우
                self._user_scrolled_up = True
                # 추출 중일 때만 버튼 표시
                if self.is_running and hasattr(self, "scroll_to_bottom_btn"):
                    self.scroll_to_bottom_btn.show()


    def _scroll_to_bottom(self) -> None:
            """맨 아래로 스크롤하고 자동 스크롤 재개"""
            self._user_scrolled_up = False
            self.subtitle_text.moveCursor(QTextCursor.MoveOperation.End)
            if hasattr(self, "scroll_to_bottom_btn"):
                self.scroll_to_bottom_btn.hide()


    def _toggle_stats_panel(self) -> None:
            """통계 패널 숨기기/보이기"""
            if hasattr(self, "stats_group") and hasattr(self, "toggle_stats_btn"):
                is_visible = self.stats_group.isVisible()
                self.stats_group.setVisible(not is_visible)

                if is_visible:
                    self.toggle_stats_btn.setText("📊 통계 보이기")
                    # 자막 영역이 전체 너비를 사용하도록
                    self.main_splitter.setSizes([1080, 0])
                else:
                    self.toggle_stats_btn.setText("📊 통계 숨기기")
                    self.main_splitter.setSizes([860, 220])


    def _refresh_text(self, force_full: bool = False) -> None:
            """확정된 자막만 표시 (진행 중인 자막 없음)"""
            self._render_subtitles(force_full=force_full)


    def _refresh_text_full(self, *_args) -> None:
            """렌더 캐시를 무시하고 전체 다시 그리기"""
            self._refresh_text(force_full=True)


    def _finalize_subtitle(self, text):
            """자막 확정 - 단어 단위 증분 병합 (Incremental Word Accumulation)

            [Thread Safety] subtitle_lock으로 self.subtitles 접근 보호
            """
            if not text:
                return

            # [Fix] 중복 처리 방지: _process_raw_text에서 이미 처리된 텍스트면 건너뜀
            # _last_processed_raw가 동일하면 이미 _process_raw_text에서 자막이 추가됨
            if text == self._last_processed_raw:
                return

            # [Fix] 확정된 자막을 프로세서에 등록 (#SubtitleRepetitionFix)
            self.subtitle_processor.add_confirmed(text)

            # 스레드 안전하게 자막 접근
            with self.subtitle_lock:
                # 이전에 확정된 자막이 있으면, 겹치는 부분 제거
                if self.subtitles:
                    last_text = self.subtitles[-1].text

                    # [Smart Merge] 단어 단위 겹침 분석하여 새로운 단어만 추출
                    new_part = utils.get_word_diff(last_text, text)

                    if new_part:
                        # [Length Check] 문장이 너무 길어지면 강제로 끊고 시 타임스탬프 생성
                        current_len = len(last_text)
                        new_len = len(new_part)

                        # 기존 길이에 새 내용을 더했을 때 최대 길이를 초과하면 분리
                        if current_len + new_len > Config.STREAM_SUBTITLE_MAX_LENGTH:
                            entry = SubtitleEntry(new_part)
                            entry.start_time = datetime.now()
                            entry.end_time = datetime.now()
                            self.subtitles.append(entry)
                            # 통계 캐시 갱신
                            self._cached_total_chars += entry.char_count
                            self._cached_total_words += entry.word_count

                            if self.realtime_file:
                                try:
                                    # 분리된 새 문장으로 저장
                                    timestamp = entry.timestamp.strftime("%H:%M:%S")
                                    self.realtime_file.write(f"[{timestamp}] {new_part}\n")
                                    self.realtime_file.flush()
                                except IOError as e:
                                    logger.warning(f"실시간 저장 쓰기 오류: {e}")
                        else:
                            # 새로운 내용이 있으면 이어붙이기 - update_text()로 캐시 갱신 포함
                            old_chars = self.subtitles[-1].char_count
                            old_words = self.subtitles[-1].word_count
                            self.subtitles[-1].update_text(
                                self._join_stream_text(self.subtitles[-1].text, new_part)
                            )
                            self.subtitles[-1].end_time = datetime.now()
                            # 통계 캐시 갱신
                            self._cached_total_chars += (
                                self.subtitles[-1].char_count - old_chars
                            )
                            self._cached_total_words += (
                                self.subtitles[-1].word_count - old_words
                            )

                            # 실시간 저장
                            if self.realtime_file:
                                try:
                                    # + 기호로 이어붙여진 내용임을 표시
                                    self.realtime_file.write(f"+ {new_part}\n")
                                    self.realtime_file.flush()
                                except IOError as e:
                                    logger.warning(f"실시간 저장 쓰기 오류: {e}")
                        return
                    else:
                        # 겹치는 내용만 있고 새로운 내용이 없으면 (부분집합)
                        # 시간만 갱신하고 종료
                        self.subtitles[-1].end_time = datetime.now()
                        return

                # 첫 번째 자막 또는 완전히 새로운 문장
                entry = SubtitleEntry(text)
                entry.start_time = datetime.now()
                entry.end_time = datetime.now()

                self.subtitles.append(entry)
                # 통계 캐시 갱신
                self._cached_total_chars += entry.char_count
                self._cached_total_words += entry.word_count

            # 키워드 알림 확인 (락 밖에서 - UI 작업)
            self._check_keyword_alert(text)

            # 카운트 라벨 업데이트
            self._update_count_label()

            # 실시간 저장
            if self.realtime_file:
                try:
                    timestamp = entry.timestamp.strftime("%H:%M:%S")
                    self.realtime_file.write(f"[{timestamp}] {text}\n")
                    self.realtime_file.flush()
                except IOError as e:
                    logger.warning(f"실시간 저장 쓰기 오류: {e}")

            self._refresh_text(force_full=False)


    def _insert_highlighted_text(self, cursor, text):
            """텍스트에서 키워드만 하이라이트 (성능 최적화: 캐시된 패턴/포맷 사용)"""
            text = self._normalize_subtitle_text_for_option(text)
            if not text:
                return
            # 키워드 캐시가 비어있으면 일반 텍스트로 삽입
            if not self._keyword_pattern:
                cursor.insertText(text, self._normal_fmt)
                return

            # 캐시된 패턴으로 분할
            parts = self._keyword_pattern.split(text)

            for part in parts:
                if not part:  # 빈 문자열 건너뛰기
                    continue

                if part.lower() in self._keywords_lower_set:
                    # 키워드: 캐시된 하이라이트 포맷 사용
                    cursor.insertText(part, self._highlight_fmt)
                else:
                    # 일반 텍스트: 캐시된 일반 포맷 사용
                    cursor.insertText(part, self._normal_fmt)


    def _rebuild_keyword_cache(
            self, keywords: list, update_settings: bool = True, refresh: bool = True
        ) -> None:
            """하이라이트 키워드 캐시 재구성"""
            cleaned = [k.strip() for k in keywords if k and k.strip()]
            self.keywords = cleaned
            self._keywords_lower_set = {k.lower() for k in cleaned}

            if cleaned:
                pattern = "|".join(re.escape(k) for k in cleaned)
                try:
                    self._keyword_pattern = re.compile(f"({pattern})", re.IGNORECASE)
                except re.error:
                    self._keyword_pattern = None
            else:
                self._keyword_pattern = None

            if update_settings:
                self.settings.setValue("highlight_keywords", ", ".join(self.keywords))

            if refresh and hasattr(self, "subtitle_text"):
                self._refresh_text(force_full=True)


    def _update_keyword_cache(self):
            """키워드 패턴 캐시 업데이트 (디바운싱 적용)"""
            # 디바운싱: 이전 타이머 취소
            if (
                hasattr(self, "_keyword_debounce_timer")
                and self._keyword_debounce_timer.isActive()
            ):
                self._keyword_debounce_timer.stop()

            def do_update():
                self._perform_keyword_cache_update()

            # 300ms 후 실행
            self._keyword_debounce_timer = QTimer(self)
            self._keyword_debounce_timer.setSingleShot(True)
            self._keyword_debounce_timer.timeout.connect(do_update)
            self._keyword_debounce_timer.start(300)


    def _perform_keyword_cache_update(self):
            """실제 키워드 캐시 업데이트 로직"""
            try:
                if hasattr(self, "keyword_input"):
                    raw_text = self.keyword_input.text()
                else:
                    raw_text = ", ".join(self.keywords)

                keywords = [k.strip() for k in raw_text.split(",") if k.strip()]
                self._rebuild_keyword_cache(keywords, update_settings=True, refresh=True)
            except Exception as e:
                logger.error(f"키워드 캐시 업데이트 오류: {e}")


    def _copy_to_clipboard(self) -> None:
            """자막 전체를 클립보드에 복사"""
            with self.subtitle_lock:
                if not self.subtitles:
                    self._show_toast("복사할 자막이 없습니다", "warning")
                    return

                text = "\n".join(s.text for s in self.subtitles)

            clipboard = QApplication.clipboard()
            if clipboard is None:
                self._show_toast("클립보드를 사용할 수 없습니다", "error")
                return
            clipboard.setText(text)
            self._show_toast(f"📋 {len(self.subtitles)}개 자막 복사됨", "success")


    def _clear_subtitles(self) -> None:
            """자막 목록 초기화"""
            with self.subtitle_lock:
                count = len(self.subtitles)
            if not count:
                self._show_toast("지울 자막이 없습니다", "warning")
                return

            reply = QMessageBox.question(
                self,
                "자막 지우기",
                f"현재 {count}개의 자막을 모두 지우시겠습니까?\n이 작업은 되돌릴 수 없습니다.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )

            if reply != QMessageBox.StandardButton.Yes:
                return

            self._replace_subtitles_and_refresh([], keep_history_from_subtitles=False)
            self._show_toast(f"🗑️ {count}개 자막 삭제됨", "success")


    def _toggle_theme_from_button(self) -> None:
            """툴바 버튼에서 테마 전환"""
            self._toggle_theme()
            # 버튼 아이콘 업데이트
            if hasattr(self, "theme_toggle_btn"):
                self.theme_toggle_btn.setText("🌙" if self.is_dark_theme else "☀️")


    def _update_stats(self):
            """통계 업데이트 (성능 최적화: 캐시된 통계 사용)"""
            if self.start_time:
                elapsed = int(time.time() - self.start_time)
                h, r = divmod(elapsed, 3600)
                m, s = divmod(r, 60)
                self.stat_time.setText(f"⏱️ 실행 시간: {h:02d}:{m:02d}:{s:02d}")

                # 캐시된 통계 사용 (스레드 안전)
                with self.subtitle_lock:
                    subtitle_count = len(self.subtitles)

                # 캐시된 값 직접 사용 (매번 재계산 대신)
                total_chars = self._cached_total_chars
                total_words = self._cached_total_words

                self.stat_chars.setText(f"📝 글자 수: {total_chars:,}")
                self.stat_words.setText(f"📖 단어 수: {total_words:,}")
                self.stat_sents.setText(f"💬 문장 수: {subtitle_count}")

                if elapsed > 0:
                    cpm = int(total_chars / (elapsed / 60))
                    self.stat_cpm.setText(f"⚡ 분당 글자: {cpm}")


    def _show_search(self):
            self.search_frame.show()
            self.search_input.setFocus()
            self.search_input.selectAll()


    def _hide_search(self):
            self.search_frame.hide()
            self._refresh_text(force_full=True)


    def _do_search(self):
            query = self.search_input.text()
            if not query:
                return

            query_l = query.lower()
            text_l = self.subtitle_text.toPlainText().lower()
            self.search_matches = []

            start = 0
            while True:
                idx = text_l.find(query_l, start)
                if idx == -1:
                    break
                self.search_matches.append(idx)
                start = idx + 1

            self.search_idx = 0
            self.search_count.setText(f"{len(self.search_matches)}개")

            if self.search_matches:
                self._highlight_search(0)


    def _nav_search(self, delta):
            if not self.search_matches:
                return

            self.search_idx = (self.search_idx + delta) % len(self.search_matches)
            self._highlight_search(self.search_idx)


    def _highlight_search(self, idx):
            if not self.search_matches:
                return

            pos = self.search_matches[idx]
            query = self.search_input.text()

            cursor = self.subtitle_text.textCursor()
            cursor.setPosition(pos)
            cursor.setPosition(pos + len(query), QTextCursor.MoveMode.KeepAnchor)

            self.subtitle_text.setTextCursor(cursor)
            self.subtitle_text.ensureCursorVisible()

            self.search_count.setText(f"{idx + 1}/{len(self.search_matches)}")


    def _set_keywords(self):
            """하이라이트 키워드 설정"""
            current = ", ".join(self.keywords)
            text, ok = QInputDialog.getText(
                self,
                "하이라이트 키워드 설정",
                "하이라이트할 키워드 (쉼표로 구분):",
                text=current,
            )

            if ok:
                keywords = [k.strip() for k in text.split(",") if k.strip()]
                if hasattr(self, "keyword_input"):
                    self.keyword_input.blockSignals(True)
                    self.keyword_input.setText(", ".join(keywords))
                    self.keyword_input.blockSignals(False)
                self._rebuild_keyword_cache(keywords, update_settings=True, refresh=True)
                self._show_toast(f"하이라이트 키워드 {len(keywords)}개 설정됨", "success")


    def _rebuild_alert_keyword_cache(
            self, keywords: list, update_settings: bool = True
        ) -> None:
            """알림 키워드 캐시를 재구성한다."""
            cleaned = [k.strip() for k in keywords if k and k.strip()]
            self.alert_keywords = cleaned
            self._alert_keywords_cache = [(k, k.lower()) for k in cleaned]
            if update_settings:
                self.settings.setValue("alert_keywords", ", ".join(cleaned))


    def _set_alert_keywords(self):
            """알림 키워드 설정 - 해당 키워드 감지 시 토스트 알림"""
            current = ", ".join(self.alert_keywords)
            text, ok = QInputDialog.getText(
                self,
                "알림 키워드 설정",
                "알림을 받을 키워드 (쉼표로 구분):\n예: 법안, 의결, 통과",
                text=current,
            )

            if ok:
                self._rebuild_alert_keyword_cache(
                    [k.strip() for k in text.split(",") if k.strip()],
                    update_settings=True,
                )
                self._show_toast(
                    f"알림 키워드 {len(self.alert_keywords)}개 설정됨", "success"
                )


    def _check_keyword_alert(self, text: str):
            """키워드 포함 시 알림 표시"""
            if not self._alert_keywords_cache:
                return

            text_lower = text.lower()
            for original, keyword_lower in self._alert_keywords_cache:
                if keyword_lower and keyword_lower in text_lower:
                    self._show_toast(f"🔔 키워드 감지: {original}", "warning", 5000)
                    break


    def _clear_text(self):
            if not self.subtitles:
                return

            reply = QMessageBox.question(
                self,
                "확인",
                "모든 내용을 지우시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )

            if reply == QMessageBox.StandardButton.Yes:
                self._replace_subtitles_and_refresh(
                    [], keep_history_from_subtitles=False
                )
                self.status_label.setText("내용 삭제됨")


    def _edit_subtitle(self):
            """선택한 자막 편집"""
            if not self.subtitles:
                self._show_toast("편집할 자막이 없습니다.", "warning")
                return
            if self.is_running:
                self._show_toast(
                    "추출 중에는 편집이 불안정할 수 있습니다. 먼저 중지하세요.", "warning"
                )
                return

            # 자막 목록 다이얼로그
            dialog = QDialog(self)
            dialog.setWindowTitle("자막 편집")
            dialog.setMinimumSize(600, 400)

            layout = QVBoxLayout(dialog)

            # 안내 라벨
            info_label = QLabel("편집할 자막을 선택하세요:")
            layout.addWidget(info_label)

            # 자막 목록
            list_widget = QListWidget()
            for i, entry in enumerate(self.subtitles):
                timestamp = entry.timestamp.strftime("%H:%M:%S")
                text_preview = (
                    entry.text[:50] + "..." if len(entry.text) > 50 else entry.text
                )
                list_widget.addItem(f"[{timestamp}] {text_preview}")
            layout.addWidget(list_widget)

            # 편집 영역
            edit_label = QLabel("자막 내용:")
            layout.addWidget(edit_label)

            edit_text = QTextEdit()
            edit_text.setMaximumHeight(100)
            layout.addWidget(edit_text)

            # 선택 시 내용 로드
            def on_selection_changed():
                idx = list_widget.currentRow()
                if 0 <= idx < len(self.subtitles):
                    edit_text.setText(self.subtitles[idx].text)

            list_widget.currentRowChanged.connect(on_selection_changed)

            # 버튼
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Save
                | QDialogButtonBox.StandardButton.Cancel
            )

            def save_edit():
                idx = list_widget.currentRow()
                if 0 <= idx < len(self.subtitles):
                    new_text = edit_text.toPlainText().strip()
                    if new_text:
                        with self.subtitle_lock:
                            entry = self.subtitles[idx]
                            old_chars = entry.char_count
                            old_words = entry.word_count
                            entry.update_text(new_text)
                            self._cached_total_chars += entry.char_count - old_chars
                            self._cached_total_words += entry.word_count - old_words
                        self._refresh_text(force_full=True)
                        self._update_count_label()
                        self._show_toast("자막이 수정되었습니다.", "success")
                        dialog.accept()
                    else:
                        QMessageBox.warning(dialog, "알림", "자막 내용을 입력해주세요.")
                else:
                    QMessageBox.warning(dialog, "알림", "편집할 자막을 선택해주세요.")

            buttons.accepted.connect(save_edit)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)

            # 첫 번째 항목 선택
            if list_widget.count() > 0:
                list_widget.setCurrentRow(0)

            dialog.exec()


    def _delete_subtitle(self):
            """선택한 자막 삭제"""
            if not self.subtitles:
                self._show_toast("삭제할 자막이 없습니다.", "warning")
                return
            if self.is_running:
                self._show_toast(
                    "추출 중에는 삭제가 불안정할 수 있습니다. 먼저 중지하세요.", "warning"
                )
                return

            # 자막 목록 다이얼로그
            dialog = QDialog(self)
            dialog.setWindowTitle("자막 삭제")
            dialog.setMinimumSize(600, 400)

            layout = QVBoxLayout(dialog)

            # 안내 라벨
            info_label = QLabel("삭제할 자막을 선택하세요 (다중 선택 가능):")
            layout.addWidget(info_label)

            # 자막 목록 (다중 선택 가능)
            list_widget = QListWidget()
            list_widget.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)

            for i, entry in enumerate(self.subtitles):
                timestamp = entry.timestamp.strftime("%H:%M:%S")
                text_preview = (
                    entry.text[:50] + "..." if len(entry.text) > 50 else entry.text
                )
                list_widget.addItem(f"[{timestamp}] {text_preview}")
            layout.addWidget(list_widget)

            # 버튼
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
            ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
            if ok_button is not None:
                ok_button.setText("삭제")

            def delete_selected():
                selected_rows = sorted(
                    [i.row() for i in list_widget.selectedIndexes()], reverse=True
                )
                if not selected_rows:
                    QMessageBox.warning(dialog, "알림", "삭제할 자막을 선택해주세요.")
                    return

                reply = QMessageBox.question(
                    dialog,
                    "확인",
                    f"선택한 {len(selected_rows)}개의 자막을 삭제하시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )

                if reply == QMessageBox.StandardButton.Yes:
                    with self.subtitle_lock:
                        for row in selected_rows:
                            entry = self.subtitles[row]
                            self._cached_total_chars -= entry.char_count
                            self._cached_total_words -= entry.word_count
                            del self.subtitles[row]
                    self._refresh_text(force_full=True)
                    self._update_count_label()
                    self._show_toast(
                        f"{len(selected_rows)}개 자막이 삭제되었습니다.", "success"
                    )
                    dialog.accept()

            buttons.accepted.connect(delete_selected)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)

            dialog.exec()
