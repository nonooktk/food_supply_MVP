"""test_config_db_url.py — DB_BACKEND シームの接続URL解決テスト。

レビュー指摘 F: user / password に記号が含まれても壊れないよう urllib.parse.quote_plus で
エンコードされることを検証する。
"""

from __future__ import annotations

import pytest

from app.config import Settings


def _mysql_settings(monkeypatch: pytest.MonkeyPatch, user: str, password: str) -> Settings:
    monkeypatch.setenv("DB_BACKEND", "mysql")
    monkeypatch.setenv("DB_HOST", "db.example.com")
    monkeypatch.setenv("DB_PORT", "3306")
    monkeypatch.setenv("DB_NAME", "freeradicals")
    monkeypatch.setenv("DB_USER", user)
    monkeypatch.setenv("DB_PASSWORD", password)
    # .env の混入を避けて環境変数のみで構築する。
    return Settings(_env_file=None)


def test_mysql_url_encodes_symbol_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """記号入りの user / password が URL エンコードされること。"""
    s = _mysql_settings(monkeypatch, user="user@corp", password="p@ss:w/rd#1")
    url = s.resolve_database_url()

    # エンコード済みの値が入る
    assert "user%40corp" in url
    assert "p%40ss%3Aw%2Frd%231" in url
    # 生の記号はそのまま現れない（URL 構造を壊さない）
    assert "p@ss:w/rd#1" not in url
    # ホスト以降の区切りは保たれる
    assert url.endswith("@db.example.com:3306/freeradicals")
    assert url.startswith("mysql+pymysql://")


def test_mysql_url_plain_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """記号を含まない資格情報はそのまま組み立てられること（回帰防止）。"""
    s = _mysql_settings(monkeypatch, user="admin", password="secret123")
    assert s.resolve_database_url() == "mysql+pymysql://admin:secret123@db.example.com:3306/freeradicals"


def test_postgresql_url_encodes_symbol_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """postgresql 経路でも user / password がエンコードされること。"""
    monkeypatch.setenv("DB_BACKEND", "postgresql")
    monkeypatch.setenv("PG_HOST", "pg.example.com")
    monkeypatch.setenv("PG_USER", "u@ser")
    monkeypatch.setenv("PG_PASSWORD", "a/b@c")
    s = Settings(_env_file=None)
    url = s.resolve_database_url()
    assert "u%40ser" in url
    assert "a%2Fb%40c" in url
    assert url.startswith("postgresql+psycopg://")


def test_sqlite_relative_path_resolved_to_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """相対 SQLITE_PATH は CWD 非依存で backend ディレクトリ基準の絶対パスへ解決される。"""
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    monkeypatch.setenv("SQLITE_PATH", "./freeradicals.db")
    s = Settings(_env_file=None)
    url = s.resolve_database_url()
    # 絶対パス（sqlite:/// + 先頭 / で4スラッシュ）・backend/ 直下の freeradicals.db を指す。
    assert url.startswith("sqlite:////")
    assert url.endswith("/freeradicals.db")
    assert "/backend/" in url


def test_sqlite_absolute_path_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """絶対 SQLITE_PATH はそのまま使う（既存挙動を壊さない）。"""
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    monkeypatch.setenv("SQLITE_PATH", "/tmp/foo.db")
    s = Settings(_env_file=None)
    assert s.resolve_database_url() == "sqlite:////tmp/foo.db"


def test_sqlite_memory_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """:memory: はパス解決しない。"""
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    monkeypatch.setenv("SQLITE_PATH", ":memory:")
    s = Settings(_env_file=None)
    assert s.resolve_database_url() == "sqlite:///:memory:"
