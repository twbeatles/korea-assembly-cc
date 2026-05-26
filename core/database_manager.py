"""
SQLite 데이터베이스 관리 모듈 (#26)

국회 의사중계 자막 추출기의 세션 데이터를 체계적으로 관리합니다.
"""

from core.database_impl.core import DatabaseCoreMixin
from core.database_impl.fts import DatabaseFtsMixin
from core.database_impl.schema import DatabaseSchemaMixin
from core.database_impl.search_stats import DatabaseSearchStatsMixin
from core.database_impl.sessions import DatabaseSessionMixin


class DatabaseManager(
    DatabaseCoreMixin,
    DatabaseSchemaMixin,
    DatabaseFtsMixin,
    DatabaseSessionMixin,
    DatabaseSearchStatsMixin,
):
    """자막 세션 데이터베이스 관리 클래스"""

    pass


__all__ = ["DatabaseManager"]
