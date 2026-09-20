# -*- coding: utf-8 -*-

from collections.abc import Iterable
from typing import cast

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost
from core.resource_budget import ResourceBudget, ResourceBudgetLimits


class MainWindowDatabaseDialogsStatsMergeMixin(MainWindowHost):
    """DB 통계·병합 다이얼로그 (SRP: 통계/병합)."""

    def _show_db_stats(self):
            """데이터베이스 전체 통계"""
            db = self.db
            if db is None or not bool(self.__dict__.get("db_available", False)):
                QMessageBox.warning(self, "알림", self._get_db_degraded_message())
                return
            self._run_db_task(
                "db_stats",
                worker=lambda: db.get_statistics(),
                loading_text="DB 통계 조회 중...",
            )

    def _show_db_stats_dialog(self, stats: dict) -> None:
            msg = f"""
    <h2>📊 데이터베이스 통계</h2>
    <table>
    <tr><td><b>총 세션 수:</b></td><td>{stats.get("total_sessions", 0):,}개</td></tr>
    <tr><td><b>총 자막 수:</b></td><td>{stats.get("total_subtitles", 0):,}개</td></tr>
    <tr><td><b>총 글자 수:</b></td><td>{stats.get("total_characters", 0):,}자</td></tr>
    <tr><td><b>총 녹화 시간:</b></td><td>{stats.get("total_duration_hours", 0):.1f}시간</td></tr>
    </table>
    """
            QMessageBox.information(self, "데이터베이스 통계", msg)

    def _show_merge_dialog(self):
            """자막 병합 다이얼로그"""
            if self._is_runtime_mutation_blocked("세션 병합"):
                return
            dialog = QDialog(self)
            dialog.setWindowTitle("📎 자막 병합")
            dialog.setMinimumSize(600, 500)

            layout = QVBoxLayout(dialog)

            # 파일 목록
            layout.addWidget(QLabel("병합할 세션 파일을 추가하세요:"))
            file_list = QListWidget()
            file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            layout.addWidget(file_list)

            file_paths = []

            # 파일 추가/제거 버튼
            file_btn_layout = QHBoxLayout()

            add_btn = QPushButton("➕ 파일 추가")

            def add_files():
                paths, _ = QFileDialog.getOpenFileNames(
                    dialog, "세션 파일 선택", f"{Config.SESSION_DIR}/", "JSON 파일 (*.json)"
                )
                for path in paths:
                    if path not in file_paths:
                        file_paths.append(path)
                        file_list.addItem(Path(path).name)

            add_btn.clicked.connect(add_files)
            file_btn_layout.addWidget(add_btn)

            remove_btn = QPushButton("➖ 선택 제거")

            def remove_files():
                for item in file_list.selectedItems():
                    idx = file_list.row(item)
                    file_list.takeItem(idx)
                    if idx < len(file_paths):
                        file_paths.pop(idx)

            remove_btn.clicked.connect(remove_files)
            file_btn_layout.addWidget(remove_btn)

            layout.addLayout(file_btn_layout)

            # 옵션
            options_layout = QHBoxLayout()
            remove_dup_check = QCheckBox("중복 자막 제거")
            remove_dup_check.setChecked(True)
            sort_check = QCheckBox("시간순 정렬")
            sort_check.setChecked(True)
            dedupe_mode_combo = QComboBox()
            dedupe_mode_combo.addItem("보수적 (같은 초 동일 문장)", "conservative_same_second")
            dedupe_mode_combo.addItem("기존 (30초 버킷)", "legacy_bucket")
            options_layout.addWidget(remove_dup_check)
            options_layout.addWidget(sort_check)
            options_layout.addWidget(QLabel("중복 기준:"))
            options_layout.addWidget(dedupe_mode_combo)
            options_layout.addStretch()
            layout.addLayout(options_layout)

            # 버튼
            btn_layout = QHBoxLayout()

            merge_btn = QPushButton("병합 실행")

            def do_merge():
                if len(file_paths) < 2:
                    QMessageBox.warning(dialog, "알림", "2개 이상의 파일을 선택하세요.")
                    return

                def apply_merge(
                    existing_subtitles: list[SubtitleEntry] | None = None,
                ) -> None:
                    merged = self._merge_sessions(
                        file_paths,
                        remove_duplicates=remove_dup_check.isChecked(),
                        sort_by_time=sort_check.isChecked(),
                        existing_subtitles=existing_subtitles,
                        dedupe_mode=str(
                            dedupe_mode_combo.currentData() or "legacy_bucket"
                        ),
                    )

                    if merged:
                        self._store_destructive_undo_snapshot()
                        self._replace_subtitles_and_refresh(merged)
                        self._set_capture_source_metadata("", "")
                        self._mark_session_dirty()
                        self._notify_destructive_undo_available()
                        self._show_toast(f"병합 완료! {len(merged)}개 문장", "success")
                        dialog.accept()

                if self.subtitles:
                    reply = QMessageBox.question(
                        dialog,
                        "기존 자막 처리",
                        f"현재 {len(self.subtitles)}개의 자막이 있습니다.\n\n"
                        "기존 자막을 병합 결과에 포함하시겠습니까?\n"
                        "(Yes: 포함하여 병합 / No: 기존 자막 무시하고 파일들만 병합)",
                        QMessageBox.StandardButton.Yes
                        | QMessageBox.StandardButton.No
                        | QMessageBox.StandardButton.Cancel,
                    )
                    if reply == QMessageBox.StandardButton.Cancel:
                        return

                    if reply == QMessageBox.StandardButton.Yes:
                        def continue_merge_with_existing() -> None:
                            with self.subtitle_lock:
                                existing_subtitles = list(self.subtitles)
                            apply_merge(existing_subtitles)

                        self._run_after_full_session_hydrated(
                            "세션 병합",
                            continue_merge_with_existing,
                        )
                        return

                    if self._block_session_replacement_while_saving("세션 병합"):
                        return
                    self._run_after_dirty_session_action(
                        "세션 병합",
                        lambda: apply_merge(None),
                    )
                    return

                apply_merge(None)

            merge_btn.clicked.connect(do_merge)
            btn_layout.addWidget(merge_btn)

            cancel_btn = QPushButton("취소")
            cancel_btn.clicked.connect(dialog.reject)
            btn_layout.addWidget(cancel_btn)

            layout.addLayout(btn_layout)
            dialog.exec()
