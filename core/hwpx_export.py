from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence
from xml.sax.saxutils import escape
from zipfile import ZIP_STORED, ZipFile

from core.file_io import atomic_write_bytes

_TITLE = "국회 의사중계 자막"
_HEADER_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "assets" / "hwpx" / "header.xml"
_XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
_SECTION_NAMESPACES = (
    'xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
    'xmlns:hp10="http://www.hancom.co.kr/hwpml/2016/paragraph" '
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
    'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" '
    'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
    'xmlns:hhs="http://www.hancom.co.kr/hwpml/2011/history" '
    'xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page" '
    'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:opf="http://www.idpf.org/2007/opf/" '
    'xmlns:ooxmlchart="http://www.hancom.co.kr/hwpml/2016/ooxmlchart" '
    'xmlns:hwpunitchar="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar" '
    'xmlns:epub="http://www.idpf.org/2007/ops" '
    'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0"'
)
_FIRST_PARAGRAPH = (
    '<hp:p id="2764991984" paraPrIDRef="3" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
    '<hp:run charPrIDRef="0">'
    '<hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000" '
    'tabStopVal="4000" tabStopUnit="HWPUNIT" outlineShapeIDRef="1" memoShapeIDRef="0" '
    'textVerticalWidthHead="0" masterPageCnt="0">'
    '<hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0"/>'
    '<hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>'
    '<hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0" '
    'border="SHOW_ALL" fill="SHOW_ALL" hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>'
    '<hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/>'
    '<hp:pagePr landscape="WIDELY" width="59528" height="84188" gutterType="LEFT_ONLY">'
    '<hp:margin header="4252" footer="4252" gutter="0" left="8504" right="8504" top="5668" bottom="4252"/>'
    '</hp:pagePr>'
    '<hp:footNotePr><hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/>'
    '<hp:noteLine length="-1" type="SOLID" width="0.12 mm" color="#000000"/>'
    '<hp:noteSpacing betweenNotes="283" belowLine="567" aboveLine="850"/>'
    '<hp:numbering type="CONTINUOUS" newNum="1"/>'
    '<hp:placement place="EACH_COLUMN" beneathText="0"/></hp:footNotePr>'
    '<hp:endNotePr><hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/>'
    '<hp:noteLine length="14692344" type="SOLID" width="0.12 mm" color="#000000"/>'
    '<hp:noteSpacing betweenNotes="0" belowLine="567" aboveLine="850"/>'
    '<hp:numbering type="CONTINUOUS" newNum="1"/>'
    '<hp:placement place="END_OF_DOCUMENT" beneathText="0"/></hp:endNotePr>'
    '<hp:pageBorderFill type="BOTH" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER">'
    '<hp:offset left="1417" right="1417" top="1417" bottom="1417"/></hp:pageBorderFill>'
    '<hp:pageBorderFill type="EVEN" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER">'
    '<hp:offset left="1417" right="1417" top="1417" bottom="1417"/></hp:pageBorderFill>'
    '<hp:pageBorderFill type="ODD" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER">'
    '<hp:offset left="1417" right="1417" top="1417" bottom="1417"/></hp:pageBorderFill>'
    '</hp:secPr>'
    '<hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/></hp:ctrl>'
    '<hp:t/>'
    '</hp:run>'
    '<hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="1000" textheight="1000" baseline="850" spacing="600" horzpos="0" horzsize="42520" flags="393216"/></hp:linesegarray>'
    '</hp:p>'
)
_PARAGRAPH_TEMPLATE = (
    '<hp:p id="{paragraph_id}" paraPrIDRef="3" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
    '<hp:run charPrIDRef="0">{text_node}</hp:run>'
    '</hp:p>'
)


def build_hwpx_lines(subtitles_snapshot: Sequence[tuple[datetime, str]], generated_at: datetime) -> list[str]:
    total_chars = sum(len(text) for _, text in subtitles_snapshot)
    lines = [_TITLE, f"생성 일시: {generated_at.strftime('%Y년 %m월 %d일 %H:%M:%S')}", ""]

    last_printed_ts: datetime | None = None
    for timestamp, text in subtitles_snapshot:
        should_print_ts = False
        if last_printed_ts is None:
            should_print_ts = True
        elif (timestamp - last_printed_ts).total_seconds() >= 60:
            should_print_ts = True

        if should_print_ts:
            prefix = f"[{timestamp.strftime('%H:%M:%S')}] "
            last_printed_ts = timestamp
        else:
            prefix = ""

        normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        parts = normalized.split("\n")
        first_part = parts[0] if parts else ""
        if len(parts) > 1:
            lines.append(f"{prefix}{first_part}\n" + "\n".join(parts[1:]))
        else:
            lines.append(f"{prefix}{first_part}")

    lines.extend(["", f"총 {len(subtitles_snapshot)}문장, {total_chars:,}자"])
    return lines


def _text_node(text: str) -> str:
    if not text:
        return "<hp:t/>"
    parts = str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    nodes: list[str] = []
    for index, part in enumerate(parts):
        nodes.append(f'<hp:t xml:space="preserve">{escape(part)}</hp:t>')
        if index < len(parts) - 1:
            nodes.append("<hp:lineBreak/>")
    return "".join(nodes)


def build_section_xml(lines: Sequence[str]) -> str:
    paragraphs = [_FIRST_PARAGRAPH]
    for index, line in enumerate(lines, start=1):
        paragraphs.append(
            _PARAGRAPH_TEMPLATE.format(
                paragraph_id=2764991984 + index,
                text_node=_text_node(line),
            )
        )
    return f"{_XML_DECL}<hs:sec {_SECTION_NAMESPACES}>{''.join(paragraphs)}</hs:sec>"


def build_content_hpf(generated_at: datetime) -> str:
    created_utc = generated_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    human_date = generated_at.strftime("%Y년 %m월 %d일 %H:%M:%S")
    return (
        f"{_XML_DECL}"
        '<opf:package xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
        'xmlns:hp10="http://www.hancom.co.kr/hwpml/2016/paragraph" '
        'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" '
        'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
        'xmlns:hhs="http://www.hancom.co.kr/hwpml/2011/history" '
        'xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page" '
        'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:opf="http://www.idpf.org/2007/opf/" '
        'xmlns:ooxmlchart="http://www.hancom.co.kr/hwpml/2016/ooxmlchart" '
        'xmlns:hwpunitchar="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar" '
        'xmlns:epub="http://www.idpf.org/2007/ops" '
        'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0" '
        'version="" unique-identifier="" id="">'
        '<opf:metadata>'
        f'<opf:title>{escape(_TITLE)}</opf:title>'
        '<opf:language>ko</opf:language>'
        '<opf:meta name="creator" content="text">korea-assembly-cc</opf:meta>'
        '<opf:meta name="subject" content="text">assembly subtitle export</opf:meta>'
        '<opf:meta name="description" content="text">국회 의사중계 자막 내보내기</opf:meta>'
        '<opf:meta name="lastsaveby" content="text">korea-assembly-cc</opf:meta>'
        f'<opf:meta name="CreatedDate" content="text">{created_utc}</opf:meta>'
        f'<opf:meta name="ModifiedDate" content="text">{created_utc}</opf:meta>'
        f'<opf:meta name="date" content="text">{escape(human_date)}</opf:meta>'
        '<opf:meta name="keyword" content="text">국회,자막,HWPX</opf:meta>'
        '</opf:metadata>'
        '<opf:manifest>'
        '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
        '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
        '<opf:item id="settings" href="settings.xml" media-type="application/xml"/>'
        '<opf:item id="preview-text" href="Preview/PrvText.txt" media-type="text/plain"/>'
        '</opf:manifest>'
        '<opf:spine><opf:itemref idref="header" linear="yes"/><opf:itemref idref="section0" linear="yes"/></opf:spine>'
        '</opf:package>'
    )


def build_hwpx_bytes(subtitles_snapshot: Sequence[tuple[datetime, str]], generated_at: datetime | None = None) -> bytes:
    generated = generated_at or datetime.now().astimezone()
    header_xml = _HEADER_TEMPLATE_PATH.read_text(encoding="utf-8")
    lines = build_hwpx_lines(subtitles_snapshot, generated)
    section_xml = build_section_xml(lines)
    preview_text = "\r\n".join(line.replace("\n", "\r\n") for line in lines).rstrip() + "\r\n"
    content_hpf = build_content_hpf(generated)
    settings_xml = (
        f"{_XML_DECL}"
        '<ha:HWPApplicationSetting xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
        'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0">'
        '<ha:CaretPosition listIDRef="0" paraIDRef="0" pos="16"/>'
        '</ha:HWPApplicationSetting>'
    )
    version_xml = (
        f"{_XML_DECL}"
        '<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" '
        'tagetApplication="WORDPROCESSOR" major="5" minor="0" micro="5" buildNumber="0" '
        'os="1" xmlVersion="1.4" application="Hancom Office Hangul" '
        'appVersion="9, 1, 1, 5656 WIN32LEWindows_Unknown_Version"/>'
    )
    container_xml = (
        f"{_XML_DECL}"
        '<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container" '
        'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf">'
        '<ocf:rootfiles>'
        '<ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>'
        '<ocf:rootfile full-path="Preview/PrvText.txt" media-type="text/plain"/>'
        '</ocf:rootfiles>'
        '</ocf:container>'
    )
    manifest_xml = (
        f"{_XML_DECL}"
        '<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>'
    )

    from io import BytesIO

    buffer = BytesIO()
    with ZipFile(buffer, mode="w") as archive:
        archive.writestr("mimetype", "application/hwp+zip", compress_type=ZIP_STORED)
        archive.writestr("version.xml", version_xml)
        archive.writestr("Contents/header.xml", header_xml)
        archive.writestr("Contents/section0.xml", section_xml)
        archive.writestr("Contents/content.hpf", content_hpf)
        archive.writestr("settings.xml", settings_xml)
        archive.writestr("Preview/PrvText.txt", preview_text)
        archive.writestr("META-INF/container.xml", container_xml)
        archive.writestr("META-INF/manifest.xml", manifest_xml)
    return buffer.getvalue()


def save_hwpx_document(filepath: str | Path, subtitles_snapshot: Sequence[tuple[datetime, str]], generated_at: datetime | None = None) -> None:
    atomic_write_bytes(filepath, build_hwpx_bytes(subtitles_snapshot, generated_at))
