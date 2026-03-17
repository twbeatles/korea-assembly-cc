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


def test_flatten_subtitle_text_removes_blank_lines_without_dropping_content():
    raw = "전 세계의 정부학교장을\n\n민간이 한 게 어디 있어요\n   \n한란도 없어요"

    assert (
        utils.flatten_subtitle_text(raw)
        == "전 세계의 정부학교장을 민간이 한 게 어디 있어요 한란도 없어요"
    )
