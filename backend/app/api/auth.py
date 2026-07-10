"""auth.py — ログイン（認証シーム: mock / google）と me。

認証方式は ``AUTH_MODE`` で切り替える（設計の認証シーム）:
- mock   … テナント/ID/PW のモックフォーム（開発・テスト）。POST /auth/login。
- google … Google Identity Services の ID トークン検証（統合確認・デモ）。POST /auth/google。

どちらも最終的に AuthUser（tenantId/userId）を返し、フロントはそれを X-Tenant-Id/X-User-Id
ヘッダーで送る（データ API の認可＝テナント解決の仕組みは方式に依らず不変）。
Entra へ移行する場合は ``AUTH_MODE=entra`` を足し、対応する検証エンドポイントを本ファイルに
一つ追加するだけでよい（get_current_tenant 側は不変、または JWT 検証へ差し替え）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant, get_current_user, get_session
from app.auth.google import GoogleAuthError, verify_google_credential
from app.config import get_settings
from app.db.models import Tenant
from app.errors import ApiProblem
from app.schemas import AuthUser, GoogleAuthRequest, LoginRequest

router = APIRouter(tags=["auth"])

# 初回ログインの自動プロビジョニング先（既定テナント）。名称一致 → 単一テナント の順で解決する。
DEFAULT_TENANT_NAME = "freeradicals"


def _resolve_default_tenant(session: Session, tenant_key: str = "") -> Tenant:
    """ログインのテナントを解決する。

    tenant_id 完全一致 → tenant_name 完全一致 → 既定名 → テナントが1件だけならそれ（デモ）。
    Google 初回ログインの自動プロビジョニングは「既定テナント（freeradicals）に紐付け」。
    """
    if tenant_key:
        by_id = session.execute(select(Tenant).where(Tenant.tenant_id == tenant_key)).scalar_one_or_none()
        if by_id:
            return by_id
        by_name = session.execute(select(Tenant).where(Tenant.tenant_name == tenant_key)).scalar_one_or_none()
        if by_name:
            return by_name
    by_default = session.execute(
        select(Tenant).where(Tenant.tenant_name == DEFAULT_TENANT_NAME)
    ).scalar_one_or_none()
    if by_default:
        return by_default
    tenants = session.execute(select(Tenant)).scalars().all()
    if len(tenants) == 1:
        return tenants[0]
    raise ApiProblem(401, "ログインに失敗しました", detail="テナントを解決できませんでした。")


@router.post("/auth/login", response_model=AuthUser)
def login(body: LoginRequest, session: Session = Depends(get_session)) -> AuthUser:
    """モックログイン（AUTH_MODE=mock のときのみ有効）。"""
    if get_settings().auth_mode != "mock":
        raise ApiProblem(
            403, "モックログインは無効です", detail="AUTH_MODE=google のため Google ログインを使用してください。"
        )
    if not body.user_id.strip() or not body.password:
        raise ApiProblem(
            401, "ログインに失敗しました", detail="テナント・ID・パスワードのいずれかが正しくありません。"
        )
    tenant = _resolve_default_tenant(session, body.tenant.strip())
    return AuthUser(
        tenant_id=tenant.tenant_id,
        user_id=body.user_id.strip(),
        display_name=body.user_id.strip(),
        role="member",
    )


@router.post("/auth/google", response_model=AuthUser)
def google_login(body: GoogleAuthRequest, session: Session = Depends(get_session)) -> AuthUser:
    """Google ログイン（AUTH_MODE=google のときのみ有効）。

    GIS の credential を検証し、検証済み email を user_id として既定テナントに紐付ける
    （初回ログインの自動プロビジョニング＝既定テナント）。永続的な users テーブルは MVP では持たず、
    email を実行者識別子（監査の user_id）として用いる。役割別 users は後続で追加する受け皿。
    """
    if get_settings().auth_mode != "google":
        raise ApiProblem(
            403, "Google ログインは無効です", detail="AUTH_MODE=mock のためモックログインを使用してください。"
        )
    try:
        identity = verify_google_credential(body.credential)
    except GoogleAuthError as exc:
        raise ApiProblem(401, "Google 認証に失敗しました", detail=str(exc)) from exc

    tenant = _resolve_default_tenant(session)
    user_id = identity.email or identity.sub
    return AuthUser(
        tenant_id=tenant.tenant_id,
        user_id=user_id,
        display_name=identity.name or user_id,
        role="member",
    )


@router.get("/me", response_model=AuthUser)
def me(
    tenant_id: str = Depends(get_current_tenant),
    user_id: str = Depends(get_current_user),
) -> AuthUser:
    """ヘッダーから現在の認証情報を返す（動線確認用）。"""
    return AuthUser(tenant_id=tenant_id, user_id=user_id, display_name=user_id, role="member")
