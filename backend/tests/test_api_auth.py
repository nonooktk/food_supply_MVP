"""test_api_auth.py — モック認証（ログイン / me / ヘッダー依存）のテスト。"""

from __future__ import annotations


def test_login_resolves_tenant(api) -> None:
    """ログインは（単一テナントのデモでは）テナントを解決して tenantId を返す。"""
    res = api.client.post(
        "/api/auth/login", json={"tenant": "freeradicals", "userId": "tanaka", "password": "demo1234"}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["tenantId"] == api.tenant_id
    assert body["userId"] == "tanaka"
    assert body["role"] == "member"


def test_login_rejects_empty_credentials(api) -> None:
    res = api.client.post("/api/auth/login", json={"tenant": "x", "userId": "", "password": ""})
    assert res.status_code == 401
    assert res.headers["content-type"] == "application/problem+json"


def test_me_returns_header_identity(api) -> None:
    res = api.client.get("/api/me", headers=api.headers())
    assert res.status_code == 200
    assert res.json()["tenantId"] == api.tenant_id


def test_missing_tenant_header_is_401(api) -> None:
    res = api.client.get("/api/cases", headers={"X-User-Id": "tanaka"})
    assert res.status_code == 401
    assert res.headers["content-type"] == "application/problem+json"


def test_unknown_tenant_is_403(api) -> None:
    res = api.client.get("/api/cases", headers={"X-Tenant-Id": "not-a-tenant", "X-User-Id": "x"})
    assert res.status_code == 403
