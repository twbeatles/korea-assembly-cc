# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path
from uuid import uuid4

from core.update_installer import (
    consume_update_result,
    launch_update_helper,
    prepare_staged_update,
    resolve_update_staging_root,
    stream_update_artifact,
    update_result_path,
)
from core.update_manifest import (
    NoUpdateAvailableError,
    ReleaseManifest,
    download_release_manifest,
    verify_release_manifest,
)
from ui.main_window_common import *
from ui.main_window_types import MainWindowHost


class MainWindowUIHelpMixin(MainWindowHost):
    def _open_latest_release_page(self) -> None:
        webbrowser.open(Config.UPDATE_RELEASES_URL)

    def _set_update_state(self, state: str) -> None:
        self._update_state = str(state or "idle")
        self._update_operation_in_progress = self._update_state in {
            "checking",
            "downloading",
            "awaiting_confirmation",
            "applying",
        }

    def _discard_staged_update(self, staged: Path) -> None:
        try:
            staged.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not remove staged update %s: %s", staged, exc)

    def _notify_pending_update_result(self) -> None:
        target = Path(sys.executable).resolve()
        staging_root = resolve_update_staging_root(
            storage_root=Config.STORAGE_DIR,
            install_dir=target.parent,
            storage_mode=Config.STORAGE_MODE,
        )
        result = consume_update_result(update_result_path(staging_root))
        if not result:
            return
        status = str(result.get("status", "failed"))
        error = str(result.get("error", "") or "")
        if status == "applied":
            self._set_status("이전 실행에서 업데이트를 완료했습니다.", "success")
            self._show_toast("업데이트가 완료되었습니다.", "success", 3500)
            return
        message = "업데이트 후 원래 버전으로 복원했습니다." if status == "rolled_back" else "업데이트를 적용하지 못했습니다."
        if error:
            message = f"{message}\n\n오류: {error}"
        self._set_status("업데이트 적용 실패", "warning")
        dialog = QMessageBox(self)
        dialog.setWindowTitle("업데이트 결과")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(f"{message}\n\n최신 버전은 릴리스 페이지에서 직접 받을 수 있습니다.")
        release_button = dialog.addButton("릴리스 페이지 열기", QMessageBox.ButtonRole.ActionRole)
        dialog.addButton("닫기", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is release_button:
            self._open_latest_release_page()

    def _check_for_updates(self, interactive: bool = True) -> None:
        if interactive and self._is_runtime_mutation_blocked("업데이트 확인"):
            return
        if bool(getattr(self, "_update_operation_in_progress", False)):
            if interactive:
                self._set_status("업데이트 작업이 이미 진행 중입니다.", "info")
            return
        manifest_url = str(Config.UPDATE_MANIFEST_URL or "").strip()
        public_key = str(Config.UPDATE_PUBLIC_KEY_B64 or "").strip()
        if not manifest_url or not public_key:
            if interactive:
                QMessageBox.information(
                    self,
                    "업데이트",
                    "서명된 업데이트 채널이 이 빌드에 설정되지 않았습니다.",
                )
            else:
                logger.info("Startup update check skipped: update channel is not configured")
            return
        if interactive:
            self._set_status("업데이트 확인 중...", "running")
        self._set_update_state("checking")

        def check_worker() -> None:
            try:
                document = download_release_manifest(manifest_url)
                manifest = verify_release_manifest(
                    document,
                    public_key=public_key,
                    current_version=Config.VERSION,
                )
                self._emit_control_message(
                    "update_manifest_ready",
                    {"manifest": manifest, "interactive": interactive},
                )
            except NoUpdateAvailableError:
                self._emit_control_message(
                    "update_not_available", {"interactive": interactive}
                )
            except Exception as exc:
                self._emit_control_message(
                    "update_check_failed",
                    {"error": str(exc), "interactive": interactive},
                )

        if not self._start_background_thread(check_worker, "UpdateCheckWorker"):
            self._set_update_state("idle")
            if interactive:
                self._set_status("업데이트 확인 시작 실패", "warning")
            else:
                logger.warning("Startup update check could not start")

    def _handle_update_manifest_ready(
        self, manifest: ReleaseManifest, *, interactive: bool = True
    ) -> None:
        if not isinstance(manifest, ReleaseManifest):
            self._set_update_state("idle")
            self._handle_update_failure("업데이트 응답 형식이 올바르지 않습니다.", interactive)
            return
        if not bool(getattr(sys, "frozen", False)):
            self._set_update_state("idle")
            if interactive:
                QMessageBox.information(
                    self,
                    "업데이트",
                    "개발 실행에서는 자동 설치를 사용할 수 없습니다.",
                )
            return
        if not interactive and (
            str(getattr(self, "_last_notified_update_version", "")) == manifest.version
        ):
            self._set_update_state("idle")
            return
        if self._is_runtime_mutation_blocked("업데이트 설치"):
            self._set_update_state("deferred")
            self._set_status("추출 중인 동안 업데이트 설치를 보류합니다.", "info")
            return
        self._last_notified_update_version = manifest.version

        message = (
            f"새 버전 {manifest.version}이 있습니다.\n\n"
            f"현재 버전: {Config.VERSION}\n"
            f"최신 버전: {manifest.version}"
        )
        dialog = QMessageBox(self)
        dialog.setWindowTitle("업데이트 발견")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText(message)
        update_button = dialog.addButton("업데이트", QMessageBox.ButtonRole.AcceptRole)
        release_button = dialog.addButton(
            "릴리스 페이지 보기", QMessageBox.ButtonRole.ActionRole
        )
        dialog.addButton("나중에", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is release_button:
            self._open_latest_release_page()
            self._set_update_state("idle")
            self._set_status("릴리스 페이지를 열었습니다.", "info")
            return
        if dialog.clickedButton() is not update_button:
            self._set_update_state("idle")
            self._set_status("업데이트 다운로드를 나중에 진행합니다.", "info")
            return

        def start_download() -> None:
            if self._is_runtime_mutation_blocked("업데이트 설치"):
                self._set_update_state("deferred")
                self._set_status("추출 중인 동안 업데이트 설치를 보류합니다.", "info")
                return
            self._set_update_state("downloading")
            self._set_status(f"업데이트 {manifest.version} 다운로드 중...", "running")

            def download_worker() -> None:
                try:
                    target = Path(sys.executable).resolve()
                    staging_root = resolve_update_staging_root(
                        storage_root=Config.STORAGE_DIR,
                        install_dir=target.parent,
                        storage_mode=Config.STORAGE_MODE,
                    )
                    staged = prepare_staged_update(
                        manifest,
                        chunks=stream_update_artifact(manifest),
                        staging_root=staging_root,
                        approve=lambda _manifest, _path: True,
                    )
                    if staged is None:
                        return
                    backup = target.with_name(
                        f"{target.name}.v{Config.VERSION}.{uuid4().hex[:8]}.bak"
                    )
                    result_file = update_result_path(staging_root)
                    self._emit_control_message(
                        "update_install_ready",
                        {
                            "target": str(target),
                            "staged": str(staged),
                            "backup": str(backup),
                            "version": manifest.version,
                            "sha256": manifest.artifact_sha256,
                            "size": manifest.artifact_size,
                            "interactive": interactive,
                            "result_file": str(result_file),
                        },
                    )
                except Exception as exc:
                    self._emit_control_message(
                        "update_install_failed", {"error": str(exc), "interactive": interactive}
                    )

            if not self._start_background_thread(
                download_worker, "UpdateDownloadWorker"
            ):
                self._set_update_state("idle")
                self._set_status("업데이트 다운로드 시작 실패", "warning")

        if not self._run_after_dirty_session_action("업데이트 설치", start_download):
            self._set_update_state("idle")

    def _handle_update_not_available(self, interactive: bool) -> None:
        self._set_update_state("idle")
        if not interactive:
            logger.info("Update check completed: current version is latest")
            return
        self._set_status("현재 최신 버전을 사용 중입니다.", "success")
        QMessageBox.information(self, "업데이트", "현재 최신 버전을 사용 중입니다.")

    def _handle_update_failure(self, error: str, interactive: bool) -> None:
        self._set_update_state("idle")
        if not interactive:
            logger.info("Startup update check failed: %s", error)
            return
        self._set_status(f"업데이트 실패: {error}", "error")
        dialog = QMessageBox(self)
        dialog.setWindowTitle("업데이트 실패")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(
            "자동 업데이트를 완료하지 못했습니다.\n\n"
            f"오류: {error}\n\n"
            "최신 버전은 GitHub 릴리스 페이지에서 직접 받을 수 있습니다."
        )
        release_button = dialog.addButton(
            "릴리스 페이지 열기", QMessageBox.ButtonRole.ActionRole
        )
        dialog.addButton("닫기", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is release_button:
            self._open_latest_release_page()

    def _handle_update_install_ready(self, payload: dict[str, object]) -> None:
        staged_value = payload.get("staged")
        target_value = payload.get("target")
        backup_value = payload.get("backup")
        sha256_value = payload.get("sha256")
        size_value = payload.get("size")
        result_file_value = payload.get("result_file")
        interactive = bool(payload.get("interactive", True))
        if (
            not isinstance(staged_value, str)
            or not staged_value
            or not isinstance(target_value, str)
            or not target_value
            or not isinstance(backup_value, str)
            or not backup_value
            or not isinstance(sha256_value, str)
            or len(sha256_value) != 64
            or not isinstance(size_value, int)
            or size_value <= 0
            or not isinstance(result_file_value, str)
            or not result_file_value
        ):
            self._handle_update_failure("업데이트 설치 정보가 올바르지 않습니다.", interactive)
            return
        staged = Path(staged_value).resolve()
        if self._is_runtime_mutation_blocked("업데이트 설치"):
            self._discard_staged_update(staged)
            self._set_update_state("deferred")
            self._set_status("추출 중이라 다운로드한 업데이트 설치를 보류했습니다. 중지 후 다시 확인하세요.", "info")
            return
        self._set_update_state("awaiting_confirmation")
        reply = QMessageBox.question(
            self,
            "업데이트 검증 완료",
            f"업데이트 {payload.get('version', '')}의 서명과 파일 무결성을 "
            "확인했습니다. 지금 설치하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self._discard_staged_update(staged)
            self._set_update_state("idle")
            self._set_status("업데이트 설치 취소", "info")
            return
        try:
            launch_update_helper(
                target=target_value,
                staged=staged,
                backup=backup_value,
                parent_pid=os.getpid(),
                expected_sha256=sha256_value,
                expected_size=size_value,
                result_file=result_file_value,
            )
        except Exception as exc:
            self._discard_staged_update(staged)
            self._handle_update_failure(f"업데이트 설치 시작 실패: {exc}", interactive)
            return
        self._set_update_state("applying")
        self._set_status(
            f"업데이트 {payload.get('version', '')} 설치를 위해 종료합니다.",
            "success",
        )
        QApplication.quit()

    def _show_guide(self):
            """사용법 가이드 표시"""
            guide = """
    <h2>🏛️ 사용법 가이드</h2>

    <h3>📋 기본 사용법</h3>
    <ol>
    <li><b>URL 입력</b> - 국회 의사중계 페이지 URL을 입력합니다</li>
    <li><b>선택자 확인</b> - 기본값을 사용하거나 수정합니다</li>
    <li><b>옵션 설정</b>
        <ul>
        <li>자동 스크롤: 새 자막 자동 따라가기</li>
        <li>실시간 저장: 자막 실시간 파일 저장 (추출 시작 전 설정)</li>
        <li>헤드리스 모드: 브라우저 창 숨기고 실행 (추출 시작 전 설정)</li>
        </ul>
    </li>
    <li><b>시작</b> 버튼 클릭 (또는 F5)</li>
    <li>자막 추출 완료 후 <b>파일 저장</b></li>
    </ol>

    <h3>⌨️ 주요 단축키</h3>
    <table>
    <tr><td><b>F5</b></td><td>시작</td></tr>
    <tr><td><b>Escape</b></td><td>검색창 닫기 / 추출 중지</td></tr>
    <tr><td><b>Ctrl+F</b></td><td>검색</td></tr>
    <tr><td><b>F3</b></td><td>다음 검색</td></tr>
    <tr><td><b>Ctrl+T</b></td><td>테마 전환</td></tr>
    <tr><td><b>Ctrl+S</b></td><td>TXT 저장</td></tr>
    <tr><td><b>Ctrl+Shift+C</b></td><td>전체 자막 복사</td></tr>
    </table>
    """
            msg = QMessageBox(self)
            msg.setWindowTitle("사용법 가이드")
            msg.setTextFormat(Qt.TextFormat.RichText)
            msg.setText(guide)
            msg.setIcon(QMessageBox.Icon.Information)
            msg.exec()


    def _show_shortcuts(self):
            """키보드 단축키 목록 표시"""
            shortcuts = """
    <h2>⌨️ 키보드 단축키</h2>

    <h3>📋 기본 조작</h3>
    <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
    <tr style="background-color: #f0f0f0;"><th>단축키</th><th>기능</th></tr>
    <tr><td><b>F5</b></td><td>추출 시작</td></tr>
    <tr><td><b>Escape</b></td><td>검색창 닫기 / 추출 중지</td></tr>
    <tr><td><b>Ctrl+Q</b></td><td>프로그램 종료</td></tr>
    </table>

    <h3>🔍 검색 및 편집</h3>
    <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
    <tr style="background-color: #f0f0f0;"><th>단축키</th><th>기능</th></tr>
    <tr><td><b>Ctrl+F</b></td><td>검색창 열기</td></tr>
    <tr><td><b>F3</b></td><td>다음 검색 결과</td></tr>
    <tr><td><b>Shift+F3</b></td><td>이전 검색 결과</td></tr>
    <tr><td><b>Ctrl+E</b></td><td>자막 편집</td></tr>
    <tr><td><b>Delete</b></td><td>자막 삭제</td></tr>
    <tr><td><b>Ctrl+Shift+C</b></td><td>전체 자막 복사</td></tr>
    <tr><td><b>Ctrl+C</b></td><td>선택한 텍스트 복사</td></tr>
    </table>

    <h3>💾 저장</h3>
    <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
    <tr style="background-color: #f0f0f0;"><th>단축키</th><th>기능</th></tr>
    <tr><td><b>Ctrl+S</b></td><td>TXT 저장</td></tr>
    <tr><td><b>Ctrl+Shift+S</b></td><td>세션 저장</td></tr>
    <tr><td><b>Ctrl+O</b></td><td>세션 불러오기</td></tr>
    </table>

    <h3>🎨 보기</h3>
    <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
    <tr style="background-color: #f0f0f0;"><th>단축키</th><th>기능</th></tr>
    <tr><td><b>Ctrl+T</b></td><td>테마 전환</td></tr>
    <tr><td><b>Ctrl++</b></td><td>글자 크기 키우기</td></tr>
    <tr><td><b>Ctrl+-</b></td><td>글자 크기 줄이기</td></tr>
    <tr><td><b>F1</b></td><td>사용법 가이드</td></tr>
    </table>
    """
            msg = QMessageBox(self)
            msg.setWindowTitle("키보드 단축키")
            msg.setTextFormat(Qt.TextFormat.RichText)
            msg.setText(shortcuts)
            msg.setIcon(QMessageBox.Icon.Information)
            msg.exec()


    def _show_features(self):
            """기능 소개 표시"""
            features = """
    <h2>✨ 기능 소개</h2>

    <h3>🎯 실시간 자막 추출</h3>
    <p>국회 의사중계 웹사이트의 AI 자막을 실시간으로 캡처합니다.<br>
    3초 동안 자막이 변경되지 않으면 자동으로 확정됩니다.</p>

    <h3>💾 다양한 저장 형식</h3>
    <ul>
    <li><b>TXT</b> - 일반 텍스트</li>
    <li><b>SRT</b> - 자막 파일 형식</li>
    <li><b>VTT</b> - WebVTT 자막 형식</li>
    <li><b>DOCX</b> - Word 문서</li>
    <li><b>HWPX</b> - 한글 문서 (기본 포맷)</li>
    </ul>

    <h3>🔍 검색 및 하이라이트</h3>
    <ul>
    <li><b>실시간 검색</b> - Ctrl+F로 자막 내 텍스트 검색</li>
    <li><b>키워드 하이라이트</b> - 특정 단어 강조</li>
    </ul>

    <h3>⚙️ 헤드리스 모드 (인터넷창 숨김)</h3>
    <p>브라우저 창을 숨기고 백그라운드에서 실행합니다.<br>
    자막 추출 중 다른 작업을 할 수 있으며, 실행 중에는 변경할 수 없습니다.</p>

    <h3>📊 통계 패널</h3>
    <p>실행 시간, 글자 수, 공백 기준 단어 수, 분당 글자 수를 표시합니다.</p>
    """
            msg = QMessageBox(self)
            msg.setWindowTitle("기능 소개")
            msg.setTextFormat(Qt.TextFormat.RichText)
            msg.setText(features)
            msg.setIcon(QMessageBox.Icon.Information)
            msg.exec()


    def _show_about(self):
            """프로그램 정보 표시"""
            about = f"""
    <h2>🏛️ 국회 의사중계 자막 추출기</h2>
    <p><b>버전:</b> {Config.VERSION}</p>
    <p><b>설명:</b> 국회 의사중계 웹사이트에서 실시간 AI 자막을<br>
    자동으로 추출하고 저장하는 프로그램입니다.</p>

    <h3>📦 필요 라이브러리</h3>
    <ul>
    <li>PyQt6</li>
    <li>selenium</li>
    <li>python-docx (DOCX 저장용)</li>
    </ul>

    <p><b>© 2024-2026</b></p>
    """
            msg = QMessageBox(self)
            msg.setWindowTitle("정보")
            msg.setTextFormat(Qt.TextFormat.RichText)
            msg.setText(about)
            msg.setIcon(QMessageBox.Icon.Information)
            msg.exec()


    def _toggle_top_header(self):
            """상단 영역(헤더/툴바) 표시/숨김 토글"""
            if self.top_header_container.isVisible():
                # 접기: 헤더 숨김 & 설정 그룹 접기
                self.top_header_container.hide()
                self.settings_group.set_collapsed(True)
                self.toggle_header_btn.setText("🔽 상단 펼치기")
            else:
                # 펼치기: 헤더 보임 & 설정 그룹 펼치기
                self.top_header_container.show()
                self.settings_group.set_collapsed(False)
                self.toggle_header_btn.setText("🔼 상단 접기")
