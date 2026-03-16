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
