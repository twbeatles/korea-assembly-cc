# -*- coding: utf-8 -*-

from core.file_io import (
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_json_stream,
    atomic_write_text,
    iter_serialized_subtitles,
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
