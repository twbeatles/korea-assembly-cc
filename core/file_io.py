# -*- coding: utf-8 -*-

import io
import json
import os
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, List, Mapping, Optional, Union
from xml.sax.saxutils import escape as _xml_escape
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

def save_hwpx(
    path: Union[str, Path],
    entries: List[SubtitleEntry],
    *,
    title: str = "국회 의사중계 자막",
    generated_at: Optional[str] = None,
    timestamp_interval_seconds: int = 60,
) -> None:
    """HWPX 형식으로 자막을 저장한다.

    순수 Python(표준 라이브러리만)으로 구현되어 Hancom Office 없이도 동작한다.
    생성된 .hwpx 파일은 한컴오피스 2018 이상에서 열 수 있다.
    """
    if generated_at is None:
        generated_at = datetime.now().strftime("%Y년 %m월 %d일 %H:%M:%S")

    total_chars = sum(len(e.text) for e in entries)

    # ── 1. mimetype ──────────────────────────────────────────────────────────
    MIMETYPE = b"application/hwp+zip"

    # ── 2. META-INF/container.xml ────────────────────────────────────────────
    CONTAINER = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<hcf:container version="1.0"'
        ' xmlns:hcf="urn:HancomOffice:Names:tc:opendocument:xmlns:container">\n'
        "  <hcf:rootfiles>\n"
        '    <hcf:rootfile full-path="Contents/content.hpf"'
        ' media-type="application/hwp+zip"/>\n'
        "  </hcf:rootfiles>\n"
        "</hcf:container>\n"
    )

    # ── 3. Contents/content.hpf (manifest) ───────────────────────────────────
    HPF = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        "<hpf:HWPFPackage"
        ' xmlns:hpf="urn:HancomOffice:Names:tc:opendocument:xmlns:package:1.0">\n'
        "  <hpf:manifest>\n"
        '    <hpf:item href="Contents/header.xml" media-type="application/xml"/>\n'
        '    <hpf:item href="Contents/section0.xml" media-type="application/xml"/>\n'
        '    <hpf:item href="Preview/PrvText.txt" media-type="text/plain"/>\n'
        "  </hpf:manifest>\n"
        "</hpf:HWPFPackage>\n"
    )

    # ── 4. Contents/header.xml ───────────────────────────────────────────────
    # 문자 속성 2개: 0=본문(10pt), 1=제목(12pt 굵음)
    # 단락 속성 2개: 0=왼쪽 정렬, 1=가운데 정렬
    HEADER = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<hml:head xmlns:hml="urn:HancomOffice:Names:tc:opendocument:xmlns:hwpml:2.0"'
        ' version="2.0">\n'
        '  <hml:beginNum pageNum="1" fnNum="1" enNum="1" picNum="1"'
        ' tblNum="1" eqNum="1"/>\n'
        "  <hml:refList>\n"
        '    <hml:charPrList count="2">\n'
        # charPr id=0: 본문(10pt)
        '      <hml:charPr id="0" height="1000" textColor="0" shadeColor="-1"'
        ' useFontSpace="0" useKerning="0" symMark="0" borderFillIDRef="0">\n'
        '        <hml:fontRef hangul="0" latin="1" hanja="0" japanese="0"'
        ' other="1" symbol="1" user="0"/>\n'
        '        <hml:ratio hangul="100" latin="100" hanja="100" japanese="100"'
        ' other="100" symbol="100" user="100"/>\n'
        '        <hml:spacing hangul="0" latin="0" hanja="0" japanese="0"'
        ' other="0" symbol="0" user="0"/>\n'
        '        <hml:relSz hangul="100" latin="100" hanja="100" japanese="100"'
        ' other="100" symbol="100" user="100"/>\n'
        '        <hml:offset hangul="0" latin="0" hanja="0" japanese="0"'
        ' other="0" symbol="0" user="0"/>\n'
        "      </hml:charPr>\n"
        # charPr id=1: 제목(12pt, 굵음)
        '      <hml:charPr id="1" height="1200" textColor="0" shadeColor="-1"'
        ' useFontSpace="0" useKerning="0" symMark="0" borderFillIDRef="0"'
        ' bold="1">\n'
        '        <hml:fontRef hangul="0" latin="1" hanja="0" japanese="0"'
        ' other="1" symbol="1" user="0"/>\n'
        '        <hml:ratio hangul="100" latin="100" hanja="100" japanese="100"'
        ' other="100" symbol="100" user="100"/>\n'
        '        <hml:spacing hangul="0" latin="0" hanja="0" japanese="0"'
        ' other="0" symbol="0" user="0"/>\n'
        '        <hml:relSz hangul="100" latin="100" hanja="100" japanese="100"'
        ' other="100" symbol="100" user="100"/>\n'
        '        <hml:offset hangul="0" latin="0" hanja="0" japanese="0"'
        ' other="0" symbol="0" user="0"/>\n'
        "      </hml:charPr>\n"
        "    </hml:charPrList>\n"
        '    <hml:tabPrList count="1">\n'
        '      <hml:tabPr id="0" autoTabLeft="1" autoTabRight="1"/>\n'
        "    </hml:tabPrList>\n"
        '    <hml:numbList count="0"/>\n'
        '    <hml:paraPrList count="2">\n'
        # paraPr id=0: 왼쪽 정렬(본문)
        '      <hml:paraPr id="0" condense="0" fontLineHeight="0" snapToGrid="1"'
        ' suppressLineNumbers="0" checked="0">\n'
        '        <hml:align horizontal="Justify" vertical="Baseline"/>\n'
        '        <hml:heading type="None" idRef="0" level="0"/>\n'
        '        <hml:breakSetting breakLatinWord="BreakWord"'
        ' breakNonLatinWord="KeepWord" widowOrphan="0" keepWithNext="0"'
        ' keepLines="0" pageBreakBefore="0" columnBreakBefore="0"/>\n'
        '        <hml:autoSpacing eAsianEng="1" eAsianNum="1"/>\n'
        "      </hml:paraPr>\n"
        # paraPr id=1: 가운데 정렬(제목)
        '      <hml:paraPr id="1" condense="0" fontLineHeight="0" snapToGrid="1"'
        ' suppressLineNumbers="0" checked="0">\n'
        '        <hml:align horizontal="Center" vertical="Baseline"/>\n'
        '        <hml:heading type="None" idRef="0" level="0"/>\n'
        '        <hml:breakSetting breakLatinWord="BreakWord"'
        ' breakNonLatinWord="KeepWord" widowOrphan="0" keepWithNext="0"'
        ' keepLines="0" pageBreakBefore="0" columnBreakBefore="0"/>\n'
        '        <hml:autoSpacing eAsianEng="1" eAsianNum="1"/>\n'
        "      </hml:paraPr>\n"
        "    </hml:paraPrList>\n"
        '    <hml:styleList count="1">\n'
        '      <hml:style id="0" type="Para" name="Normal" engName="Normal"'
        ' paraPrIDRef="0" charPrIDRef="0" nextStyleIDRef="0"'
        ' langID="1042" lockForm="0"/>\n'
        "    </hml:styleList>\n"
        '    <hml:memoList count="0"/>\n'
        '    <hml:trackChangeList count="0"/>\n'
        '    <hml:fontList count="2">\n'
        '      <hml:font id="0" face="바탕" type="TTF" isEmbedded="0">\n'
        '        <hml:typeInfo familyType="Roman" serif="1" fixedPitch="0"'
        ' symFont="0" script="0"/>\n'
        "      </hml:font>\n"
        '      <hml:font id="1" face="Arial" type="TTF" isEmbedded="0">\n'
        '        <hml:typeInfo familyType="Swiss" serif="0" fixedPitch="0"'
        ' symFont="0" script="0"/>\n'
        "      </hml:font>\n"
        "    </hml:fontList>\n"
        '    <hml:borderFillList count="1">\n'
        '      <hml:borderFill id="0" threeD="0" shadow="0" centerLine="0"'
        ' breakCellSeparateLine="0">\n'
        '        <hml:slash type="None" Crooked="0" isCounter="0"/>\n'
        '        <hml:backSlash type="None" Crooked="0" isCounter="0"/>\n'
        '        <hml:leftBorder type="None" width="0.1mm" color="0"/>\n'
        '        <hml:rightBorder type="None" width="0.1mm" color="0"/>\n'
        '        <hml:topBorder type="None" width="0.1mm" color="0"/>\n'
        '        <hml:bottomBorder type="None" width="0.1mm" color="0"/>\n'
        '        <hml:diagonal type="None" width="0.1mm" color="0"/>\n'
        '        <hml:fillBrush useFillBrush="0">\n'
        '          <hml:winBrush faceColor="4294967295" hatchColor="0" alpha="0"/>\n'
        "        </hml:fillBrush>\n"
        "      </hml:borderFill>\n"
        "    </hml:borderFillList>\n"
        '    <hml:charShapeList count="0"/>\n'
        '    <hml:paraShapeList count="0"/>\n'
        '    <hml:bulletList count="0"/>\n'
        '    <hml:notNumberingList count="0"/>\n'
        "  </hml:refList>\n"
        '  <hml:compatibleDocument targetProgram="HWP7X">\n'
        "    <hml:layoutCompatibility>\n"
        '      <hml:lineWrapType lineWrap="Break"/>\n'
        '      <hml:fieldCtrlMasking fieldCtrlMasking="0"/>\n'
        "    </hml:layoutCompatibility>\n"
        "  </hml:compatibleDocument>\n"
        "  <hml:docOption>\n"
        '    <hml:linkPropertyOption baseStyle="Normal"/>\n'
        "  </hml:docOption>\n"
        '  <hml:trackChangeConfig insertAfterFormattingChange="0"/>\n'
        "</hml:head>\n"
    )

    # ── 5. Contents/section0.xml ─────────────────────────────────────────────
    HML_NS = (
        'xmlns:hml="urn:HancomOffice:Names:tc:opendocument:xmlns:hwpml:2.0"'
    )

    def _para(pid: int, text: str, para_pr: int = 0, char_pr: int = 0) -> str:
        return (
            f'  <hml:p id="{pid}" paraPrIDRef="{para_pr}" styleIDRef="0"'
            f' pageBreak="0" columnBreak="0">\n'
            f'    <hml:run charPrIDRef="{char_pr}">\n'
            f"      <hml:t>{text}</hml:t>\n"
            f"    </hml:run>\n"
            f"  </hml:p>\n"
        )

    sec_parts: List[str] = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n',
        f"<hml:sec {HML_NS} id=\"0\" visibility=\"0\" protect=\"0\""
        f' masterPageIDRef="0" hasTextRef="0" hasNumRef="0">\n',
    ]

    pid = 0
    # 제목 단락: 가운데 정렬(paraPr=1), 굵은 글꼴(charPr=1)
    sec_parts.append(_para(pid, _xml_escape(title), para_pr=1, char_pr=1))
    pid += 1

    # 생성 일시
    sec_parts.append(
        _para(pid, _xml_escape(f"생성 일시: {generated_at}"))
    )
    pid += 1

    # 빈 줄
    sec_parts.append(_para(pid, ""))
    pid += 1

    # 자막 내용 (1분 간격 타임스탬프)
    last_ts: Optional[datetime] = None
    for entry in entries:
        should_stamp = last_ts is None or (
            entry.timestamp - last_ts
        ).total_seconds() >= timestamp_interval_seconds
        if should_stamp:
            line_text = f"[{entry.timestamp.strftime('%H:%M:%S')}] {entry.text}"
            last_ts = entry.timestamp
        else:
            line_text = entry.text
        sec_parts.append(_para(pid, _xml_escape(line_text)))
        pid += 1

    # 통계
    sec_parts.append(_para(pid, ""))
    pid += 1
    sec_parts.append(
        _para(pid, _xml_escape(f"총 {len(entries)}문장, {total_chars:,}자"))
    )

    sec_parts.append("</hml:sec>\n")
    section_xml = "".join(sec_parts)

    # ── 6. Preview/PrvText.txt ───────────────────────────────────────────────
    prev: List[str] = [title, "", f"생성 일시: {generated_at}", ""]
    last_ts = None
    for entry in entries:
        should_stamp = last_ts is None or (
            entry.timestamp - last_ts
        ).total_seconds() >= timestamp_interval_seconds
        if should_stamp:
            prev.append(f"[{entry.timestamp.strftime('%H:%M:%S')}] {entry.text}")
            last_ts = entry.timestamp
        else:
            prev.append(entry.text)
    prev.extend(["", f"총 {len(entries)}문장, {total_chars:,}자"])
    preview_text = "\n".join(prev)

    # ── 7. ZIP 조립 ──────────────────────────────────────────────────────────
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # mimetype은 반드시 첫 번째, 비압축(STORED) 저장
        mi = zipfile.ZipInfo("mimetype")
        mi.compress_type = zipfile.ZIP_STORED
        zf.writestr(mi, MIMETYPE)

        zf.writestr("META-INF/container.xml", CONTAINER.encode("utf-8"))
        zf.writestr("Contents/content.hpf", HPF.encode("utf-8"))
        zf.writestr("Contents/header.xml", HEADER.encode("utf-8"))
        zf.writestr("Contents/section0.xml", section_xml.encode("utf-8"))
        zf.writestr("Preview/PrvText.txt", preview_text.encode("utf-8"))

    atomic_write_bytes(path, buf.getvalue())


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
