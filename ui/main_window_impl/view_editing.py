# -*- coding: utf-8 -*-
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportCallIssue=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportAssignmentType=false

from __future__ import annotations

from importlib import import_module
from typing import Any

from PyQt6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from core.config import Config
from ui.main_window_common import (
    build_subtitle_dialog_items,
    filter_subtitle_dialog_items,
)
from ui.main_window_impl.contracts import ViewEditingHost


def _view_public() -> Any:
    return import_module("ui.main_window_view")


ViewEditingBase = object


class MainWindowViewEditingMixin(ViewEditingBase):
    def _build_subtitle_dialog_items(self):
        with self.subtitle_lock:
            entries = list(self.subtitles)
        return build_subtitle_dialog_items(
            entries,
            self._normalize_subtitle_text_for_option,
        )

    def _update_subtitle_dialog_count_label(self, state: dict[str, Any]) -> None:
        count_label = state.get("count_label")
        if count_label is None:
            return

        rendered_count = len(state.get("rendered_items", []))
        filtered_count = len(state.get("filtered_items", []))
        if filtered_count:
            count_label.setText(f"현재 {rendered_count}/{filtered_count}개 로드됨")
        else:
            count_label.setText("표시할 자막이 없습니다.")

    def _load_more_subtitle_dialog_items(
        self,
        list_widget,
        state: dict[str, Any],
        *,
        reset: bool = False,
    ) -> None:
        filtered_items = list(state.get("filtered_items", []))
        rendered_items = list(state.get("rendered_items", []))
        page_size = int(
            state.get("page_size", Config.SUBTITLE_DIALOG_PAGE_SIZE)
            or Config.SUBTITLE_DIALOG_PAGE_SIZE
        )

        if reset:
            list_widget.clear()
            rendered_items = []

        start = len(rendered_items)
        next_items = filtered_items[start : start + page_size]
        for item in next_items:
            list_widget.addItem(item.display_text)
        rendered_items.extend(next_items)
        state["rendered_items"] = rendered_items

        more_btn = state.get("more_btn")
        if more_btn is not None:
            more_btn.setEnabled(len(rendered_items) < len(filtered_items))

        self._update_subtitle_dialog_count_label(state)
        if list_widget.count() > 0 and list_widget.currentRow() < 0:
            list_widget.setCurrentRow(0)

    def _apply_subtitle_dialog_filter(
        self,
        list_widget,
        state: dict[str, Any],
        query: str,
    ) -> None:
        state["filtered_items"] = filter_subtitle_dialog_items(
            list(state.get("all_items", [])),
            query,
        )
        state["rendered_items"] = []
        self._load_more_subtitle_dialog_items(list_widget, state, reset=True)

    def _copy_to_clipboard(self) -> None:
        if self.is_running and self._has_runtime_archived_segments():
            with self.subtitle_lock:
                if not self.subtitles:
                    self._show_toast("복사할 자막이 없습니다", "warning")
                    return
                text = "\n".join(s.text for s in self.subtitles)
                copied_count = len(self.subtitles)

            clipboard = QApplication.clipboard()
            if clipboard is None:
                self._show_toast("클립보드를 사용할 수 없습니다", "error")
                return
            clipboard.setText(text)
            self._show_toast(
                f"실행 중에는 최근 {copied_count}개 자막만 복사했습니다.",
                "info",
                3500,
            )
            return

        def continue_copy() -> None:
            with self.subtitle_lock:
                if not self.subtitles:
                    self._show_toast("복사할 자막이 없습니다", "warning")
                    return
                text = "\n".join(s.text for s in self.subtitles)
                copied_count = len(self.subtitles)

            clipboard = QApplication.clipboard()
            if clipboard is None:
                self._show_toast("클립보드를 사용할 수 없습니다", "error")
                return
            clipboard.setText(text)
            self._show_toast(f"📋 {copied_count}개 자막 복사됨", "success")

        self._run_after_full_session_hydrated("클립보드 복사", continue_copy)

    def _clear_subtitles(self) -> None:
        if self._is_runtime_mutation_blocked("전체 자막 삭제"):
            return

        def continue_clear() -> None:
            count = self._get_global_subtitle_count()
            if not count:
                self._show_toast("지울 자막이 없습니다", "warning")
                return

            view_mod = _view_public()
            reply = view_mod.QMessageBox.question(
                self,
                "자막 지우기",
                f"현재 {count}개의 자막을 모두 지우시겠습니까?\n이 작업은 되돌릴 수 없습니다.",
                view_mod.QMessageBox.StandardButton.Yes
                | view_mod.QMessageBox.StandardButton.No,
                view_mod.QMessageBox.StandardButton.No,
            )

            if reply != view_mod.QMessageBox.StandardButton.Yes:
                return

            self._store_destructive_undo_snapshot()
            self._replace_subtitles_and_refresh([], keep_history_from_subtitles=False)
            self._mark_session_dirty()
            self._notify_destructive_undo_available()
            self._show_toast(f"🗑️ {count}개 자막 삭제됨", "success")

        self._run_after_full_session_hydrated("전체 자막 삭제", continue_clear)

    def _clear_text(self):
        if self._is_runtime_mutation_blocked("내용 지우기"):
            return

        def continue_clear_text() -> None:
            if not self.subtitles:
                return

            view_mod = _view_public()
            reply = view_mod.QMessageBox.question(
                self,
                "확인",
                "모든 내용을 지우시겠습니까?",
                view_mod.QMessageBox.StandardButton.Yes
                | view_mod.QMessageBox.StandardButton.No,
            )

            if reply == view_mod.QMessageBox.StandardButton.Yes:
                self._store_destructive_undo_snapshot()
                self._replace_subtitles_and_refresh([], keep_history_from_subtitles=False)
                self._mark_session_dirty()
                self._notify_destructive_undo_available()
                self.status_label.setText("내용 삭제됨")

        self._run_after_full_session_hydrated("내용 지우기", continue_clear_text)

    def _edit_subtitle(self):
        if self._is_runtime_mutation_blocked("자막 편집"):
            return

        def continue_edit() -> None:
            if not self.subtitles:
                self._show_toast("편집할 자막이 없습니다.", "warning")
                return

            items = self._build_subtitle_dialog_items()
            if not items:
                self._show_toast("편집할 자막이 없습니다.", "warning")
                return

            view_mod = _view_public()
            dialog = QDialog(self)
            dialog.setWindowTitle("자막 편집")
            dialog.setMinimumSize(760, 520)
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel("편집할 자막을 선택하세요:"))

            search_input = QLineEdit()
            search_input.setPlaceholderText("시간 또는 자막 내용을 검색하세요...")
            layout.addWidget(search_input)

            count_label = QLabel("")
            layout.addWidget(count_label)

            list_widget = QListWidget()
            list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            layout.addWidget(list_widget)

            layout.addWidget(QLabel("자막 내용:"))
            edit_text = QTextEdit()
            edit_text.setMaximumHeight(160)
            layout.addWidget(edit_text)

            more_btn = QPushButton("더 보기")
            layout.addWidget(more_btn)

            state = {
                "all_items": items,
                "filtered_items": list(items),
                "rendered_items": [],
                "page_size": Config.SUBTITLE_DIALOG_PAGE_SIZE,
                "count_label": count_label,
                "more_btn": more_btn,
            }

            def on_selection_changed():
                idx = list_widget.currentRow()
                rendered_items = state.get("rendered_items", [])
                if 0 <= idx < len(rendered_items):
                    edit_text.setText(rendered_items[idx].text)
                else:
                    edit_text.clear()

            def load_more():
                self._load_more_subtitle_dialog_items(list_widget, state)

            def on_filter_changed(text: str):
                self._apply_subtitle_dialog_filter(list_widget, state, text)

            list_widget.currentRowChanged.connect(on_selection_changed)
            more_btn.clicked.connect(load_more)
            search_input.textChanged.connect(on_filter_changed)

            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Save
                | QDialogButtonBox.StandardButton.Cancel
            )

            def save_edit():
                idx = list_widget.currentRow()
                rendered_items = state.get("rendered_items", [])
                if 0 <= idx < len(rendered_items):
                    source_index = rendered_items[idx].source_index
                    new_text = edit_text.toPlainText().strip()
                    if new_text:
                        with self.subtitle_lock:
                            if not (0 <= source_index < len(self.subtitles)):
                                view_mod.QMessageBox.warning(
                                    dialog, "알림", "선택한 자막을 찾을 수 없습니다."
                                )
                                return
                            entry = self.subtitles[source_index]
                            old_chars = entry.char_count
                            old_words = entry.word_count
                            entry.update_text(new_text)
                            self._cached_total_chars += entry.char_count - old_chars
                            self._cached_total_words += entry.word_count - old_words
                        self._refresh_text(force_full=True)
                        self._update_count_label()
                        self._mark_session_dirty()
                        self._invalidate_destructive_undo()
                        self._show_toast("자막이 수정되었습니다.", "success")
                        dialog.accept()
                    else:
                        view_mod.QMessageBox.warning(dialog, "알림", "자막 내용을 입력해주세요.")
                else:
                    view_mod.QMessageBox.warning(dialog, "알림", "편집할 자막을 선택해주세요.")

            buttons.accepted.connect(save_edit)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)

            self._load_more_subtitle_dialog_items(list_widget, state, reset=True)
            dialog.exec()

        self._run_after_full_session_hydrated("자막 편집", continue_edit)

    def _delete_subtitle(self):
        if self._is_runtime_mutation_blocked("자막 삭제"):
            return

        def continue_delete() -> None:
            if not self.subtitles:
                self._show_toast("삭제할 자막이 없습니다.", "warning")
                return

            items = self._build_subtitle_dialog_items()
            if not items:
                self._show_toast("삭제할 자막이 없습니다.", "warning")
                return

            view_mod = _view_public()
            dialog = QDialog(self)
            dialog.setWindowTitle("자막 삭제")
            dialog.setMinimumSize(760, 520)
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel("삭제할 자막을 선택하세요 (다중 선택 가능):"))

            search_input = QLineEdit()
            search_input.setPlaceholderText("시간 또는 자막 내용을 검색하세요...")
            layout.addWidget(search_input)

            count_label = QLabel("")
            layout.addWidget(count_label)

            list_widget = QListWidget()
            list_widget.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
            layout.addWidget(list_widget)

            more_btn = QPushButton("더 보기")
            layout.addWidget(more_btn)

            state = {
                "all_items": items,
                "filtered_items": list(items),
                "rendered_items": [],
                "page_size": Config.SUBTITLE_DIALOG_PAGE_SIZE,
                "count_label": count_label,
                "more_btn": more_btn,
            }

            def load_more():
                self._load_more_subtitle_dialog_items(list_widget, state)

            def on_filter_changed(text: str):
                self._apply_subtitle_dialog_filter(list_widget, state, text)

            more_btn.clicked.connect(load_more)
            search_input.textChanged.connect(on_filter_changed)

            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
            ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
            if ok_button is not None:
                ok_button.setText("삭제")

            def delete_selected():
                rendered_items = state.get("rendered_items", [])
                selected_rows = sorted({i.row() for i in list_widget.selectedIndexes()})
                if not selected_rows or not rendered_items:
                    view_mod.QMessageBox.warning(dialog, "알림", "삭제할 자막을 선택해주세요.")
                    return

                source_indexes = sorted(
                    {
                        rendered_items[row].source_index
                        for row in selected_rows
                        if 0 <= row < len(rendered_items)
                    },
                    reverse=True,
                )
                if not source_indexes:
                    view_mod.QMessageBox.warning(dialog, "알림", "삭제할 자막을 선택해주세요.")
                    return

                reply = view_mod.QMessageBox.question(
                    dialog,
                    "확인",
                    f"선택한 {len(source_indexes)}개의 자막을 삭제하시겠습니까?",
                    view_mod.QMessageBox.StandardButton.Yes
                    | view_mod.QMessageBox.StandardButton.No,
                )

                if reply == view_mod.QMessageBox.StandardButton.Yes:
                    self._store_destructive_undo_snapshot()
                    with self.subtitle_lock:
                        for row in source_indexes:
                            if not (0 <= row < len(self.subtitles)):
                                continue
                            entry = self.subtitles[row]
                            self._cached_total_chars -= entry.char_count
                            self._cached_total_words -= entry.word_count
                            del self.subtitles[row]
                    self._refresh_text(force_full=True)
                    self._update_count_label()
                    self._mark_session_dirty()
                    self._notify_destructive_undo_available()
                    self._show_toast(
                        f"{len(source_indexes)}개 자막이 삭제되었습니다.", "success"
                    )
                    dialog.accept()

            buttons.accepted.connect(delete_selected)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)

            self._load_more_subtitle_dialog_items(list_widget, state, reset=True)
            dialog.exec()

        self._run_after_full_session_hydrated("자막 삭제", continue_delete)
