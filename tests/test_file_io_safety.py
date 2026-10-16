import json
from pathlib import Path
import pytest

from core import utils
from core import file_io


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


def test_next_available_path_returns_original_when_missing(tmp_path):
    target = tmp_path / "backup_20260521_120000_000001.json"

    assert utils.next_available_path(target) == target


def test_next_available_path_adds_numeric_suffix_without_overwriting(tmp_path):
    target = tmp_path / "backup_20260521_120000_000001.json"
    target.write_text("first", encoding="utf-8")
    (tmp_path / "backup_20260521_120000_000001_001.json").write_text(
        "second",
        encoding="utf-8",
    )

    assert (
        utils.next_available_path(target)
        == tmp_path / "backup_20260521_120000_000001_002.json"
    )


def _write(kind, target):
    """Exercise each public atomic writer, including streaming callbacks."""
    if kind == "json":
        file_io.atomic_write_json(target, {"text": "새 자막"})
    elif kind == "json_stream":
        file_io.atomic_write_json_stream(
            target, head_items=[("version", "test")], sequence_key="subtitles",
            sequence_items=iter([{"text": "새 자막"}]), tail_items=[("count", 1)],
        )
    elif kind == "text":
        file_io.atomic_write_text(target, "새 자막")
    elif kind == "text_writer":
        def write_text(handle):
            handle.write("새 자막")
        file_io.atomic_write_text_via_writer(target, write_text)
    elif kind == "bytes":
        file_io.atomic_write_bytes(target, b"new bytes")
    else:
        def write_bytes(handle):
            handle.write(b"new bytes")
        file_io.atomic_write_bytes_via_writer(target, write_bytes)


@pytest.mark.parametrize("kind", ["json", "json_stream", "text", "text_writer", "bytes", "bytes_writer"])
@pytest.mark.parametrize("failure_point", ["fsync", "replace"])
def test_atomic_writers_preserve_original_and_cleanup_on_os_failure(tmp_path, monkeypatch, kind, failure_point):
    target = tmp_path / "session.dat"
    original = b"original data must survive\r\n"
    target.write_bytes(original)
    calls = []

    def fail(*args):
        calls.append(args)
        # The destination is still complete even after the temporary file was written.
        assert target.read_bytes() == original
        raise OSError("injected disk failure")

    with monkeypatch.context() as patch:
        patch.setattr(file_io.os, failure_point, fail)
        with pytest.raises(OSError, match="injected disk failure"):
            _write(kind, target)
    assert len(calls) == 1
    assert target.read_bytes() == original
    assert list(tmp_path.iterdir()) == [target]

    # A failed save must not poison the next attempt.
    _write(kind, target)
    assert target.read_bytes() != original
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("kind", ["json", "json_stream", "text_writer", "bytes_writer"])
@pytest.mark.parametrize("existing", [True, False])
def test_atomic_writers_discard_partial_serialization(tmp_path, kind, existing):
    target = tmp_path / "snapshot.dat"
    if existing:
        target.write_bytes(b"previous snapshot")

    def broken_items():
        yield {"text": "already serialized"}
        raise ValueError("input interrupted")

    def broken_writer(handle):
        handle.write(b"partial" if kind == "bytes_writer" else "partial")
        raise ValueError("input interrupted")

    error = TypeError if kind == "json" else ValueError
    with pytest.raises(error, match="serializable" if kind == "json" else "input interrupted"):
        if kind == "json":
            file_io.atomic_write_json(target, {"first": "written", "bad": object()})
        elif kind == "json_stream":
            file_io.atomic_write_json_stream(target, head_items=[], sequence_key="subtitles", sequence_items=broken_items())
        elif kind == "text_writer":
            file_io.atomic_write_text_via_writer(target, broken_writer)
        else:
            file_io.atomic_write_bytes_via_writer(target, broken_writer)
    assert sorted(tmp_path.iterdir()) == ([target] if existing else [])
    if existing:
        assert target.read_bytes() == b"previous snapshot"


def test_streaming_json_round_trip_escapes_and_consumes_input_once(tmp_path):
    target = tmp_path / "stream.json"
    expected = [{"text": '한글 "인용"\n역슬래시\\ 이모지 🎤', "index": i} for i in range(7)]
    consumed = []

    def entries():
        for row in expected:
            consumed.append(row["index"])
            yield row

    file_io.atomic_write_json_stream(
        target, head_items=[('위원회"명', "예산")], sequence_key='자막"목록',
        sequence_items=entries(), tail_items=[("count", len(expected))],
    )
    assert json.loads(target.read_text(encoding="utf-8")) == {'위원회"명': "예산", '자막"목록': expected, "count": 7}
    assert consumed == list(range(7))


def test_next_available_path_exhaustion_preserves_all_files(tmp_path):
    target = tmp_path / "backup.json"
    originals = {target: b"first", target.with_stem("backup_001"): b"second"}
    for path, content in originals.items():
        path.write_bytes(content)
    with pytest.raises(FileExistsError, match="exhausted"):
        file_io.next_available_path(target, max_attempts=1)
    assert {path: path.read_bytes() for path in tmp_path.iterdir()} == originals


@pytest.mark.parametrize("kind", ["json", "json_stream", "text", "text_writer", "bytes", "bytes_writer"])
def test_atomic_writers_retry_transient_cleanup_lock_without_masking_save_error(tmp_path, monkeypatch, kind):
    target = tmp_path / "snapshot.dat"
    target.write_bytes(b"original")
    original_unlink = Path.unlink
    attempts = []
    save_error = OSError("replace failed")

    def fail_replace(*_args):
        raise save_error

    def temporarily_locked(path, *args, **kwargs):
        attempts.append(path)
        if len(attempts) < 3:
            raise PermissionError("temporary sharing lock")
        return original_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(file_io.os, "replace", fail_replace)
        patch.setattr(Path, "unlink", temporarily_locked)
        with pytest.raises(OSError, match="replace failed") as error:
            _write(kind, target)
        assert error.value is save_error
    assert len(attempts) == 3
    assert list(tmp_path.iterdir()) == [target]
    assert target.read_bytes() == b"original"


def test_permanent_cleanup_lock_is_bounded_and_preserves_original_error(tmp_path, monkeypatch):
    target = tmp_path / "snapshot.json"
    attempts = []

    def locked(path, **_kwargs):
        attempts.append(path)
        raise PermissionError("permanent sharing lock")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", locked)
        with pytest.raises(TypeError, match="serializable"):
            file_io.atomic_write_json(target, {"bad": object()})
    assert len(attempts) == 3
    assert not target.exists()
    assert len(list(tmp_path.iterdir())) == 1
    # Once our simulated lock is gone, clean up the intentionally retained temp.
    attempts[-1].unlink()
