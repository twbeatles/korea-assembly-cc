from core import utils


def test_short_utterance_korean_is_allowed():
    assert utils.is_meaningful_subtitle_text("네")
    assert utils.is_meaningful_subtitle_text("예.")


def test_short_utterance_noise_is_blocked():
    assert not utils.is_meaningful_subtitle_text("...")
    assert not utils.is_meaningful_subtitle_text("123")
    assert not utils.is_meaningful_subtitle_text("   ")
