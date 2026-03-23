# -*- coding: utf-8 -*-

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, List, Mapping, Optional, Union
from core.config import Config
from core.models import SubtitleEntry

def atomic_write_json(
    path: Union[str, Path],
    data: object,
    *,
    ensure_ascii: bool = False,
    indent: int = 2,
    encoding: str = "utf-8",
) -> None:
    """JSON 파일을 원자적으로 저장한다."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    temp_file = Path(temp_path)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            json.dump(data, f, ensure_ascii=ensure_ascii, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(temp_file), str(target))
    except Exception:
        try:
            temp_file.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def iter_serialized_subtitles(
    entries: Iterable[SubtitleEntry],
) -> Iterator[Mapping[str, object]]:
    for entry in entries:
        yield entry.to_dict()


def atomic_write_json_stream(
    path: Union[str, Path],
    *,
    head_items: Iterable[tuple[str, object]],
    sequence_key: str,
    sequence_items: Iterable[object],
    tail_items: Iterable[tuple[str, object]] = (),
    ensure_ascii: bool = False,
    encoding: str = "utf-8",
) -> None:
    """JSON object를 배열 필드 하나와 함께 스트리밍 저장한다."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    temp_file = Path(temp_path)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write("{\n")
            wrote_any = False

            def write_item(key: str, value: object) -> None:
                nonlocal wrote_any
                if wrote_any:
                    f.write(",\n")
                f.write(
                    f"{json.dumps(str(key), ensure_ascii=ensure_ascii)}: "
                    f"{json.dumps(value, ensure_ascii=ensure_ascii)}"
                )
                wrote_any = True

            for key, value in head_items:
                write_item(key, value)

            if wrote_any:
                f.write(",\n")
            f.write(f"{json.dumps(sequence_key, ensure_ascii=ensure_ascii)}: [\n")
            first_item = True
            for item in sequence_items:
                if not first_item:
                    f.write(",\n")
                f.write(json.dumps(item, ensure_ascii=ensure_ascii))
                first_item = False
            f.write("\n]")
            wrote_any = True

            for key, value in tail_items:
                write_item(key, value)

            f.write("\n}\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(temp_file), str(target))
    except Exception:
        try:
            temp_file.unlink(missing_ok=True)
        except Exception:
            pass
        raise

def atomic_write_text(
    path: Union[str, Path],
    content: str,
    *,
    encoding: str = "utf-8",
    newline: Optional[str] = None,
) -> None:
    """텍스트 파일을 원자적으로 저장한다."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    temp_file = Path(temp_path)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline=newline) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(temp_file), str(target))
    except Exception:
        try:
            temp_file.unlink(missing_ok=True)
        except Exception:
            pass
        raise

def atomic_write_bytes(path: Union[str, Path], content: bytes) -> None:
    """바이너리 파일을 원자적으로 저장한다."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    temp_file = Path(temp_path)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(temp_file), str(target))
    except Exception:
        try:
            temp_file.unlink(missing_ok=True)
        except Exception:
            pass
        raise
