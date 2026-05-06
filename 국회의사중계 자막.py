# -*- coding: utf-8 -*-
"""
국회 의사중계 자막 추출기
- 버전 표기는 README.md 기준
- 참조 코드 기반 안정성 강화
- PyQt6 모던 UI
- 추가 기능: 자동저장, 실시간 저장, 검색 필터, URL 히스토리, SRT/VTT 내보내기, 통계, 하이라이트, 세션 저장
"""

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, cast

# HiDPI 지원 - PyQt6 임포트 전에 설정 필요
os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '1'
os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '1'


_CLI_CONSOLE_ATTACHED = False


def _ensure_cli_console_output() -> None:
    global _CLI_CONSOLE_ATTACHED
    if _CLI_CONSOLE_ATTACHED or os.name != "nt" or not bool(getattr(sys, "frozen", False)):
        return
    _CLI_CONSOLE_ATTACHED = True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        attached = bool(kernel32.AttachConsole(-1))
        already_attached = int(kernel32.GetLastError()) == 5
        if attached or already_attached:
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
            sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
    except Exception:
        pass


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="국회 의사중계 자막 추출기")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="GUI 없이 import/resource/storage smoke 검증을 실행합니다.",
    )
    parser.add_argument(
        "--smoke-storage-preflight",
        action="store_true",
        help="GUI 없이 저장소 preflight만 실행합니다.",
    )
    parser.add_argument(
        "--smoke-storage-dir",
        default="",
        help="smoke preflight에 사용할 임시 저장소 루트입니다.",
    )
    return parser.parse_args(argv)


def _print_json_line(payload: dict[str, object]) -> None:
    _ensure_cli_console_output()
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


def _run_storage_preflight_for_cli(storage_dir: str = "") -> tuple[bool, str, dict[str, str]]:
    from core.config import Config, run_storage_preflight

    storage_dir = str(storage_dir or "").strip()
    if storage_dir:
        root = Path(storage_dir).resolve()
        ok, error = run_storage_preflight(
            root,
            database_path=root / "subtitle_history.db",
            preset_file=root / "committee_presets.json",
            url_history_file=root / "url_history.json",
            recovery_state_file=root / "session_recovery.json",
        )
        return ok, error, {
            "storage_dir": str(root),
            "storage_mode": "override",
        }

    ok, error = Config.run_storage_preflight()
    return ok, error, {
        "storage_dir": str(Config.STORAGE_DIR),
        "storage_mode": str(Config.STORAGE_MODE),
    }


def _run_smoke(args: argparse.Namespace) -> int:
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: F401
        from PyQt6.QtGui import QFont  # noqa: F401
        from selenium import webdriver  # noqa: F401

        from core.config import Config
        from core.live_capture import reconcile_live_capture
        from ui.main_window import MainWindow
    except ImportError as exc:
        _print_json_line(
            {
                "ok": False,
                "kind": "smoke",
                "error_type": "dependency_import",
                "error": str(exc),
            }
        )
        return 1

    ok, error, storage_payload = _run_storage_preflight_for_cli(args.smoke_storage_dir)
    readme_path = Path(Config.get_resource_path("README.md"))
    hwpx_assets_path = Path(Config.get_resource_path("assets/hwpx"))
    resource_ok = readme_path.exists() and hwpx_assets_path.exists()
    imports_ok = MainWindow.__name__ == "MainWindow" and callable(reconcile_live_capture)
    smoke_ok = bool(ok and resource_ok and imports_ok)
    _print_json_line(
        {
            "ok": smoke_ok,
            "kind": "smoke",
            "version": Config.VERSION,
            "storage": storage_payload,
            "storage_preflight": ok,
            "resource_ok": resource_ok,
            "imports_ok": imports_ok,
            "error": error,
        }
    )
    return 0 if smoke_ok else 2


def _run_storage_preflight_smoke(args: argparse.Namespace) -> int:
    try:
        from core.config import Config
    except ImportError as exc:
        _print_json_line(
            {
                "ok": False,
                "kind": "storage_preflight",
                "error_type": "dependency_import",
                "error": str(exc),
            }
        )
        return 1

    ok, error, storage_payload = _run_storage_preflight_for_cli(args.smoke_storage_dir)
    _print_json_line(
        {
            "ok": ok,
            "kind": "storage_preflight",
            "version": Config.VERSION,
            "storage": storage_payload,
            "error": error,
        }
    )
    return 0 if ok else 2


def main(argv: list[str] | None = None) -> int:
    """메인 함수 - 예외 처리 강화"""
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.smoke:
        return _run_smoke(args)
    if args.smoke_storage_preflight:
        return _run_storage_preflight_smoke(args)

    try:
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            from PyQt6.QtGui import QFont
        except ImportError:
            print("PyQt6 필요: pip install PyQt6")
            return 1

        try:
            from selenium import webdriver  # noqa: F401
        except ImportError:
            print("selenium 필요: pip install selenium")
            return 1

        from core.config import Config
        from core.logging_utils import ensure_file_logging, logger
        from ui.main_window import MainWindow

        # IDLE 호환성을 위한 이벤트 루프 체크
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        if not isinstance(app, QApplication):
            raise RuntimeError("QApplication 인스턴스를 초기화할 수 없습니다.")

        preflight_ok, preflight_error = Config.run_storage_preflight()
        if not preflight_ok:
            QMessageBox.critical(
                None,
                "저장소 초기화 실패",
                (
                    "필수 저장 경로를 준비하지 못해 프로그램을 시작할 수 없습니다.\n\n"
                    f"저장 모드: {Config.STORAGE_MODE}\n"
                    f"저장 루트: {Config.STORAGE_DIR}\n\n"
                    f"{preflight_error}"
                ),
            )
            return 1
        ensure_file_logging()

        app.setStyle("Fusion")
        app.setFont(QFont("맑은 고딕", 10))

        window = cast(Any, MainWindow)()
        window.show()

        # IDLE에서 실행 시 exec() 대신 processEvents 사용
        if hasattr(sys, 'ps1'):  # IDLE/인터프리터 환경
            while window.isVisible():
                app.processEvents()
                time.sleep(0.01)
            return 0
        else:
            return int(app.exec())

    except Exception as e:
        from PyQt6.QtWidgets import QMessageBox
        from core.logging_utils import logger

        logger.exception(f"프로그램 오류: {e}")
        QMessageBox.critical(None, "오류", f"프로그램 실행 중 오류 발생:\n{e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
