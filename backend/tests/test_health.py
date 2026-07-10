"""test_health.py — /api/health のユニットテスト。

外部依存を持たないため、TestClient で in-process 実行して 200 と本文を検証する。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_200() -> None:
    """/api/health が 200 と status=ok を返すこと。"""
    client = TestClient(create_app())
    res = client.get("/api/health")

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["service"] == "freeradicals-backend"
    # 既定の DB バックエンドは sqlite。
    assert body["db_backend"] == "sqlite"
