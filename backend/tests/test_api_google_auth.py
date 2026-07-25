"""test_api_google_auth.py — Google 認証（AUTH_MODE=google）と認証シーム分岐のテスト。

実 Google トークンは使わず、id_token.verify_oauth2_token をモック化して検証する。

2026-07-26 セキュリティ監査（F-2/F-16）対応で、google モードには
「ALLOWED_EMAILS の allowlist に載った、email_verified=True のアカウントのみ許可」
という関門が入った。本ファイルの google_mode フィクスチャ・モッククレームはそれに追随している。
"""

from __future__ import annotations

import pytest

from app.config import get_settings

# 許可済みのテストアカウント（allowlist に載せる email）。
ALLOWED_EMAIL = "tanaka@example.com"


@pytest.fixture()
def google_mode(monkeypatch: pytest.MonkeyPatch):
    """AUTH_MODE=google・GOOGLE_CLIENT_ID・ALLOWED_EMAILS 設定済みに切り替える（後に自動復元）。"""
    s = get_settings()
    monkeypatch.setattr(s, "auth_mode", "google")
    monkeypatch.setattr(s, "google_client_id", "test-client.apps.googleusercontent.com")
    monkeypatch.setattr(s, "allowed_emails_raw", ALLOWED_EMAIL)


def _mock_verify(monkeypatch: pytest.MonkeyPatch, claims: dict) -> None:
    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token", lambda *a, **k: claims
    )


def test_google_login_success(api, google_mode, monkeypatch: pytest.MonkeyPatch) -> None:
    """検証成功: allowlist 済み email を user_id、既定テナントに紐付けて AuthUser を返す。"""
    _mock_verify(
        monkeypatch,
        {"sub": "g-123", "email": ALLOWED_EMAIL, "email_verified": True, "name": "田中 太郎"},
    )
    res = api.client.post("/api/auth/google", json={"credential": "header.payload.sig"})
    assert res.status_code == 200
    body = res.json()
    assert body["tenantId"] == api.tenant_id  # 既定テナントに紐付け
    assert body["userId"] == ALLOWED_EMAIL
    assert body["displayName"] == "田中 太郎"


def test_google_login_rejects_email_outside_allowlist(
    api, google_mode, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[F-2] allowlist 外の検証済みアカウントは 403（既定テナントに入れない）。"""
    _mock_verify(
        monkeypatch,
        {"sub": "g-999", "email": "stranger@gmail.com", "email_verified": True, "name": "赤の他人"},
    )
    res = api.client.post("/api/auth/google", json={"credential": "header.payload.sig"})
    assert res.status_code == 403
    assert res.headers["content-type"] == "application/problem+json"


def test_google_login_rejects_unverified_email(
    api, google_mode, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[F-16] allowlist に載っていても email_verified が True でなければ 403。"""
    _mock_verify(
        monkeypatch,
        {"sub": "g-123", "email": ALLOWED_EMAIL, "email_verified": False, "name": "田中 太郎"},
    )
    res = api.client.post("/api/auth/google", json={"credential": "header.payload.sig"})
    assert res.status_code == 403


def test_google_login_allowlist_is_case_insensitive(
    api, google_mode, monkeypatch: pytest.MonkeyPatch
) -> None:
    """allowlist 照合は大文字小文字を区別しない（設定ゆれで締め出さない）。"""
    _mock_verify(
        monkeypatch,
        {"sub": "g-123", "email": "Tanaka@Example.COM", "email_verified": True, "name": "田中"},
    )
    res = api.client.post("/api/auth/google", json={"credential": "header.payload.sig"})
    assert res.status_code == 200
    assert res.json()["userId"] == ALLOWED_EMAIL


def test_google_login_invalid_token(api, google_mode, monkeypatch: pytest.MonkeyPatch) -> None:
    """検証失敗（署名不正等）は 401。"""
    def _raise(*a, **k):
        raise ValueError("bad signature")

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", _raise)
    res = api.client.post("/api/auth/google", json={"credential": "bad"})
    assert res.status_code == 401
    assert res.headers["content-type"] == "application/problem+json"


def test_google_login_requires_client_id(api, monkeypatch: pytest.MonkeyPatch) -> None:
    """GOOGLE_CLIENT_ID 未設定なら検証不可で 401。"""
    s = get_settings()
    monkeypatch.setattr(s, "auth_mode", "google")
    monkeypatch.setattr(s, "google_client_id", "")
    res = api.client.post("/api/auth/google", json={"credential": "x"})
    assert res.status_code == 401


def test_google_disabled_in_mock_mode(api) -> None:
    """AUTH_MODE=mock（既定）では Google ログインは 403。"""
    res = api.client.post("/api/auth/google", json={"credential": "x"})
    assert res.status_code == 403


def test_mock_login_disabled_in_google_mode(api, google_mode) -> None:
    """AUTH_MODE=google ではモックログインは 403（シームの排他）。"""
    res = api.client.post(
        "/api/auth/login", json={"tenant": "x", "userId": "tanaka", "password": "demo1234"}
    )
    assert res.status_code == 403


def test_mock_login_works_by_default(api) -> None:
    """既定（mock）ではモックログインが成功する（回帰）。"""
    res = api.client.post(
        "/api/auth/login", json={"tenant": "freeradicals", "userId": "tanaka", "password": "demo1234"}
    )
    assert res.status_code == 200
    assert res.json()["tenantId"] == api.tenant_id


def test_clock_skew_passed_to_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    """ホットフィックス検証: verify_oauth2_token に clock_skew_in_seconds=10 が渡ること。

    ローカル機の時計ズレによる「Token used too early」対策（コーディネーターのホットフィックス）。
    """
    from app.auth.google import verify_google_credential

    monkeypatch.setattr(get_settings(), "google_client_id", "test-client.apps.googleusercontent.com")

    captured: dict = {}

    def _spy(credential, request, client_id, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return {"sub": "g-1", "email": "u@example.com", "name": "U"}

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", _spy)
    identity = verify_google_credential("header.payload.sig")
    assert captured.get("clock_skew_in_seconds") == 10
    assert identity.email == "u@example.com"
