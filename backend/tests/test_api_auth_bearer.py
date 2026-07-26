"""test_api_auth_bearer.py — Bearer 認証（AUTH_MODE=google）と設定 fail-fast のテスト。

セキュリティ監査 2026-07-26（担当: バリヤード）の指摘 F-1 / F-2 / F-3 に対する回帰テスト。

【この修正が守るもの】
データ API のテナントは **検証済みの Google ID トークン** からのみ決まる。
クライアントが自称する X-Tenant-Id / X-User-Id は google モードでは一切参照しない。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api import deps
from app.config import Settings, get_settings

ALLOWED_EMAIL = "tanaka@example.com"
OUTSIDER_EMAIL = "stranger@gmail.com"
TEST_CLIENT_ID = "test-client.apps.googleusercontent.com"

# 形だけ JWT らしい文字列（検証関数はモック化するので中身は使われない）。
DUMMY_TOKEN = "header.payload.signature"


@pytest.fixture()
def google_mode(monkeypatch: pytest.MonkeyPatch):
    """AUTH_MODE=google（GOOGLE_CLIENT_ID・ALLOWED_EMAILS 設定済み）へ切り替える。"""
    s = get_settings()
    monkeypatch.setattr(s, "auth_mode", "google")
    monkeypatch.setattr(s, "google_client_id", TEST_CLIENT_ID)
    monkeypatch.setattr(s, "allowed_emails_raw", ALLOWED_EMAIL)
    deps.reset_token_cache()
    yield
    deps.reset_token_cache()


def _mock_verify_returns(monkeypatch: pytest.MonkeyPatch, claims: dict) -> None:
    """Google の検証関数を差し替え、任意のクレームを返させる（＝検証に成功した状態）。"""
    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", lambda *a, **k: claims)


def _mock_verify_raises(monkeypatch: pytest.MonkeyPatch, message: str = "bad signature") -> None:
    """Google の検証関数を差し替え、常に失敗させる（署名不正・期限切れ相当）。"""

    def _raise(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise ValueError(message)

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", _raise)


# ==============================================================================
# ① Bearer 無しは 401
# ==============================================================================
@pytest.mark.parametrize(
    "headers",
    [
        {},  # 資格情報なし
        {"Authorization": ""},  # 空
        {"Authorization": "Bearer"},  # トークン部分なし
        {"Authorization": "Bearer   "},  # 空白のみ
        {"Authorization": f"Basic {DUMMY_TOKEN}"},  # 別スキーム
    ],
    ids=["none", "empty", "scheme-only", "blank-token", "wrong-scheme"],
)
def test_missing_bearer_is_401(api, google_mode, headers) -> None:
    """google モードで Bearer が無い（または形式不正な）リクエストは 401。"""
    res = api.client.get("/api/cases", headers=headers)
    assert res.status_code == 401, f"資格情報なしで通った: {headers} -> {res.text}"
    assert res.headers["content-type"] == "application/problem+json"


# ==============================================================================
# ② 不正 Bearer は 401
# ==============================================================================
def test_invalid_bearer_is_401(api, google_mode, monkeypatch: pytest.MonkeyPatch) -> None:
    """署名不正・期限切れなど、ID トークンの検証に失敗したら 401（再ログイン導線）。"""
    _mock_verify_raises(monkeypatch)
    res = api.client.get("/api/cases", headers=api.bearer(DUMMY_TOKEN))
    assert res.status_code == 401
    assert res.headers["content-type"] == "application/problem+json"


def test_expired_bearer_is_401(api, google_mode, monkeypatch: pytest.MonkeyPatch) -> None:
    """期限切れ（ID トークンの寿命は約1時間）も 401。サイレント更新は行わない。"""
    _mock_verify_raises(monkeypatch, "Token expired")
    res = api.client.get("/api/cases", headers=api.bearer(DUMMY_TOKEN))
    assert res.status_code == 401


# ==============================================================================
# ③ allowlist 外の検証済みアカウントは 403
# ==============================================================================
def test_verified_but_not_allowlisted_is_403(
    api, google_mode, monkeypatch: pytest.MonkeyPatch
) -> None:
    """トークンは正当でも、ALLOWED_EMAILS に無いアカウントはデータ API を叩けない（F-2）。"""
    _mock_verify_returns(
        monkeypatch,
        {"sub": "g-999", "email": OUTSIDER_EMAIL, "email_verified": True, "name": "赤の他人"},
    )
    res = api.client.get("/api/cases", headers=api.bearer(DUMMY_TOKEN))
    assert res.status_code == 403, "allowlist 外のアカウントが営業秘密を読めた"


def test_unverified_email_is_403(api, google_mode, monkeypatch: pytest.MonkeyPatch) -> None:
    """email_verified が True でないアカウントは拒否する（F-16）。"""
    _mock_verify_returns(
        monkeypatch,
        {"sub": "g-1", "email": ALLOWED_EMAIL, "email_verified": False, "name": "田中"},
    )
    res = api.client.get("/api/cases", headers=api.bearer(DUMMY_TOKEN))
    assert res.status_code == 403


def test_missing_email_claim_is_403(api, google_mode, monkeypatch: pytest.MonkeyPatch) -> None:
    """email クレームが無いトークン（sub のみ）でも素通りさせない。"""
    _mock_verify_returns(monkeypatch, {"sub": "g-1", "name": "名無し"})
    res = api.client.get("/api/cases", headers=api.bearer(DUMMY_TOKEN))
    assert res.status_code == 403


def test_empty_allowlist_denies_everyone(api, google_mode, monkeypatch: pytest.MonkeyPatch) -> None:
    """ALLOWED_EMAILS が空なら全拒否（fail-closed）。設定漏れが全開放に倒れないこと。"""
    monkeypatch.setattr(get_settings(), "allowed_emails_raw", "")
    _mock_verify_returns(
        monkeypatch,
        {"sub": "g-1", "email": ALLOWED_EMAIL, "email_verified": True, "name": "田中"},
    )
    res = api.client.get("/api/cases", headers=api.bearer(DUMMY_TOKEN))
    assert res.status_code == 403


# ==============================================================================
# ④ allowlist 内は 200（正常系）
# ==============================================================================
def test_allowlisted_bearer_can_read(api, google_mode, monkeypatch: pytest.MonkeyPatch) -> None:
    """allowlist 済みの検証済みアカウントは、自テナントのデータを読める。"""
    _mock_verify_returns(
        monkeypatch,
        {"sub": "g-1", "email": ALLOWED_EMAIL, "email_verified": True, "name": "田中 太郎"},
    )
    res = api.client.get("/api/cases", headers=api.bearer(DUMMY_TOKEN))
    assert res.status_code == 200
    assert "items" in res.json()


def test_me_identifies_user_from_bearer(api, google_mode, monkeypatch: pytest.MonkeyPatch) -> None:
    """/api/me は Bearer の検証済み email を実行者として返す（監査証跡の源泉）。"""
    _mock_verify_returns(
        monkeypatch,
        {"sub": "g-1", "email": ALLOWED_EMAIL, "email_verified": True, "name": "田中 太郎"},
    )
    res = api.client.get("/api/me", headers=api.bearer(DUMMY_TOKEN))
    assert res.status_code == 200
    body = res.json()
    assert body["userId"] == ALLOWED_EMAIL
    assert body["tenantId"] == api.tenant_id


def test_write_with_bearer_records_verified_user(
    api, google_mode, monkeypatch: pytest.MonkeyPatch
) -> None:
    """書き込み系でも Bearer だけで実行者が定まる（X-User-Id を送らなくても 401 にならない）。"""
    _mock_verify_returns(
        monkeypatch,
        {"sub": "g-1", "email": ALLOWED_EMAIL, "email_verified": True, "name": "田中 太郎"},
    )
    res = api.client.post(
        "/api/cases",
        headers=api.bearer(DUMMY_TOKEN),
        json={"supplierId": 1, "product": "鶏もも肉", "quotedPrice": 600, "targetPeriod": "2026Q1"},
    )
    assert res.status_code == 201, res.text


# ==============================================================================
# ⑤ X-Tenant-Id 詐称は google モードでは通らない
# ==============================================================================
def test_spoofed_tenant_header_is_ignored_in_google_mode(
    api, google_mode, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bearer と併せて別テナントの X-Tenant-Id を送っても、ヘッダーは無視される。

    テナントは検証済み資格情報からのみ決まる（クライアント供給値は認可に影響しない）。
    """
    _mock_verify_returns(
        monkeypatch,
        {"sub": "g-1", "email": ALLOWED_EMAIL, "email_verified": True, "name": "田中 太郎"},
    )
    res = api.client.get(
        "/api/me",
        headers={
            **api.bearer(DUMMY_TOKEN),
            "X-Tenant-Id": "00000000-0000-0000-0000-000000000000",  # 詐称
            "X-User-Id": "intruder",  # 詐称
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["tenantId"] == api.tenant_id, "X-Tenant-Id の詐称が通った"
    assert body["userId"] == ALLOWED_EMAIL, "X-User-Id の詐称が通った"


def test_bare_headers_without_bearer_are_rejected_in_google_mode(api, google_mode) -> None:
    """google モードでは、モックヘッダーのみのリクエストは（テナントが実在しても）401。"""
    res = api.client.get("/api/cases", headers=api.headers())
    assert res.status_code == 401, "google モードで生ヘッダー認証が通った"


def test_mock_headers_still_work_in_mock_mode(api) -> None:
    """回帰: AUTH_MODE=mock ではローカル開発のヘッダー方式が従来どおり使える。"""
    res = api.client.get("/api/cases", headers=api.headers())
    assert res.status_code == 200


# ==============================================================================
# ⑥⑦ 起動時 fail-fast（F-3）— Settings 構築で失敗すること
# ==============================================================================
def _settings_env(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    """Settings 構築に使う環境変数を設定する（.env の混入は _env_file=None で避ける）。"""
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_production_with_mock_auth_fails_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """[⑥] APP_ENV=production × AUTH_MODE=mock は起動時に失敗する。"""
    _settings_env(monkeypatch, APP_ENV="production", AUTH_MODE="mock")
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)
    assert "AUTH_MODE=mock" in str(exc.value)


def test_google_mode_without_allowed_emails_fails_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """[⑦] AUTH_MODE=google × ALLOWED_EMAILS 空は起動時に失敗する（全開放の防止）。"""
    _settings_env(
        monkeypatch, APP_ENV="production", AUTH_MODE="google", GOOGLE_CLIENT_ID=TEST_CLIENT_ID
    )
    monkeypatch.delenv("ALLOWED_EMAILS", raising=False)
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)
    assert "ALLOWED_EMAILS" in str(exc.value)


def test_google_mode_without_client_id_fails_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """AUTH_MODE=google × GOOGLE_CLIENT_ID 空も起動時に失敗する（aud 検証不能）。"""
    _settings_env(monkeypatch, AUTH_MODE="google", ALLOWED_EMAILS=ALLOWED_EMAIL)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)
    assert "GOOGLE_CLIENT_ID" in str(exc.value)


def test_valid_production_google_settings_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """正しい本番設定（google + client id + allowlist）は起動できる。"""
    _settings_env(
        monkeypatch,
        APP_ENV="production",
        AUTH_MODE="google",
        GOOGLE_CLIENT_ID=TEST_CLIENT_ID,
        ALLOWED_EMAILS=f"{ALLOWED_EMAIL}, Suzuki@Example.com ",
    )
    s = Settings(_env_file=None)
    # カンマ区切り・空白・大文字小文字は正規化される。
    assert s.allowed_emails == [ALLOWED_EMAIL, "suzuki@example.com"]
    assert s.is_production is True


def test_development_with_mock_auth_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    """回帰: 開発既定（development + mock）は従来どおり起動できる。"""
    _settings_env(monkeypatch, APP_ENV="development", AUTH_MODE="mock")
    assert Settings(_env_file=None).normalized_auth_mode == "mock"


# ==============================================================================
# ⑧ 本番でのドキュメント公開停止（F-14）
# ==============================================================================
def test_docs_are_exposed_in_development(api) -> None:
    """開発時は /docs・/openapi.json を従来どおり公開する。"""
    assert api.client.get("/openapi.json").status_code == 200


def test_docs_are_disabled_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """APP_ENV=production では /docs・/redoc・/openapi.json を出さない（F-14）。"""
    from fastapi.testclient import TestClient

    from app.main import create_app

    s = get_settings()
    monkeypatch.setattr(s, "app_env", "production")
    monkeypatch.setattr(s, "auth_mode", "google")
    monkeypatch.setattr(s, "google_client_id", TEST_CLIENT_ID)
    monkeypatch.setattr(s, "allowed_emails_raw", ALLOWED_EMAIL)

    client = TestClient(create_app())
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, f"本番で {path} が公開されている"


# ==============================================================================
# ⑨ セキュリティヘッダー（F-15）
# ==============================================================================
def test_nosniff_header_is_present(api) -> None:
    """全レスポンスに X-Content-Type-Options: nosniff が付く（F-15）。"""
    ok = api.client.get("/api/cases", headers=api.headers())
    assert ok.headers.get("x-content-type-options") == "nosniff"

    # エラー応答（problem+json）にも付くこと。
    unauthorized = api.client.get("/api/cases")
    assert unauthorized.status_code == 401
    assert unauthorized.headers.get("x-content-type-options") == "nosniff"
