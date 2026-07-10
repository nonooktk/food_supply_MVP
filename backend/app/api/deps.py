"""deps.py — FastAPI 依存性注入（認証・DB・Repository・KRE エンジン）。

認証は MVP のモックヘッダー方式（設計 v3 §6.2 の PoC 相当）:
- ``X-Tenant-Id`` … テナントの唯一の源泉。Repository のスコープに接続する。
- ``X-User-Id``   … 監査ログの実行者。
Entra External ID（JWT）への差し替えは後続タスク。get_current_tenant を置換するだけでよい。
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Iterator, Optional

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

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


def get_current_user(x_user_id: Optional[str] = Header(default=None, alias="X-User-Id")) -> str:
    """実行ユーザー（モック認証）。未指定は 401。"""
    if not x_user_id:
        raise ApiProblem(401, "未認証です", detail="X-User-Id ヘッダーが必要です。")
    return x_user_id


def get_current_tenant(
    session: Session = Depends(get_session),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id"),
) -> str:
    """テナントを解決する（唯一の源泉は X-Tenant-Id）。

    - ヘッダー未指定は 401（Deny by Default・設計 v3 §6.2）。
    - 実在しないテナントは 403（越境防止）。
    """
    if not x_tenant_id:
        raise ApiProblem(401, "未認証です", detail="X-Tenant-Id ヘッダーが必要です。")
    exists = session.execute(
        select(Tenant.tenant_id).where(Tenant.tenant_id == x_tenant_id)
    ).scalar_one_or_none()
    if exists is None:
        raise ApiProblem(403, "アクセスできません", detail="不明なテナントです。")
    return x_tenant_id


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
