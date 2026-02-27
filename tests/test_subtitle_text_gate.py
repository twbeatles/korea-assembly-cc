from core import utils


def test_meaningful_subtitle_text_accepts_short_utterances():
    assert utils.is_meaningful_subtitle_text("네") is True
    assert utils.is_meaningful_subtitle_text("예") is True
    assert utils.is_meaningful_subtitle_text("ok") is True


def test_meaningful_subtitle_text_rejects_noise():
    assert utils.is_meaningful_subtitle_text("") is False
    assert utils.is_meaningful_subtitle_text("   ") is False
    assert utils.is_meaningful_subtitle_text("...") is False
    assert utils.is_meaningful_subtitle_text("--") is False
    assert utils.is_meaningful_subtitle_text("123") is False
