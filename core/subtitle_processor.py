# -*- coding: utf-8 -*-
"""
자막 처리기 모듈 - 문장 해시 기반 중복 감지

웹에서 AI 자막이 누적/반복되는 경우를 처리하기 위한 새 알고리즘:
1. 마지막 문장만 추적
2. 해시 기반 중복 감지  
3. 시간 기반 확정
"""

import time
import hashlib
import re
from typing import Optional, List, Set
from dataclasses import dataclass, field
from core.config import Config


def _normalize_for_hash(text: str) -> str:
    """해시 비교용 텍스트 정규화 (공백/특수문자 제거)"""
    if not text:
        return ""
    # 공백, 줄바꿈, 특수문자 제거
    normalized = re.sub(r'\s+', '', text)
    # 숫자 제거 (년도 등)
    normalized = re.sub(r'\d{4}', '', normalized)
    return normalized.strip()


def _compute_hash(text: str) -> str:
    """텍스트의 해시값 계산"""
    normalized = _normalize_for_hash(text)
    if not normalized:
        return ""
    return hashlib.md5(normalized.encode('utf-8')).hexdigest()[:16]


def _extract_last_sentence(text: str) -> str:
    """텍스트에서 마지막 문장 추출
    
    줄바꿈 기준으로 마지막 비어있지 않은 줄 반환
    """
    if not text:
        return ""
    
    lines = text.strip().split('\n')
    # 뒤에서부터 비어있지 않은 줄 찾기
    for line in reversed(lines):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _extract_sentences(text: str) -> List[str]:
    """텍스트를 문장 단위로 분리
    
    줄바꿈 기준으로 분리하고, 빈 줄 제거
    """
    if not text:
        return []
    
    lines = text.strip().split('\n')
    return [line.strip() for line in lines if line.strip()]


@dataclass
class SubtitleProcessor:
    """문장 해시 기반 자막 처리기
    
    웹에서 누적/반복되는 자막을 처리하여 새 문장만 추출
    """
    
    # 확정된 문장 해시 (중복 방지용)
    confirmed_hashes: Set[str] = field(default_factory=set)
    
    # 확정된 문장 텍스트 (마지막 N개만 유지, suffix 매칭용)
    confirmed_sentences: List[str] = field(default_factory=list)
    
    # 현재 진행 중인 문장
    current_sentence: str = ""
    
    # 마지막 업데이트 시간
    last_update: float = 0.0
    
    # 이전에 처리한 전체 텍스트 (변화 감지용)
    last_raw_text: str = ""
    
    # 설정
    finalize_delay: float = 2.0  # 확정 대기 시간 (초)
    max_confirmed_sentences: int = 100  # 유지할 최대 확정 문장 수
    min_sentence_length: int = 5  # 최소 문장 길이
    
    def process(self, raw_text: str) -> Optional[str]:
        """새 텍스트를 처리하고, 확정된 문장이 있으면 반환
        
        Args:
            raw_text: 웹에서 가져온 전체 자막 텍스트
            
        Returns:
            확정된 새 문장 (없으면 None)
        """
        if not raw_text or not raw_text.strip():
            return None
            
        raw_text = raw_text.strip()
        
        # 전체 텍스트가 동일하면 스킵
        if raw_text == self.last_raw_text:
            return None
        
        self.last_raw_text = raw_text
        
        # 마지막 문장 추출
        last_sentence = _extract_last_sentence(raw_text)
        
        if not last_sentence or len(last_sentence) < self.min_sentence_length:
            return None
        
        # 이미 확정된 문장인지 체크 (해시 기반)
        sentence_hash = _compute_hash(last_sentence)
        if sentence_hash and sentence_hash in self.confirmed_hashes:
            return None
        
        # 현재 문장과 비교
        if last_sentence == self.current_sentence:
            # 동일 문장 - 시간만 업데이트 (타이머가 확정 처리)
            return None
        
        # 새 문장 감지 - 이전 문장을 즉시 확정
        now = time.time()
        confirmed = None
        
        # [FIX] 이전 문장이 있으면 즉시 확정 (2초 대기 없이)
        # 자막이 빠르게 변하면 중간 문장 누락 방지
        if self.current_sentence:
            confirmed = self._confirm_current()
        
        # 현재 문장 업데이트
        self.current_sentence = last_sentence
        self.last_update = now
        
        return confirmed
    
    def _should_finalize(self, now: float) -> bool:
        """현재 문장을 확정해야 하는지 판단"""
        if not self.current_sentence:
            return False
        if self.last_update <= 0:
            return False
        return (now - self.last_update) >= self.finalize_delay
    
    def _confirm_current(self) -> Optional[str]:
        """현재 문장을 확정하고 반환"""
        sentence = self.current_sentence
        if not sentence:
            return None
        
        sentence_hash = _compute_hash(sentence)
        
        # 이미 확정된 문장이면 스킵
        if sentence_hash in self.confirmed_hashes:
            self.current_sentence = ""
            return None
        
        # 확정 처리
        if sentence_hash:
            self.confirmed_hashes.add(sentence_hash)
        
        self.confirmed_sentences.append(sentence)
        
        # 메모리 관리 - 오래된 문장 제거
        if len(self.confirmed_sentences) > self.max_confirmed_sentences:
            removed = self.confirmed_sentences.pop(0)
            removed_hash = _compute_hash(removed)
            if removed_hash in self.confirmed_hashes:
                self.confirmed_hashes.discard(removed_hash)
        
        self.current_sentence = ""
        return sentence
    
    def check_finalize(self) -> Optional[str]:
        """타이머에서 호출 - 시간 경과 시 현재 문장 확정
        
        Returns:
            확정된 문장 (없으면 None)
        """
        now = time.time()
        if self._should_finalize(now):
            return self._confirm_current()
        return None
    
    def force_finalize(self) -> Optional[str]:
        """강제 확정 (중지 시 호출)
        
        Returns:
            확정된 문장 (없으면 None)
        """
        return self._confirm_current()
    
    def reset(self) -> None:
        """상태 초기화"""
        self.confirmed_hashes.clear()
        self.confirmed_sentences.clear()
        self.current_sentence = ""
        self.last_update = 0.0
        self.last_raw_text = ""
    
    def is_duplicate(self, text: str) -> bool:
        """텍스트가 이미 확정된 문장인지 확인"""
        if not text:
            return False
        text_hash = _compute_hash(text)
        return text_hash in self.confirmed_hashes
    
    def add_confirmed(self, sentence: str) -> None:
        """외부에서 확정된 문장을 수동으로 등록
        
        Args:
            sentence: 확정된 문장 텍스트
        """
        if not sentence:
            return
            
        sentence_hash = _compute_hash(sentence)
        
        # 이미 확정된 문장이면 스킵
        if sentence_hash in self.confirmed_hashes:
            return
        
        # 확정 처리
        if sentence_hash:
            self.confirmed_hashes.add(sentence_hash)
        
        self.confirmed_sentences.append(sentence)
        
        # 메모리 관리 - 오래된 문장 제거
        if len(self.confirmed_sentences) > self.max_confirmed_sentences:
            removed = self.confirmed_sentences.pop(0)
            removed_hash = _compute_hash(removed)
            if removed_hash in self.confirmed_hashes:
                self.confirmed_hashes.discard(removed_hash)
    
    def is_duplicate_input(self, raw_text: str) -> bool:
        """입력된 Raw Text의 마지막 문장이 이미 확정된 것인지 확인"""
        if not raw_text:
            return False
            
        last_sentence = _extract_last_sentence(raw_text)
        if not last_sentence or len(last_sentence) < self.min_sentence_length:
            return False
            
        return self.is_duplicate(last_sentence)

    def get_stats(self) -> dict:
        """통계 정보 반환"""
        return {
            "confirmed_count": len(self.confirmed_sentences),
            "hash_count": len(self.confirmed_hashes),
            "current_sentence_len": len(self.current_sentence),
            "has_pending": bool(self.current_sentence),
        }
