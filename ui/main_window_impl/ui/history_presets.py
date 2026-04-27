# -*- coding: utf-8 -*-

from __future__ import annotations

from importlib import import_module

from ui.main_window_common import *
from ui.main_window_types import MainWindowHost


def _ui_public():
    return import_module("ui.main_window_ui")


class MainWindowUIHistoryPresetsMixin(MainWindowHost):
    def _load_url_history(self):
            """URL 히스토리 로드 - {url: tag} 형태"""
            try:
                if _ui_public().Path(Config.URL_HISTORY_FILE).exists():
                    with open(Config.URL_HISTORY_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        # dict 형태인지 확인 (새로운 형식)
                        if isinstance(data, dict):
                            return data
                        # 이전 list 형태면 dict로 변환
                        elif isinstance(data, list):
                            return {url: "" for url in data}
            except Exception as e:
                logger.warning(f"URL 히스토리 로드 오류: {e}")
                self._report_user_visible_warning(
                    f"URL 히스토리 로드 실패: {e}",
                    toast=False,
                )
            return {}


    def _save_url_history(self):
            """URL 히스토리 저장"""
            try:
                if not isinstance(self.url_history, dict):
                    self.url_history = {}
                _ui_public().utils.atomic_write_json(
                    Config.URL_HISTORY_FILE,
                    self.url_history,
                    ensure_ascii=False,
                    indent=2,
                )
            except Exception as e:
                logger.warning(f"URL 히스토리 저장 오류: {e}")
                self._report_user_visible_warning(f"URL 히스토리 저장 실패: {e}")


    def _add_to_history(self, url, tag=""):
            """URL 히스토리에 추가 (자동 태그 매칭)"""
            if not isinstance(self.url_history, dict):
                self.url_history = {}

            existing_tag = self.url_history.get(url, "")

            # 태그가 없으면 자동 감지
            if not tag:
                # 1. 이미 저장된 태그가 있는지 확인
                if existing_tag:
                    tag = existing_tag
                else:
                    # 2. 프리셋/약칭에서 매칭 확인
                    tag = self._autodetect_tag(url)

            if url in self.url_history:
                self.url_history.pop(url, None)
            self.url_history[url] = tag

            # 히스토리 크기 제한
            if len(self.url_history) > Config.MAX_URL_HISTORY:
                # 가장 오래된 항목 삭제 (dict는 삽입 순서 유지)
                oldest_key = next(iter(self.url_history))
                del self.url_history[oldest_key]

            self._save_url_history()
            self._refresh_url_combo()


    def _autodetect_tag(self, url):
            """URL을 기반으로 위원회 이름/약칭 자동 감지"""
            # 1. 정확한 URL 매칭 확인 (프리셋)
            for name, preset_url in self.committee_presets.items():
                if url == preset_url:
                    # 약칭이 있으면 약칭 사용 (더 짧고 보기 좋음)
                    for abbr, full_name in Config.COMMITTEE_ABBREVIATIONS.items():
                        if full_name == name:
                            return abbr
                    return name

            # 2. xcode 파라미터 매칭 (숫자 또는 문자열 xcode 모두 지원)
            import re

            match = re.search(r"xcode=([^&]+)", url)
            if match:
                xcode = match.group(1)
                # 프리셋에서 해당 xcode를 가진 URL 찾기
                for name, preset_url in self.committee_presets.items():
                    if f"xcode={xcode}" in preset_url:
                        # 약칭 리턴
                        for abbr, full_name in Config.COMMITTEE_ABBREVIATIONS.items():
                            if full_name == name:
                                return abbr
                        return name

            return ""


    def _refresh_url_combo(self):
            """URL 콤보박스 새로고침"""
            current_text = self.url_combo.currentText()
            self.url_combo.clear()

            for url, tag in self.url_history.items():
                if tag:
                    self.url_combo.addItem(f"[{tag}] {url}", url)
                else:
                    self.url_combo.addItem(url, url)

            # 기본 URL 추가
            if not self.url_history:
                self.url_combo.addItem("https://assembly.webcast.go.kr/main/player.asp")

            # 이전 텍스트 복원
            if current_text:
                self.url_combo.setCurrentText(current_text)


    def _get_current_url(self):
            """현재 선택된 URL 반환 (태그 제거)"""
            text = self.url_combo.currentText().strip()
            text_url = text
            if text.startswith("[") and "] " in text:
                text_url = text.split("] ", 1)[1].strip()

            data = self.url_combo.currentData()
            if data:
                data_url = str(data).strip()
                if text_url and text_url != data_url:
                    return text_url
                return data_url

            return text_url


    def _is_allowed_preset_host(self, host: str) -> bool:
            normalized_host = str(host or "").strip().lower()
            return normalized_host == "assembly.webcast.go.kr" or normalized_host.endswith(
                ".assembly.webcast.go.kr"
            )


    def _validate_preset_url(self, url: object) -> tuple[str | None, str | None]:
            from urllib.parse import urlsplit

            normalized_url = str(url or "").strip()
            if not normalized_url:
                return None, "프리셋 URL을 입력하세요."

            try:
                parsed = urlsplit(normalized_url)
            except Exception:
                return None, "올바른 프리셋 URL을 입력하세요."

            scheme = str(parsed.scheme or "").lower()
            if scheme not in ("http", "https"):
                return None, "프리셋 URL은 http:// 또는 https://만 허용됩니다."

            host = str(parsed.hostname or "").strip().lower()
            if not self._is_allowed_preset_host(host):
                return (
                    None,
                    "프리셋 URL은 assembly.webcast.go.kr 계열만 허용됩니다.",
                )

            return normalized_url, None


    def _coerce_preset_entry(
        self,
        name: object,
        url: object,
    ) -> tuple[tuple[str, str] | None, str | None]:
            normalized_name = str(name or "").strip()
            if not normalized_name:
                return None, "프리셋 이름이 비어 있습니다."

            normalized_url, error = self._validate_preset_url(url)
            if normalized_url is None:
                return None, error

            return (normalized_name, normalized_url), None


    def _edit_url_tag(self):
            """현재 URL의 태그 편집"""
            if self._is_runtime_mutation_blocked("URL 태그 편집"):
                return
            url = self._get_current_url()
            if not url or not url.startswith(("http://", "https://")):
                _ui_public().QMessageBox.warning(self, "알림", "태그를 지정할 URL을 먼저 선택하세요.")
                return

            current_tag = self.url_history.get(url, "")
            tag, ok = _ui_public().QInputDialog.getText(
                self,
                "URL 태그 설정",
                f"URL: {url[:50]}...\n\n태그 입력 (예: 본회의, 법사위, 상임위):",
                text=current_tag,
            )

            if ok:
                self._add_to_history(url, tag.strip())
                _ui_public().QMessageBox.information(
                    self,
                    "성공",
                    f"태그가 설정되었습니다: [{tag}]" if tag else "태그가 제거되었습니다.",
                )


    def _load_committee_presets(self):
            """프리셋 파일에서 로드 (없으면 기본값 사용)"""
            self.committee_presets = dict(Config.DEFAULT_COMMITTEE_PRESETS)
            self.custom_presets = {}

            try:
                if _ui_public().Path(Config.PRESET_FILE).exists():
                    with open(Config.PRESET_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if "presets" in data:
                            self.committee_presets.update(data["presets"])
                        if "custom" in data:
                            self.custom_presets = data["custom"]
            except Exception as e:
                logger.warning(f"프리셋 로드 오류: {e}")
                self._report_user_visible_warning(
                    f"프리셋 로드 실패: {e}",
                    toast=False,
                )


    def _save_committee_presets(self):
            """프리셋을 파일에 저장"""
            try:
                data = {"presets": self.committee_presets, "custom": self.custom_presets}
                _ui_public().utils.atomic_write_json(
                    Config.PRESET_FILE,
                    data,
                    ensure_ascii=False,
                    indent=2,
                )
            except Exception as e:
                logger.warning(f"프리셋 저장 오류: {e}")
                self._report_user_visible_warning(f"프리셋 저장 실패: {e}")


    def _build_preset_menu(self):
            """프리셋 메뉴 구성"""
            self.preset_menu.clear()

            # 기본 상임위원회
            for name, url in self.committee_presets.items():
                action = QAction(name, self)
                action.setData(url)
                action.triggered.connect(
                    lambda checked, u=url, n=name: self._select_preset(u, n)
                )
                self.preset_menu.addAction(action)

            # 사용자 정의 프리셋이 있으면 구분선 추가
            if self.custom_presets:
                self.preset_menu.addSeparator()
                section_action = QAction("── 사용자 정의 ──", self)
                section_action.setEnabled(False)
                self.preset_menu.addAction(section_action)

                for name, url in self.custom_presets.items():
                    action = QAction(f"⭐ {name}", self)
                    action.setData(url)
                    action.triggered.connect(
                        lambda checked, u=url, n=name: self._select_preset(u, n)
                    )
                    self.preset_menu.addAction(action)

            # 관리 메뉴
            self.preset_menu.addSeparator()
            add_action = QAction("➕ 프리셋 추가...", self)
            add_action.triggered.connect(self._add_custom_preset)
            self.preset_menu.addAction(add_action)

            edit_action = QAction("✏️ 프리셋 관리...", self)
            edit_action.triggered.connect(self._manage_presets)
            self.preset_menu.addAction(edit_action)

            self.preset_menu.addSeparator()
            export_action = QAction("📤 프리셋 내보내기...", self)
            export_action.triggered.connect(self._export_presets)
            self.preset_menu.addAction(export_action)

            import_action = QAction("📥 프리셋 가져오기...", self)
            import_action.triggered.connect(self._import_presets)
            self.preset_menu.addAction(import_action)


    def _select_preset(self, url, name):
            """프리셋 선택 시 URL 설정"""
            if self._is_runtime_mutation_blocked("상임위 프리셋 변경"):
                return
            self.url_combo.setCurrentText(url)
            self._show_toast(f"'{name}' 선택됨", "success", 1500)


    def _add_custom_preset(self):
            """사용자 정의 프리셋 추가"""
            name, ok = _ui_public().QInputDialog.getText(
                self, "프리셋 추가", "프리셋 이름을 입력하세요:"
            )
            if not ok or not name.strip():
                return

            name = name.strip()
            current_url = self._get_current_url()

            url, ok = _ui_public().QInputDialog.getText(
                self,
                "프리셋 URL",
                f"'{name}' 프리셋의 URL을 입력하세요:",
                text=current_url if current_url.startswith("http") else Config.DEFAULT_URL,
            )

            if ok and url.strip():
                normalized_url, error = self._validate_preset_url(url)
                if normalized_url is None:
                    _ui_public().QMessageBox.warning(
                        self,
                        "프리셋 URL 오류",
                        error or "올바른 프리셋 URL을 입력하세요.",
                    )
                    return
                self.custom_presets[name] = normalized_url
                self._save_committee_presets()
                self._build_preset_menu()
                self._show_toast(f"프리셋 '{name}' 추가됨", "success")


    def _manage_presets(self):
            """프리셋 관리 대화상자"""
            if not self.custom_presets:
                _ui_public().QMessageBox.information(
                    self,
                    "프리셋 관리",
                    "사용자 정의 프리셋이 없습니다.\n\n"
                    "'➕ 프리셋 추가'를 통해 새 프리셋을 추가하세요.",
                )
                return

            # 작업 선택
            names = list(self.custom_presets.keys())
            actions = ["수정", "삭제"]
            action, ok = _ui_public().QInputDialog.getItem(
                self, "프리셋 관리", "작업을 선택하세요:", actions, 0, False
            )

            if not ok:
                return

            # 프리셋 선택
            name, ok = _ui_public().QInputDialog.getItem(
                self,
                f"프리셋 {action}",
                f"{action}할 프리셋을 선택하세요:",
                names,
                0,
                False,
            )

            if not ok or not name:
                return

            if action == "삭제":
                reply = _ui_public().QMessageBox.question(
                    self,
                    "확인",
                    f"'{name}' 프리셋을 삭제하시겠습니까?",
                    _ui_public().QMessageBox.StandardButton.Yes | _ui_public().QMessageBox.StandardButton.No,
                )
                if reply == _ui_public().QMessageBox.StandardButton.Yes:
                    del self.custom_presets[name]
                    self._save_committee_presets()
                    self._build_preset_menu()
                    self._show_toast(f"프리셋 '{name}' 삭제됨", "warning")

            elif action == "수정":
                # 이름 수정
                new_name, ok = _ui_public().QInputDialog.getText(
                    self, "프리셋 이름 수정", f"'{name}' 프리셋의 새 이름:", text=name
                )
                if not ok:
                    return

                # URL 수정
                current_url = self.custom_presets[name]
                new_url, ok = _ui_public().QInputDialog.getText(
                    self, "프리셋 URL 수정", f"'{new_name}' 프리셋의 URL:", text=current_url
                )
                if not ok:
                    return

                normalized_name = new_name.strip()
                if not normalized_name:
                    _ui_public().QMessageBox.warning(self, "프리셋 이름 오류", "프리셋 이름을 입력하세요.")
                    return

                normalized_url, error = self._validate_preset_url(new_url)
                if normalized_url is None:
                    _ui_public().QMessageBox.warning(
                        self,
                        "프리셋 URL 오류",
                        error or "올바른 프리셋 URL을 입력하세요.",
                    )
                    return

                # 기존 프리셋 삭제 후 새로 추가 (이름이 변경되었을 수 있으므로)
                del self.custom_presets[name]
                self.custom_presets[normalized_name] = normalized_url
                self._save_committee_presets()
                self._build_preset_menu()
                self._show_toast(f"프리셋 '{normalized_name}' 수정됨", "success")


    def _export_presets(self):
            """프리셋을 파일로 내보내기"""
            filename = f"presets_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            path, _ = _ui_public().QFileDialog.getSaveFileName(
                self, "프리셋 내보내기", filename, "JSON 파일 (*.json)"
            )

            if path:
                try:
                    data = {
                        "version": Config.VERSION,
                        "exported": datetime.now().isoformat(),
                        "committee": self.committee_presets,
                        "custom": self.custom_presets,
                    }
                    _ui_public().utils.atomic_write_json(
                        path,
                        data,
                        ensure_ascii=False,
                        indent=2,
                    )

                    total = len(self.committee_presets) + len(self.custom_presets)
                    self._show_toast(f"프리셋 {total}개 내보내기 완료!", "success")
                    logger.info(f"프리셋 내보내기 완료: {path}")
                except Exception as e:
                    _ui_public().QMessageBox.critical(self, "오류", f"프리셋 내보내기 실패: {e}")


    def _import_presets(self):
            """파일에서 프리셋 가져오기"""
            path, _ = _ui_public().QFileDialog.getOpenFileName(
                self, "프리셋 가져오기", "", "JSON 파일 (*.json)"
            )

            if path:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    if not isinstance(data, dict):
                        _ui_public().QMessageBox.warning(self, "오류", "프리셋 JSON 루트는 객체여야 합니다.")
                        return

                    imported_count = 0
                    skipped_count = 0

                    if "committee" in data and isinstance(data["committee"], dict):
                        for name, url in data["committee"].items():
                            preset_entry, _error = self._coerce_preset_entry(name, url)
                            if preset_entry is None:
                                skipped_count += 1
                                continue
                            normalized_name, normalized_url = preset_entry
                            if self.committee_presets.get(normalized_name) != normalized_url:
                                self.committee_presets[normalized_name] = normalized_url
                                imported_count += 1

                    # 사용자 정의 프리셋 가져오기 (기존 것에 추가)
                    if "custom" in data and isinstance(data["custom"], dict):
                        for name, url in data["custom"].items():
                            preset_entry, _error = self._coerce_preset_entry(name, url)
                            if preset_entry is None:
                                skipped_count += 1
                                continue
                            normalized_name, normalized_url = preset_entry
                            if self.custom_presets.get(normalized_name) != normalized_url:
                                self.custom_presets[normalized_name] = normalized_url
                                imported_count += 1

                    if imported_count > 0:
                        self._save_committee_presets()
                        self._build_preset_menu()
                        message = f"프리셋 {imported_count}개 가져오기 완료!"
                        if skipped_count > 0:
                            message += f" (제외 {skipped_count}개)"
                        self._show_toast(message, "success")
                    elif skipped_count > 0:
                        self._show_toast(
                            f"유효한 프리셋이 없습니다. (제외 {skipped_count}개)",
                            "warning",
                        )
                    else:
                        self._show_toast("가져올 새 프리셋이 없습니다", "info")

                    logger.info(
                        f"프리셋 가져오기 완료: {path}, {imported_count}개, 제외 {skipped_count}개"
                    )
                except json.JSONDecodeError:
                    _ui_public().QMessageBox.warning(self, "오류", "잘못된 JSON 파일 형식입니다.")
                except Exception as e:
                    _ui_public().QMessageBox.critical(self, "오류", f"프리셋 가져오기 실패: {e}")


