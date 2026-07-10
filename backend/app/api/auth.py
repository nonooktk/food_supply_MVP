"""auth.py — モック認証（ログイン / me）。

MVP はモックヘッダー方式。ログインは資格情報を緩く検証し、テナントを解決して AuthUser を返す。
フロントは返却された ``tenantId`` を以後 ``X-Tenant-Id`` ヘッダーで送る（Entra は後続タスク）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant, get_current_user, get_session
from app.db.models import Tenant
from app.errors import ApiProblem
from app.schemas import AuthUser, LoginRequest

router = APIRouter(tags=["auth"])


def _resolve_tenant(session: Session, tenant_key: str) -> Tenant:
    """ログインのテナント指定を解決する。

    tenant_id 完全一致 → tenant_name 完全一致 → テナントが1件だけなら黙ってそれを使う（デモ）。
    いずれにも当たらなければ 401。
    """
    by_id = session.execute(select(Tenant).where(Tenant.tenant_id == tenant_key)).scalar_one_or_none()
    if by_id:
        return by_id
    by_name = session.execute(
        select(Tenant).where(Tenant.tenant_name == tenant_key)
    ).scalar_one_or_none()
    if by_name:
        return by_name
    all_tenants = session.execute(select(Tenant)).scalars().all()
    if len(all_tenants) == 1:
        return all_tenants[0]
    raise ApiProblem(401, "ログインに失敗しました", detail="テナント・ID・パスワードのいずれかが正しくありません。")


@router.post("/auth/login", response_model=AuthUser)
def login(body: LoginRequest, session: Session = Depends(get_session)) -> AuthUser:
    """モックログイン。資格情報を緩く検証し、テナントを解決して AuthUser を返す。"""
    if not body.user_id.strip() or not body.password:
        raise ApiProblem(401, "ログインに失敗しました", detail="テナント・ID・パスワードのいずれかが正しくありません。")
    tenant = _resolve_tenant(session, body.tenant.strip())
    return AuthUser(
        tenant_id=tenant.tenant_id,
        user_id=body.user_id.strip(),
        display_name=body.user_id.strip(),
        role="member",
    )


@router.get("/me", response_model=AuthUser)
def me(
    tenant_id: str = Depends(get_current_tenant),
    user_id: str = Depends(get_current_user),
) -> AuthUser:
    """ヘッダーから現在の認証情報を返す（動線確認用）。"""
    return AuthUser(tenant_id=tenant_id, user_id=user_id, display_name=user_id, role="member")
