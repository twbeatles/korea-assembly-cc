# -*- coding: utf-8 -*-

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost


class MainWindowPersistenceToolsMixin(MainWindowHost):

    def _clean_newlines(self):
            """줄넘김 정리: 문장 부호 분리 및 병합 (스마트 리플로우)"""
            if self._is_runtime_mutation_blocked("줄넘김 정리"):
                return
            if self._is_background_shutdown_active():
                self._show_toast("종료 중이라 줄넘김 정리를 시작할 수 없습니다.", "warning")
                return
            if bool(self.__dict__.get("_reflow_in_progress", False)):
                self._show_toast("이미 줄넘김 정리가 진행 중입니다.", "info")
                return

            def continue_reflow() -> None:
                prepared_entries = self._build_persistent_entries_snapshot()
                if not prepared_entries:
                    self._show_toast("정리할 자막이 없습니다.", "warning")
                    return

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

                old_count = len(prepared_entries)
                self._reflow_in_progress = True
                self._set_status("줄넘김 정리 중...", "running")

                def background_reflow():
                    try:
                        new_subtitles = utils.reflow_subtitles(prepared_entries)
                        self._emit_control_message(
                            "reflow_done",
                            {
                                "old_count": old_count,
                                "subtitles": new_subtitles,
                            },
                        )
                    except Exception as e:
                        logger.error(f"리플로우 중 오류: {e}")
                        self._emit_control_message("reflow_failed", {"error": str(e)})

                started = self._start_background_thread(background_reflow, "ReflowWorker")
                if not started:
                    self._reflow_in_progress = False
                    self._set_status("줄넘김 정리 시작 거부 (종료 중)", "warning")
                    self._show_toast("종료 중이라 줄넘김 정리를 시작할 수 없습니다.", "warning")
                    return
                self._show_toast("줄넘김 정리 시작...", "info", 1500)

            self._run_after_full_session_hydrated("줄넘김 정리", continue_reflow)

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
