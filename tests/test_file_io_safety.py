import json
import zipfile
from datetime import datetime

from core import utils
from core.models import SubtitleEntry


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


# ── save_hwpx 테스트 ──────────────────────────────────────────────────────────

def test_save_hwpx_creates_valid_zip(tmp_path):
    """save_hwpx가 올바른 ZIP 구조의 .hwpx 파일을 생성한다."""
    target = tmp_path / "output.hwpx"
    entries = [
        SubtitleEntry("첫 번째 자막", datetime(2026, 3, 23, 9, 0, 0)),
        SubtitleEntry("두 번째 자막", datetime(2026, 3, 23, 9, 0, 30)),
        SubtitleEntry("세 번째 자막", datetime(2026, 3, 23, 9, 1, 10)),
    ]

    utils.save_hwpx(target, entries, generated_at="2026년 03월 23일 09:00:00")

    assert target.exists()
    assert target.stat().st_size > 0

    with zipfile.ZipFile(target) as zf:
        names = zf.namelist()
        assert "mimetype" in names
        assert "META-INF/container.xml" in names
        assert "Contents/content.hpf" in names
        assert "Contents/header.xml" in names
        assert "Contents/section0.xml" in names
        assert "Preview/PrvText.txt" in names


def test_save_hwpx_mimetype_is_stored_uncompressed(tmp_path):
    """mimetype 엔트리는 비압축(STORED)으로 저장되어야 한다."""
    target = tmp_path / "out.hwpx"
    utils.save_hwpx(target, [SubtitleEntry("테스트")])

    with zipfile.ZipFile(target) as zf:
        info = zf.getinfo("mimetype")
        assert info.compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype") == b"application/hwp+zip"


def test_save_hwpx_section_contains_subtitle_text(tmp_path):
    """section0.xml에 자막 텍스트가 포함되어야 한다."""
    target = tmp_path / "out.hwpx"
    entries = [SubtitleEntry("안녕하세요", datetime(2026, 3, 23, 10, 0, 0))]
    utils.save_hwpx(target, entries)

    with zipfile.ZipFile(target) as zf:
        section = zf.read("Contents/section0.xml").decode("utf-8")
        assert "안녕하세요" in section


def test_save_hwpx_xml_escapes_special_chars(tmp_path):
    """XML 특수문자(&, <, >)가 올바르게 이스케이프된다."""
    target = tmp_path / "out.hwpx"
    entries = [SubtitleEntry("A&B <C> D", datetime(2026, 3, 23, 10, 0, 0))]
    utils.save_hwpx(target, entries)

    with zipfile.ZipFile(target) as zf:
        section = zf.read("Contents/section0.xml").decode("utf-8")
        assert "&amp;" in section
        assert "&lt;" in section
        assert "&gt;" in section


def test_save_hwpx_timestamp_printed_every_60s(tmp_path):
    """60초 이상 간격에서만 타임스탬프가 출력된다."""
    target = tmp_path / "out.hwpx"
    entries = [
        SubtitleEntry("A", datetime(2026, 3, 23, 9, 0, 0)),   # 타임스탬프 표시
        SubtitleEntry("B", datetime(2026, 3, 23, 9, 0, 30)),  # 30초 → 표시 안 함
        SubtitleEntry("C", datetime(2026, 3, 23, 9, 1, 5)),   # 65초 → 표시
    ]
    utils.save_hwpx(target, entries)

    with zipfile.ZipFile(target) as zf:
        section = zf.read("Contents/section0.xml").decode("utf-8")
        assert "[09:00:00] A" in section
        assert "[09:00:30]" not in section
        assert "[09:01:05] C" in section


def test_save_hwpx_empty_entries(tmp_path):
    """자막이 없어도 파일이 정상적으로 생성된다."""
    target = tmp_path / "empty.hwpx"
    utils.save_hwpx(target, [])

    assert target.exists()
    with zipfile.ZipFile(target) as zf:
        section = zf.read("Contents/section0.xml").decode("utf-8")
        assert "총 0문장" in section


def test_save_hwpx_preview_text_matches_section(tmp_path):
    """PrvText.txt 프리뷰 텍스트에 자막 내용이 포함된다."""
    target = tmp_path / "out.hwpx"
    entries = [SubtitleEntry("미리보기 자막", datetime(2026, 3, 23, 11, 0, 0))]
    utils.save_hwpx(target, entries)

    with zipfile.ZipFile(target) as zf:
        preview = zf.read("Preview/PrvText.txt").decode("utf-8")
        assert "미리보기 자막" in preview
