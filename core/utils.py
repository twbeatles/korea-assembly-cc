# -*- coding: utf-8 -*-

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union
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

def clean_text_display(text: str) -> str:
    """표시/저장용 텍스트 정리 (공백 유지)"""
    if not text:
        return ""
    text = Config.RE_YEAR.sub('', text)
    text = Config.RE_ZERO_WIDTH.sub('', text)
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
                                       min_overlap: int = 10, max_overlap: int = None) -> int:
    """last_compact의 suffix와 text_compact의 prefix가 겹치는 최대 길이(공백 무시)를 반환"""
    if max_overlap is None:
        max_overlap = Config.MAX_WORD_DIFF_OVERLAP  # 성능 최적화 (#1)
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

def find_list_overlap(existing: list[str], new_items: list[str]) -> int:
    """기존 리스트의 끝부분과 새 리스트의 앞부분이 겹치는 길이를 반환"""
    if not existing or not new_items:
        return 0
    max_check = min(len(existing), len(new_items))
    for i in range(max_check, 0, -1):
        if existing[-i:] == new_items[:i]:
            return i
    return 0

def _find_match_with_window(last_compact: str, new_compact: str, window_size: int = 20) -> int:
    """
    last_compact의 끝에서부터 윈도우 단위로 끊어 new_compact에서 검색
    
    Returns:
        int: new_compact 내에서 매칭된 부분의 끝 인덱스 (매칭 실패 시 -1)
    """
    if not last_compact or not new_compact:
        return -1
        
    n = len(last_compact)
    # 뒤에서부터 검색 (stride 3 - 촘촘하게 검색하여 정확도 향상)
    # 너무 많이 검색하면 성능 저하되므로 최대 200자까지만 뒤로 탐색
    limit = max(0, n - 200)
    
    for i in range(n, limit, -3):
        start = max(0, i - window_size)
        window = last_compact[start:i]
        
        if len(window) < 10: # 윈도우가 너무 작으면 오탐 가능성 높음
            break
            
        pos = new_compact.rfind(window)
        if pos != -1:
            # 매칭 성공! 해당 윈도우의 끝 위치 반환
            return pos + len(window)
            
    return -1

def get_word_diff(last_text: str, new_text: str) -> str:
    """
    이전 텍스트(last_text)와 새 텍스트(new_text)를 '단어 단위'로 비교하여
    새롭게 추가된 부분만 반환한다.
    
    웹페이지에서 자막이 누적/반복되는 경우를 처리:
    1) 단순 startswith 비교
    2) last_text가 new_text 내에 포함된 경우 rfind로 마지막 위치 감지
    3) 단어 단위 overlap 비교 (띄어쓰기 변화 대응)
    4) compact 기반 rfind 매칭 (공백 무시)
    5) 슬라이딩 윈도우 감지 (앞부분 탈락 케이스)
    6) 완전히 새로운 문장이면 전체 반환
    """
    if not last_text:
        return new_text
    if not new_text:
        return ""
        
    last_text = clean_text_display(last_text)
    new_text = clean_text_display(new_text)

    # 1. 완전 중복 또는 포함 관계면 빈 문자열 (Flicker 방지)
    if is_redundant_text(new_text, last_text):
        return ""

    # 2. 단순 텍스트 확장 (가장 빠름)
    if new_text.startswith(last_text):
        return new_text[len(last_text):].strip()

    # 3. [NEW] last_text가 new_text 내에 포함된 경우 - rfind로 마지막 위치 찾기
    # 웹에서 누적된 텍스트에서 last_text 이후의 새 내용만 추출
    # 예: last="A B C", new="X A B C D E" -> delta="D E"
    if last_text in new_text:
        last_pos = new_text.rfind(last_text)
        if last_pos >= 0:
            delta = new_text[last_pos + len(last_text):].strip()
            if delta:
                return delta
            # last_text가 new_text의 끝부분이면 새 내용 없음
            return ""

    # 4. 단어 단위 분석
    # 공백 기준으로 단어 분리
    last_words = last_text.split()
    new_words = new_text.split()
    
    # 겹치는 부분 찾기
    overlap_count = find_list_overlap(last_words, new_words)
    
    if overlap_count > 0:
        # 겹치는 단어 이후의 단어들만 추출
        added_words = new_words[overlap_count:]
        if added_words:
            return " ".join(added_words)
        else:
            return ""

    # 5. [NEW] compact 기반 rfind 매칭 - 공백 무시하고 포함 관계 감지
    # 예: last="A B C", new="X A  B  C D E" (공백 다름) -> delta="D E"
    last_compact = compact_subtitle_text(last_text)
    new_compact = compact_subtitle_text(new_text)
    
    if last_compact and new_compact and last_compact in new_compact:
        # compact 기준으로 마지막 위치 찾기
        compact_pos = new_compact.rfind(last_compact)
        if compact_pos >= 0:
            # compact 인덱스 이후의 원문 텍스트 추출
            delta = slice_from_compact_index(new_text, compact_pos + len(last_compact))
            if delta:
                return delta.strip()
            return ""
    
    # 6. [NEW] suffix 기반 매칭 - AI 자막 인식으로 텍스트가 약간씩 달라지는 경우
    # last_compact의 끝부분이 new_compact에 포함되면 그 이후만 반환
    # 예: last="...인수가 정당하다는 입장을 계속 얘기하는데"
    #     new="...인수가 정당하다는 그런 입장을 계속 얘기하는데 그러다 보니까"
    # -> 공통 suffix "입장을계속얘기하는데" 이후 "그러다 보니까"만 반환
    if last_compact and new_compact and len(last_compact) >= 10:
        # last_compact의 suffix를 new_compact에서 찾기 (최소 10자~최대 100자)
        for suffix_len in range(min(100, len(last_compact)), 9, -1):
            suffix = last_compact[-suffix_len:]
            pos = new_compact.rfind(suffix)
            if pos >= 0:
                # suffix 이후의 텍스트 추출
                delta = slice_from_compact_index(new_text, pos + suffix_len)
                if delta:
                    return delta.strip()
                return ""
    
    # 7. 슬라이딩 윈도우 감지 - 앞부분이 탈락하고 뒷부분이 유지되는 케이스
    # 예: last="A B C D", new="C D E F" -> delta="E F"
    overlap_len = find_compact_suffix_prefix_overlap(last_compact, new_compact, min_overlap=10)
    if overlap_len > 0:
        # 겹치는 부분 이후만 반환
        delta = slice_from_compact_index(new_text, overlap_len)
        return delta.strip() if delta else ""

    # 7. [NEW] 역방향 윈도우 매칭 (Reverse Window Matching)
    # 중간 내용이 수정되었거나(오타 등), 앞부분이 잘려나간 경우에도 대응
    # last_text의 끝부분 청크가 new_text 어딘가에 존재한다면, 그 이후가 새로운 내용임
    match_end_pos = _find_match_with_window(last_compact, new_compact, window_size=20)
    if match_end_pos != -1:
         # match_end_pos는 new_compact 기준 인덱스.
         # 원문 텍스트 슬라이싱 필요.
         delta = slice_from_compact_index(new_text, match_end_pos)
         # 만약 delta가 너무 짧으면(예: 점 하나), 무의미한 변경일 수 있음
         # 하지만 여기서는 일단 반환하고 상위 로직에서 판단하게 함
         if delta:
             return delta.strip()
         return ""

    # 8. 겹침 없음 -> 새 문장일 가능성 높음

    return new_text

def reflow_subtitles(subtitles: List[SubtitleEntry]) -> List[SubtitleEntry]:
    """
    자막 리스트를 재정렬(Reflow)합니다.
    
    기능:
    1. 텍스트 내 포함된 타임스탬프([HH:MM:SS])를 감지하여 새로운 자막 엔트리로 분리합니다.
    2. 문장 부호(. ? !) 기준으로 문장을 분리합니다.
    3. 문장 부호로 끝나지 않는 짧은 라인들을 병합합니다.
    """
    if not subtitles:
        return []

    # 1단계: 타임스탬프 파싱 및 텍스트 정규화
    expanded_entries = []
    
    # 타임스탬프 패턴: [HH:MM:SS]
    ts_pattern = re.compile(r'\[(\d{2}:\d{2}:\d{2})\]')
    
    # 텍스트 내 타임스탬프를 찾아서 분리
    for entry in subtitles:
        text = entry.text
        # 원본 타임스탬프의 날짜 부분 (시간은 텍스트에서 추출할 것이므로)
        base_date = entry.timestamp.date()
        current_timestamp = entry.timestamp
        
        last_pos = 0
        for match in ts_pattern.finditer(text):
            # 타임스탬프 이전 텍스트 처리
            pre_text = text[last_pos:match.start()].strip()
            if pre_text:
                # 이전 텍스트는 원본 엔트리의 시간(또는 직전 파싱된 시간)을 따름
                # 첫 덩어리면 원본 시간, 아니면 직전 분리된 시간...
                # 여기서는 단순화를 위해 첫 덩어리는 원본 시간을 씁니다.
                # (중간 텍스트의 정확한 시간 추정은 어려움)
                expanded_entries.append(SubtitleEntry(pre_text, current_timestamp))
            
            # 타임스탬프 시간 파싱
            ts_str = match.group(1)
            try:
                # 시:분:초 파싱
                parsed_time = datetime.strptime(ts_str, "%H:%M:%S").time()
                new_dt = datetime.combine(base_date, parsed_time)
                
                # 지금부터 나오는 텍스트는 이 시간을 따름
                # 타임스탬프 자체는 텍스트에서 제거하거나 유지할 수 있는데,
                # "자막 내용"으로서는 제거하는게 깔끔하겠지만
                # 사용자가 [14:00:00] 텍스트를 보길 원할 수도 있음.
                # 여기서는 "Start timestamp"로 사용하기 위해 텍스트에서는 제거하지 않고
                # 다음 텍스트 덩어리의 시작 시간으로 설정합니다.
                
                # 타임스탬프 텍스트 자체는 제거 (깔끔한 자막을 위해)
                # 입력 엔트리 원본은 수정하지 않고 로컬 타임스탬프만 갱신한다.
                current_timestamp = new_dt
                
            except ValueError:
                pass # 파싱 실패 시 무시
            
            last_pos = match.end()
        
        # 남은 텍스트
        remaining_text = text[last_pos:].strip()
        if remaining_text:
            expanded_entries.append(SubtitleEntry(remaining_text, current_timestamp))

    if not expanded_entries:
        return []

    # 2단계: 문장 단위 분리 (. ? ! 뒤에 공백이 있으면 분리)
    # 3단계: 병합 (문장이 안 끝난 경우)
    
    result_entries = []
    current_buffer = expanded_entries[0]
    
    for i in range(1, len(expanded_entries)):
        next_entry = expanded_entries[i]
        
        buffer_text = current_buffer.text.strip()
        
        # 2-1) 버퍼 텍스트가 여러 문장으로 구성된 경우 분리 시도
        # 예: "안녕하세요. 반갑습니다." -> "안녕하세요." / "반갑습니다."
        # 정규식으로 문장 종료 패턴 찾기: (. ? !) + 공백 + (대문자나 한글 등)
        # 한국어 문맥상 (. ? !) 뒤에 공백이면 자르는게 좋음
        
        # 먼저 버퍼를 문장 단위로 쪼갠다
        sentences = re.split(r'([.?!])\s+', buffer_text)
        # re.split 결과: ["문장1", ".", "문장2", "?", "나머지"]
        
        if len(sentences) > 1:
            # 첫 번째 문장은 확정 (현재 버퍼 시간 사용)
            # 나머지는 분리된 엔트리로 (시간은 동일하게 하거나 조금씩 뒤로 밀어야 함)
            
            # 재조립 (구분자 포함)
            real_sentences = []
            temp = ""
            for fragment in sentences:
                if fragment in ('.', '?', '!'):
                    temp += fragment
                    real_sentences.append(temp)
                    temp = ""
                else:
                    if temp: # 구분자가 없었던 이전 덩어리 처리 (혹시나해서)
                        real_sentences.append(temp)
                    temp = fragment
            if temp:
                real_sentences.append(temp)
                
            # 조립된 문장들을 result에 넣되, 마지막 문장은 다음 병합을 위해 남겨둠
            for idx, sent in enumerate(real_sentences):
                # 공백 정리
                sent = sent.strip()
                if not sent: continue
                
                if idx < len(real_sentences) - 1:
                    # 중간 문장들은 확정
                    result_entries.append(SubtitleEntry(sent, current_buffer.timestamp))
                else:
                    # 마지막 문장은 버퍼로 다시 설정
                    current_buffer = SubtitleEntry(sent, current_buffer.timestamp)
                    
        # 다시 buffer_text (마지막 조각) 갱신
        buffer_text = current_buffer.text.strip()
        
        # 문장 종료 확인
        enders = ('.', '?', '!')
        
        # 다음 문장이 타임스탬프에 의해 강제로 분리된(시간 차이가 큰) 경우라면 병합하지 않음
        time_diff = (next_entry.timestamp - current_buffer.timestamp).total_seconds()
        
        # 시간 차이가 크면(예: 3초 이상) 문장이 안 끝나도 병합하지 않고 분리하는게 나을 수 있음
        # 하지만 사용자는 "blob"을 해결하고 싶어하므로, 일단은 문법적 종결을 우선시함.
        # 단, 명시적으로 타임스탬프가 박혀서 분리된 entry라면 병합하지 않는게 맞을 수도 있음.
        # 기존 로직은 "이어붙이기"였음.
        
        if buffer_text.endswith(enders):
            # 문장 종료됨 -> 확정
            result_entries.append(current_buffer)
            current_buffer = next_entry
        else:
            # 문장 안끝남 -> 병합
            # 시간 차이가 너무 크면(10초 이상) 그냥 분리 (화자 전환 등일 수 있음)
            if time_diff > 10:
                result_entries.append(current_buffer)
                current_buffer = next_entry
            else:
                current_buffer.update_text(buffer_text + " " + next_entry.text.strip())
                # 시간은 시작 시간 유지, 종료 시간은 필요하다면 next_entry꺼 가져옴
                current_buffer.end_time = next_entry.end_time
    
    # 마지막 버퍼 처리
    if current_buffer and current_buffer.text.strip():
        # 마지막 버퍼도 문장 분리 체크
        buffer_text = current_buffer.text.strip()
        sentences = re.split(r'([.?!])\s+', buffer_text)
        real_sentences = []
        temp = ""
        for fragment in sentences:
            if fragment in ('.', '?', '!'):
                temp += fragment
                real_sentences.append(temp)
                temp = ""
            else:
                temp = fragment
        if temp:
            real_sentences.append(temp)
            
        for sent in real_sentences:
            if sent.strip():
                result_entries.append(SubtitleEntry(sent.strip(), current_buffer.timestamp))
    
    return result_entries
