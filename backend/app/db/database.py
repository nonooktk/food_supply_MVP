"""database.py — SQLAlchemy エンジン／セッションの生成（DB_BACKEND シーム連携）。

``app.config.Settings.resolve_database_url()`` が解決した接続URLでエンジンを作る。
SQLite のときは同一プロセス内テスト・スレッド共有のため connect_args を補う。
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import DbBackend, Settings, get_settings


def create_db_engine(settings: Settings | None = None) -> Engine:
    """設定に基づき SQLAlchemy エンジンを生成する。"""
    settings = settings or get_settings()
    url = settings.resolve_database_url()
    connect_args = settings.database_connect_args()

    if settings.db_backend is DbBackend.SQLITE:
        # SQLite は既定でスレッドを跨げないため、同一接続を許可する。
        connect_args = {**connect_args, "check_same_thread": False}

    engine = create_engine(url, connect_args=connect_args, future=True, pool_pre_ping=True)

    if settings.db_backend is DbBackend.SQLITE:
        # SQLite は既定で外部キー制約が無効。テナントスコープ FK を効かせるため有効化する。
        @event.listens_for(engine, "connect")
        def _enable_sqlite_fk(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """プロセス内で 1 度だけエンジンを生成してキャッシュする。"""
    return create_db_engine()


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    """セッションファクトリを返す。"""
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False, future=True)


def get_session() -> Iterator[Session]:
    """FastAPI 依存性注入用のセッションジェネレータ。"""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
