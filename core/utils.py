# -*- coding: utf-8 -*-

from core.export_text import (
    format_cue_timestamp_from_seconds,
    format_srt_relative,
    format_srt_timestamp,
    format_vtt_relative,
    format_vtt_timestamp,
    normalize_hwp_insert_text,
    resolve_cue_time_range,
    sanitize_document_text,
    sanitize_subtitle_cue_text,
    strip_illegal_xml_chars,
)
from core.file_io import (
    atomic_write_bytes,
    atomic_write_bytes_via_writer,
    atomic_write_json,
    atomic_write_json_stream,
    atomic_write_text,
    atomic_write_text_via_writer,
    iter_serialized_subtitles,
    next_available_path,
)
from core.reflow import reflow_subtitles
from core.text_utils import (
    _find_match_with_window,
    clean_text,
    clean_text_display,
    compact_subtitle_text,
    flatten_subtitle_text,
    find_compact_suffix_prefix_overlap,
    find_list_overlap,
    generate_filename,
    get_word_diff,
    is_continuation_text,
    is_meaningful_subtitle_text,
    is_redundant_text,
    is_similar_subtitle,
    normalize_subtitle_text,
    same_leading_context,
    slice_from_compact_index,
)
