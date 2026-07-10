"""test_db_isolation.py — テストが実 DB（開発用 freeradicals.db）に触れないことを固定する。

conftest の _isolate_sqlite_from_real_db により、実エンジン（get_engine / get_sessionmaker）の
接続先が一時 DB へ隔離されていることを検証する（テスト分離の漏れの回帰防止）。
"""

from __future__ import annotations

from app.config import get_settings
from app.db.database import get_engine, get_sessionmaker


def test_real_engine_points_to_tmp_not_dev_db() -> None:
    """実エンジンの接続先が一時 DB（frd_isolated_db 配下）であり、開発用 DB ではないこと。"""
    url = str(get_engine().url)
    resolved = get_settings().resolved_sqlite_path()
    # 隔離された一時 DB を指す。
    assert "frd_isolated_db" in resolved
    assert resolved.endswith("test.db")
    assert "frd_isolated_db" in url
    # 開発用 DB（backend/freeradicals.db）は指さない。
    assert not resolved.endswith("backend/freeradicals.db")


def test_sessionmaker_uses_isolated_engine() -> None:
    """get_sessionmaker のバインド先も隔離エンジンであること。"""
    bind_url = str(get_sessionmaker().kw["bind"].url)
    assert "frd_isolated_db" in bind_url
