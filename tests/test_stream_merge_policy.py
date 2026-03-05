from datetime import datetime, timedelta
import threading

import pytest

from core.models import SubtitleEntry

mw_mod = pytest.importorskip("ui.main_window")
MainWindow = mw_mod.MainWindow


def _build_window_with_last_entry(text: str = "기존 문장"):
    win = MainWindow.__new__(MainWindow)
    win.subtitle_lock = threading.Lock()

    entry = SubtitleEntry(text)
    now = datetime.now()
    entry.start_time = now
    entry.end_time = now

    win.subtitles = [entry]
    win._cached_total_chars = entry.char_count
    win._cached_total_words = entry.word_count
    win.realtime_file = None
    win._check_keyword_alert = lambda _text: None
    win._update_count_label = lambda: None
    win._refresh_text = lambda force_full=False: None
    return win


def test_add_text_merges_into_last_entry_when_within_threshold():
    win = _build_window_with_last_entry()

    MainWindow._add_text_to_subtitles(win, "추가 문장")

    assert len(win.subtitles) == 1
    assert "추가 문장" in win.subtitles[0].text


def test_add_text_respects_config_length_threshold(monkeypatch):
    win = _build_window_with_last_entry(text="긴 문장")
    monkeypatch.setattr(mw_mod.Config, "ENTRY_MERGE_MAX_CHARS", 5, raising=False)

    MainWindow._add_text_to_subtitles(win, "추가 문장")

    assert len(win.subtitles) == 2


def test_add_text_respects_config_gap_threshold():
    win = _build_window_with_last_entry()
    win.subtitles[0].end_time = datetime.now() - timedelta(
        seconds=mw_mod.Config.ENTRY_MERGE_MAX_GAP + 1
    )

    MainWindow._add_text_to_subtitles(win, "뒤늦은 문장")

    assert len(win.subtitles) == 2
