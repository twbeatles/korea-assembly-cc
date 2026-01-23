# -*- coding: utf-8 -*-
"""
국회 의사중계 자막 추출기 v16.8
- 참조 코드 기반 안정성 강화
- PyQt6 모던 UI
- 추가 기능: 자동저장, 실시간 저장, 검색 필터, URL 히스토리, SRT/VTT 내보내기, 통계, 하이라이트, 세션 저장
- v16.1: 생중계 xcgcd 자동 감지 기능 추가
- v16.2: 코드 정리 개선 (기존 URL 복구, xcgcd 유효성 검증 자동 필터 강화, 헤드리스 사용 안정성)
- v16.3: 스레드 안정성 강화, 하이라이트 설정 메뉴 및 종료 처리 개선
- v16.6: 연결 상태 모니터링/자동 재연결/자동 파일명/DB/자막 병합
- v16.7: live_list 기반 URL 감지 강화 + 생중계 목록 선택 UI
- v16.8: 상임위원회 xcode 최신화 + 성능 최적화(정규식/통계 캐시)
"""

import os
import sys
import time

# HiDPI 지원 - PyQt6 임포트 전에 설정 필요
os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '1'
os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '1'

try:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from PyQt6.QtGui import QFont
except ImportError:
    print("PyQt6 필요: pip install PyQt6")
    sys.exit(1)

try:
    from selenium import webdriver
except ImportError:
    print("selenium 필요: pip install selenium")
    sys.exit(1)

from core.logging_utils import logger
from ui.main_window import MainWindow


def main():
    """메인 함수 - 예외 처리 강화"""
    try:
        # IDLE 호환성을 위한 이벤트 루프 체크
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)

        app.setStyle("Fusion")
        app.setFont(QFont("맑은 고딕", 10))

        window = MainWindow()
        window.show()

        # IDLE에서 실행 시 exec() 대신 processEvents 사용
        if hasattr(sys, 'ps1'):  # IDLE/인터프리터 환경
            while window.isVisible():
                app.processEvents()
                time.sleep(0.01)
        else:
            sys.exit(app.exec())

    except Exception as e:
        logger.exception(f"프로그램 오류: {e}")
        QMessageBox.critical(None, "오류", f"프로그램 실행 중 오류 발생:\n{e}")


if __name__ == '__main__':
    main()
