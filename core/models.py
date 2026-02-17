# -*- coding: utf-8 -*-

from datetime import datetime
from typing import Optional, Dict, Any

class SubtitleEntry:
    """자막 항목 - 타입 힌트 포함, 성능 최적화: 통계 캐싱"""
    
    def __init__(self, text: str, timestamp: Optional[datetime] = None):
        self.text: str = text
        self.timestamp: datetime = timestamp or datetime.now()
        self.start_time: Optional[datetime] = None  # SRT용
        self.end_time: Optional[datetime] = None    # SRT용
        # 성능 최적화: 통계 캐시 필드
        self._char_count: int = len(text)
        self._word_count: int = len(text.split())
    
    @property
    def char_count(self) -> int:
        """캐시된 글자 수 반환"""
        return self._char_count
    
    @property
    def word_count(self) -> int:
        """캐시된 단어 수 반환"""
        return self._word_count
    
    def update_text(self, new_text: str) -> None:
        """텍스트 업데이트 시 캐시도 갱신"""
        self.text = new_text
        self._char_count = len(new_text)
        self._word_count = len(new_text.split())
    
    def append(self, additional_text: str, separator: str = " ") -> None:
        """텍스트 이어붙이기 - 캐시 자동 갱신 (#8)
        
        Args:
            additional_text: 추가할 텍스트
            separator: 구분자 (기본: 공백)
        """
        if additional_text:
            self.update_text(self.text + separator + additional_text)
            self.end_time = datetime.now()
    
    def to_dict(self) -> Dict[str, Optional[str]]:
        """딕셔너리로 변환 (세션 저장용)"""
        return {
            'text': self.text,
            'timestamp': self.timestamp.isoformat(),
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SubtitleEntry':
        """딕셔너리에서 생성 - 방어 코드 포함"""
        # 필수 필드 검증
        text = data.get('text', '')
        timestamp_str = data.get('timestamp')
        
        if not text:
            raise ValueError("자막 텍스트가 비어있습니다")
        if not timestamp_str:
            raise ValueError("타임스탬프가 없습니다")
        
        entry = cls(text)
        entry.timestamp = datetime.fromisoformat(timestamp_str)
        if data.get('start_time'):
            entry.start_time = datetime.fromisoformat(data['start_time'])
        if data.get('end_time'):
            entry.end_time = datetime.fromisoformat(data['end_time'])
        return entry


# ============================================================
# 메인 윈도우
# ============================================================

