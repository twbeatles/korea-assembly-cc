# -*- coding: utf-8 -*-

import re
from datetime import datetime
from typing import Optional
from core.config import Config

def clean_text(text: str) -> str:
    """자막 텍스트 정리 (성능 최적화: 사전 컴파일된 정규식 사용)"""
    if not text:
        return ""
    # 년도 제거
    text = Config.RE_YEAR.sub('', text)
    # 특수 문자 정리 (Zero-width 문자 제거)
    text = Config.RE_ZERO_WIDTH.sub('', text)
    # 연속 공백 정리
    text = Config.RE_MULTI_SPACE.sub(' ', text)
    return text.strip()

def normalize_subtitle_text(text: str) -> str:
    """자막 비교용 정규화 (공백 정리)"""
    if not text:
        return ""
    return Config.RE_MULTI_SPACE.sub(' ', text).strip()

def compact_subtitle_text(text: str) -> str:
    """겹침/중복 판별용 정규화 (공백 제거 + zero-width 제거)"""
    if not text:
        return ""
    text = Config.RE_ZERO_WIDTH.sub('', text)
    return Config.RE_MULTI_SPACE.sub('', text).strip()

def slice_from_compact_index(text: str, compact_index: int) -> str:
    """compact 인덱스(공백 제거 기준) 위치부터 원문 슬라이스를 반환"""
    if not text:
        return ""
    if compact_index <= 0:
        return text

    text = Config.RE_ZERO_WIDTH.sub('', text)
    count = 0
    for i, ch in enumerate(text):
        if ch.isspace():
            continue
        if count >= compact_index:
            return text[i:]
        count += 1
    return ""

def find_compact_suffix_prefix_overlap(last_compact: str, text_compact: str,
                                       min_overlap: int = 10, max_overlap: int = 500) -> int:
    """last_compact의 suffix와 text_compact의 prefix가 겹치는 최대 길이(공백 무시)를 반환"""
    if not last_compact or not text_compact:
        return 0
    max_possible = min(len(last_compact), len(text_compact), max_overlap)
    for overlap_len in range(max_possible, min_overlap - 1, -1):
        if last_compact.endswith(text_compact[:overlap_len]):
            return overlap_len
    return 0

def is_redundant_text(candidate: str, last_text: str) -> bool:
    """이미 확정된 자막과 중복/포함 관계인지 판단"""
    cand_norm = normalize_subtitle_text(candidate)
    last_norm = normalize_subtitle_text(last_text)
    if not cand_norm or not last_norm:
        return False
    if cand_norm == last_norm:
        return True
    if len(cand_norm) <= len(last_norm) and cand_norm in last_norm:
        return True

    # 공백 차이(예: "국 장" vs "국장")로 인해 중복/포함 판단이 실패하는 케이스 보완
    cand_compact = compact_subtitle_text(candidate)
    last_compact = compact_subtitle_text(last_text)
    if cand_compact and last_compact:
        if cand_compact == last_compact:
            return True
        return len(cand_compact) <= len(last_compact) and cand_compact in last_compact
    return False

def generate_filename(committee_name: str, extension: str, now: Optional[datetime] = None) -> str:
    """스마트 파일명 생성"""
    if now is None:
        now = datetime.now()
    
    date_str = now.strftime(Config.FILENAME_DATE_FORMAT)
    time_str = now.strftime(Config.FILENAME_TIME_FORMAT)
    
    # 위원회명이 없으면 기본값 사용
    if not committee_name:
        committee_name = "국회자막"
    
    # 파일명에 사용할 수 없는 문자 제거
    safe_committee = re.sub(r'[\\/*?:"<>|]', '', committee_name)
    
    # 템플릿 기반 파일명 생성
    filename = Config.DEFAULT_FILENAME_TEMPLATE.format(
        date=date_str,
        committee=safe_committee,
        time=time_str
    )
    
    return f"{filename}.{extension}"

def is_similar_subtitle(text1: str, text2: str, threshold: float = 0.9) -> bool:
    """두 자막이 유사한지 판단 (Jaccard 유사도)"""
    norm1 = compact_subtitle_text(text1)
    norm2 = compact_subtitle_text(text2)
    
    if norm1 == norm2:
        return True
    
    # 문자 단위 Jaccard 유사도
    set1, set2 = set(norm1), set(norm2)
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    
    return (intersection / union) >= threshold if union > 0 else False

def same_leading_context(a: str, b: str, take: int = 20) -> bool:
    """실시간 자막이 같은 흐름인지(앞부분이 유지되는지) 공백 무시로 판별"""
    a_compact = compact_subtitle_text(a)
    b_compact = compact_subtitle_text(b)
    prefix_len = min(take, len(a_compact), len(b_compact))
    if prefix_len <= 0:
        return True
    return a_compact[:prefix_len] == b_compact[:prefix_len]

def is_continuation_text(previous: str, current: str) -> bool:
    """이전 raw 대비 현재 raw가 같은 흐름의 업데이트인지(윈도우 슬라이딩 포함) 판별"""
    prev_compact = compact_subtitle_text(previous)
    cur_compact = compact_subtitle_text(current)
    if not prev_compact or not cur_compact:
        return True

    # 포함 관계면 같은 흐름(확장/축약/공백차)
    if prev_compact in cur_compact or cur_compact in prev_compact:
        return True

    # 이전 텍스트의 최근 tail이 현재에 포함되면 같은 흐름(앞부분이 슬라이딩되어도 유지)
    tail_len = min(60, len(prev_compact))
    if tail_len >= 15 and prev_compact[-tail_len:] in cur_compact:
        return True

    # 앞부분이 유사하면 같은 흐름
    prefix_len = min(30, len(prev_compact), len(cur_compact))
    if prefix_len >= 15 and prev_compact[:prefix_len] == cur_compact[:prefix_len]:
        return True

    return False
