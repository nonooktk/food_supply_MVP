"""deps.py — FastAPI 依存性注入（認証・DB・Repository・KRE エンジン）。

認証は ``AUTH_MODE`` で二系統に分かれる（セキュリティ監査 2026-07-26 F-1 対応）。

- ``AUTH_MODE=google``（本番）:
  ``Authorization: Bearer <Google ID トークン>`` を **毎リクエスト検証** する。
  検証で得た email を allowlist（``ALLOWED_EMAILS``）と照合し、テナントを解決する。
  ``X-Tenant-Id`` / ``X-User-Id`` は **一切参照しない**（クライアントが自称する識別子を
  信用しない＝ Deny by Default）。
- ``AUTH_MODE=mock``（ローカル開発・テスト専用）:
  従来のヘッダー方式（``X-Tenant-Id`` / ``X-User-Id``）を許可する。
  本番（``APP_ENV=production``）では起動時・実行時の両方で拒否する（F-3）。

【なぜヘッダー方式が危険だったか】
旧実装は ``X-Tenant-Id`` の **実在確認だけ** を行い、呼び出し元がそのテナントに属するかを
検証していなかった。テナント UUID を知る者は誰でも全データを読めた（F-1 Blocker）。
テナント分離の第2層（TenantScopedRepository）・第3層（KRE）は健全なため、
本ファイルの「最上段でテナントを名乗れてしまう」欠陥だけを塞ぐ。
"""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterator, Optional

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.google import GoogleAuthError, verify_google_credential
from app.auth.policy import authorize_google_identity, ensure_mock_auth_allowed
from app.auth.tenancy import resolve_default_tenant
from app.config import get_settings
from app.db.database import get_sessionmaker
from app.db.models import Tenant
from app.db.repository import TenantScopedRepository
from app.errors import ApiProblem, IdempotencyStore

# 冪等キーのプロセス内ストア（アプリ全体で共有）。
idempotency_store = IdempotencyStore()


def get_session() -> Iterator[Session]:
    """リクエストスコープの DB セッション。"""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


def get_trace_id(x_trace_id: Optional[str] = Header(default=None, alias="X-Trace-Id")) -> str:
    """trace_id を取得（無ければ生成）。監査ログの横断キー。"""
    return x_trace_id or str(uuid.uuid4())


@dataclass(frozen=True)
class Principal:
    """認証済みの呼び出し元。

    ``tenant_id`` … 認可（Repository のスコープ）の唯一の源泉。
    ``user_id``   … 監査ログの実行者。mock モードでは省略されうるため Optional
                    （読み取り系 API は従来どおり実行者を必須にしていない）。
    """

    tenant_id: str
    user_id: Optional[str]


# ---------------------------------------------------------------------------
# Bearer トークン検証（google モード）
# ---------------------------------------------------------------------------
# ID トークンの検証は Google の公開鍵取得（HTTPS）を伴うため、毎リクエストで実行すると
# 往復が積み上がる。トークン単位で短時間だけ検証結果をキャッシュする。
# TTL はトークン自体の寿命（約1時間）よりはるかに短く取り、安全側に倒す。
_TOKEN_CACHE_TTL_SECONDS = 300
_token_cache: dict[str, tuple[float, str]] = {}
_token_cache_lock = threading.Lock()
_TOKEN_CACHE_MAX = 512


def _token_cache_key(token: str) -> str:
    """生トークンをそのままキーに残さない（メモリダンプ・ログ露出の面積を減らす）。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _cached_authorized_email(token: str) -> Optional[str]:
    key = _token_cache_key(token)
    now = time.time()
    with _token_cache_lock:
        item = _token_cache.get(key)
        if item is None:
            return None
        expires_at, email = item
        if expires_at <= now:
            del _token_cache[key]
            return None
        return email


def _store_authorized_email(token: str, email: str) -> None:
    key = _token_cache_key(token)
    with _token_cache_lock:
        if len(_token_cache) >= _TOKEN_CACHE_MAX:
            # 単純な全消し（LRU は不要な規模。上限は暴走防止のための保険）。
            _token_cache.clear()
        _token_cache[key] = (time.time() + _TOKEN_CACHE_TTL_SECONDS, email)


def reset_token_cache() -> None:
    """検証結果キャッシュを破棄する（テスト・設定変更時用）。"""
    with _token_cache_lock:
        _token_cache.clear()


def _extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    """``Authorization: Bearer <token>`` からトークン部分を取り出す（無ければ None）。"""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.strip().lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def _principal_from_bearer(session: Session, authorization: Optional[str]) -> Principal:
    """Bearer の Google ID トークンを検証して Principal を組み立てる（google モード）。

    - トークン無し／形式不正／署名・aud・exp の検証失敗 … 401（フロントは再ログインへ誘導）
    - 検証は通ったが allowlist 外・email 未確認 … 403（app/auth/policy.py が送出）
    """
    token = _extract_bearer_token(authorization)
    if not token:
        raise ApiProblem(
            401,
            "未認証です",
            detail="Authorization: Bearer <Google ID トークン> が必要です。",
        )

    email = _cached_authorized_email(token)
    if email is None:
        try:
            identity = verify_google_credential(token)
        except GoogleAuthError as exc:
            # 期限切れ（約1時間）もここに落ちる。401 を返してフロントの再ログイン導線に繋ぐ。
            raise ApiProblem(
                401, "認証の有効期限が切れました", detail="再度ログインしてください。"
            ) from exc
        # allowlist・email_verified の照合（ログイン経路と同じ関門を通す）。
        email = authorize_google_identity(identity)
        _store_authorized_email(token, email)

    tenant = resolve_default_tenant(session)
    return Principal(tenant_id=tenant.tenant_id, user_id=email)


def _principal_from_mock_headers(
    session: Session, x_tenant_id: Optional[str], x_user_id: Optional[str]
) -> Principal:
    """従来のモックヘッダー方式（AUTH_MODE=mock のときのみ許可）。

    - ヘッダー未指定は 401（Deny by Default・設計 v3 §6.2）。
    - 実在しないテナントは 403（越境防止）。
    """
    ensure_mock_auth_allowed()  # 本番でモック認証が開かないことを実行時にも確認する（F-3）。
    if not x_tenant_id:
        raise ApiProblem(401, "未認証です", detail="X-Tenant-Id ヘッダーが必要です。")
    exists = session.execute(
        select(Tenant.tenant_id).where(Tenant.tenant_id == x_tenant_id)
    ).scalar_one_or_none()
    if exists is None:
        raise ApiProblem(403, "アクセスできません", detail="不明なテナントです。")
    return Principal(tenant_id=x_tenant_id, user_id=x_user_id or None)


def get_principal(
    session: Session = Depends(get_session),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
) -> Principal:
    """認証済みの呼び出し元を解決する（テナント／実行者の唯一の源泉）。

    FastAPI の依存キャッシュにより、1 リクエスト内で 1 回だけ評価される
    （get_current_tenant / get_current_user が同じ Principal を共有する）。
    """
    if get_settings().normalized_auth_mode == "mock":
        return _principal_from_mock_headers(session, x_tenant_id, x_user_id)
    # mock 以外は必ず検証済み資格情報を要求する（未知のモードも fail-closed）。
    return _principal_from_bearer(session, authorization)


def get_current_user(principal: Principal = Depends(get_principal)) -> str:
    """実行ユーザー（監査ログの実行者）。特定できない場合は 401。"""
    if not principal.user_id:
        raise ApiProblem(401, "未認証です", detail="X-User-Id ヘッダーが必要です。")
    return principal.user_id


def get_current_tenant(principal: Principal = Depends(get_principal)) -> str:
    """テナントを解決する（唯一の源泉は検証済み資格情報）。"""
    return principal.tenant_id


def get_repo(
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_current_tenant),
) -> TenantScopedRepository:
    """テナントスコープ付き Repository（二層防御の第1層）。"""
    return TenantScopedRepository(session, tenant_id)


@lru_cache(maxsize=1)
def _cached_stub_engine():
    """KRE スタブを1度だけ構築してキャッシュする。"""
    from kre.stub import default_stub

    return default_stub()


@lru_cache(maxsize=1)
def _cached_azure_engine():
    """KRE 本実装（AzureRetrievalEngine）を1度だけ構築してキャッシュする。"""
    from kre.engine import default_engine

    return default_engine()


def get_retrieval_engine():
    """KRE の RetrievalEngine を DI で返す（設計 v3 §5）。

    - ``USE_KRE_STUB=true``（既定）… 同梱 fixtures のスタブ実装（AI Search/AOAI 未接続でも動く）。
    - ``USE_KRE_STUB=false``        … 本実装 ``kre.engine.AzureRetrievalEngine``（AI Search + GraphRAG）。

    どちらも同一の RetrievalEngine Protocol を満たすため、本体の呼び出し口は不変（stub ⇄ 本実装）。
    """
    settings = get_settings()
    if settings.use_kre_stub:
        return _cached_stub_engine()
    return _cached_azure_engine()
