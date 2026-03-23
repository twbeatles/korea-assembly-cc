import json

from core import utils


def test_atomic_write_json_creates_file_and_parent(tmp_path):
    target = tmp_path / "nested" / "history.json"

    utils.atomic_write_json(target, {"name": "assembly", "count": 1})

    assert target.exists()
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded == {"name": "assembly", "count": 1}


def test_atomic_write_json_overwrite_keeps_valid_json(tmp_path):
    target = tmp_path / "state.json"
    target.write_text('{"old": true}', encoding="utf-8")

    utils.atomic_write_json(target, {"new": True, "items": [1, 2, 3]})

    raw = target.read_text(encoding="utf-8")
    loaded = json.loads(raw)
    assert loaded == {"new": True, "items": [1, 2, 3]}


def test_atomic_write_text_creates_file_and_parent(tmp_path):
    target = tmp_path / "nested" / "subtitle.txt"

    utils.atomic_write_text(target, "첫 줄\n둘째 줄\n", encoding="utf-8")

    assert target.exists()
    assert target.read_text(encoding="utf-8") == "첫 줄\n둘째 줄\n"


def test_atomic_write_text_overwrite_keeps_content_integrity(tmp_path):
    target = tmp_path / "output.vtt"
    target.write_text("OLD", encoding="utf-8")

    content = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:03.000\n안녕하세요\n"
    utils.atomic_write_text(target, content, encoding="utf-8")

    assert target.read_text(encoding="utf-8") == content
