# -*- coding: utf-8 -*-
"""코어 알고리즘 단위 테스트

rfind 전환, 소프트 리셋, MutationObserver 관련 로직 검증.
"""

import sys
import os
import threading
from datetime import datetime
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.utils import compact_subtitle_text, slice_from_compact_index, get_word_diff
from core.models import SubtitleEntry


# ============================================================
# 헬퍼: MainWindow의 코어 로직만 테스트하기 위한 최소 Mock
# ============================================================


class MockMainWindow:
    """MainWindow의 코어 자막 처리 메서드만 격리하여 테스트"""

    def __init__(self):
        self.subtitles = []
        self.subtitle_lock = threading.Lock()
        self._confirmed_compact = ""
        self._trailing_suffix = ""
        self._suffix_length = 50
        self._last_raw_text = ""
        self._last_processed_raw = ""
        self._preview_desync_count = 0
        self._preview_ambiguous_skip_count = 0
        self._last_good_raw_compact = ""
        self._preview_resync_threshold = 10
        self._preview_ambiguous_resync_threshold = 6
        self._cached_total_chars = 0
        self._cached_total_words = 0

    def _extract_new_part(self, raw: str, raw_compact: str) -> str:
        """rfind 기반 새 부분 추출 (실제 코드와 동일)"""
        if not self._trailing_suffix:
            return raw
        pos = raw_compact.rfind(self._trailing_suffix)
        if pos >= 0:
            start_idx = pos + len(self._trailing_suffix)
            if start_idx >= len(raw_compact):
                return ""
            return slice_from_compact_index(raw, start_idx)
        return raw

    def _soft_resync(self) -> None:
        """소프트 리셋 (실제 코드와 동일)"""
        with self.subtitle_lock:
            if self.subtitles:
                recent = " ".join(
                    e.text for e in self.subtitles[-5:] if e and e.text
                )
                self._confirmed_compact = compact_subtitle_text(recent)
                if len(self._confirmed_compact) >= self._suffix_length:
                    self._trailing_suffix = self._confirmed_compact[
                        -self._suffix_length :
                    ]
                else:
                    self._trailing_suffix = self._confirmed_compact
            else:
                self._confirmed_compact = ""
                self._trailing_suffix = ""


# ============================================================
# 테스트: rfind 전환
# ============================================================


def test_rfind_prevents_over_extraction():
    """suffix 중복 시 rfind가 마지막 위치 기준으로 추출"""
    mw = MockMainWindow()
    mw._trailing_suffix = compact_subtitle_text("위원장 감사합니다")

    raw = "기존 텍스트 위원장 감사합니다 중간 텍스트 위원장 감사합니다 새로운 발언"
    raw_compact = compact_subtitle_text(raw)
    result = mw._extract_new_part(raw, raw_compact)

    result_compact = compact_subtitle_text(result)
    assert "새로운발언" in result_compact, f"새 발언이 포함되어야 함: {result}"
    assert "중간텍스트" not in result_compact, f"중간 텍스트가 제외되어야 함: {result}"
    print("✅ test_rfind_prevents_over_extraction PASSED")


def test_rfind_no_new_content():
    """suffix 이후에 새 내용이 없으면 빈 문자열 반환"""
    mw = MockMainWindow()
    mw._trailing_suffix = compact_subtitle_text("마지막 텍스트입니다")

    raw = "이전 내용 마지막 텍스트입니다"
    raw_compact = compact_subtitle_text(raw)
    result = mw._extract_new_part(raw, raw_compact)

    assert result == "", f"새 내용이 없으면 빈 문자열: '{result}'"
    print("✅ test_rfind_no_new_content PASSED")


def test_rfind_suffix_not_found():
    """suffix가 raw에 없으면 전체를 새 문맥으로 반환"""
    mw = MockMainWindow()
    mw._trailing_suffix = "전혀다른텍스트"

    raw = "완전히 새로운 문장입니다"
    raw_compact = compact_subtitle_text(raw)
    result = mw._extract_new_part(raw, raw_compact)

    assert result == raw, f"전체를 반환해야 함: '{result}'"
    print("✅ test_rfind_suffix_not_found PASSED")


def test_rfind_empty_suffix():
    """suffix가 비어있으면 전체를 새 내용으로"""
    mw = MockMainWindow()
    mw._trailing_suffix = ""

    raw = "첫 번째 자막"
    raw_compact = compact_subtitle_text(raw)
    result = mw._extract_new_part(raw, raw_compact)

    assert result == raw, f"첫 입력은 전체 반환: '{result}'"
    print("✅ test_rfind_empty_suffix PASSED")


# ============================================================
# 테스트: 소프트 리셋
# ============================================================


def test_soft_resync_preserves_recent():
    """소프트 리셋이 최근 자막 기반으로 suffix를 복원"""
    mw = MockMainWindow()
    mw.subtitles = [
        SubtitleEntry("첫 번째 자막입니다"),
        SubtitleEntry("두 번째 자막 텍스트가 길게 이어집니다"),
        SubtitleEntry("세 번째 자막은 더 길어서 충분한 텍스트를 제공합니다"),
    ]
    mw._confirmed_compact = ""
    mw._trailing_suffix = ""

    mw._soft_resync()

    assert mw._trailing_suffix != "", "suffix가 복원되어야 함"
    assert mw._confirmed_compact != "", "confirmed_compact가 복원되어야 함"

    # 최근 자막의 compact가 포함되어 있는지
    third_compact = compact_subtitle_text("세 번째 자막은 더 길어서 충분한 텍스트를 제공합니다")
    assert third_compact in mw._confirmed_compact, "마지막 자막이 포함되어야 함"
    print("✅ test_soft_resync_preserves_recent PASSED")


def test_soft_resync_fallback_empty():
    """자막이 없을 때 전체 리셋으로 fallback"""
    mw = MockMainWindow()
    mw.subtitles = []
    mw._confirmed_compact = "some_stale_data"
    mw._trailing_suffix = "stale"

    mw._soft_resync()

    assert mw._confirmed_compact == "", "자막 없으면 전체 리셋"
    assert mw._trailing_suffix == "", "자막 없으면 suffix도 초기화"
    print("✅ test_soft_resync_fallback_empty PASSED")


def test_soft_resync_prevents_duplicate():
    """소프트 리셋 후 동일 텍스트 재유입 시 suffix 매칭으로 차단"""
    mw = MockMainWindow()
    recent_text = "이전에 확정된 자막입니다 충분히 긴 텍스트를 포함하여 suffix가 제대로 만들어지도록 합니다"
    mw.subtitles = [SubtitleEntry(recent_text)]

    mw._soft_resync()

    # 동일 텍스트가 다시 들어오면 suffix가 매칭되어 빈 문자열 반환
    raw_compact = compact_subtitle_text(recent_text)
    result = mw._extract_new_part(recent_text, raw_compact)

    assert result == "" or compact_subtitle_text(result) == "", \
        f"동일 텍스트 재유입 시 새 내용 없어야 함: '{result}'"
    print("✅ test_soft_resync_prevents_duplicate PASSED")


# ============================================================
# 실행
# ============================================================


def run_all_tests():
    tests = [
        test_rfind_prevents_over_extraction,
        test_rfind_no_new_content,
        test_rfind_suffix_not_found,
        test_rfind_empty_suffix,
        test_soft_resync_preserves_recent,
        test_soft_resync_fallback_empty,
        test_soft_resync_prevents_duplicate,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__} FAILED: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"결과: {passed} passed, {failed} failed / {len(tests)} total")
    if failed == 0:
        print("🎉 모든 테스트 통과!")
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
