"""auth.py — ログイン（認証シーム: mock / google）と me。

認証方式は ``AUTH_MODE`` で切り替える（設計の認証シーム）:
- mock   … テナント/ID/PW のモックフォーム（開発・テスト）。POST /auth/login。
- google … Google Identity Services の ID トークン検証（統合確認・デモ）。POST /auth/google。

google モードでは、フロントは受け取った ID トークンを保持し、以後の全リクエストに
``Authorization: Bearer <ID トークン>`` を付けて送る（データ API 側の検証は app/api/deps.py）。
mock モードのみ、従来どおり X-Tenant-Id/X-User-Id ヘッダー方式で送る。
Entra へ移行する場合は ``AUTH_MODE=entra`` を足し、対応する検証エンドポイントを本ファイルに
一つ追加する（deps.py の Bearer 検証も同様に一分岐追加する）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant, get_current_user, get_session
from app.auth.google import GoogleAuthError, verify_google_credential
from app.auth.policy import authorize_google_identity, ensure_mock_auth_allowed
from app.auth.tenancy import DEFAULT_TENANT_NAME, resolve_default_tenant
from app.config import get_settings
from app.errors import ApiProblem
from app.schemas import AuthUser, GoogleAuthRequest, LoginRequest

router = APIRouter(tags=["auth"])

# テナント解決は app/auth/tenancy.py が正本（deps.py と共用するため認証層へ移設した）。
# 後方互換のための別名。
_resolve_default_tenant = resolve_default_tenant

__all__ = ["router", "DEFAULT_TENANT_NAME"]


@router.post("/auth/login", response_model=AuthUser)
def login(body: LoginRequest, session: Session = Depends(get_session)) -> AuthUser:
    """モックログイン（AUTH_MODE=mock かつ非本番のときのみ有効）。"""
    # 本番でモック認証が開いていないことを先に確認する（F-3・設定ミスの二重ガード）。
    ensure_mock_auth_allowed()
    if get_settings().normalized_auth_mode != "mock":
        raise ApiProblem(
            403, "モックログインは無効です", detail="AUTH_MODE=google のため Google ログインを使用してください。"
        )
    if not body.user_id.strip() or not body.password:
        raise ApiProblem(
            401, "ログインに失敗しました", detail="テナント・ID・パスワードのいずれかが正しくありません。"
        )
    tenant = resolve_default_tenant(session, body.tenant.strip())
    return AuthUser(
        tenant_id=tenant.tenant_id,
        user_id=body.user_id.strip(),
        display_name=body.user_id.strip(),
        role="member",
    )


@router.post("/auth/google", response_model=AuthUser)
def google_login(body: GoogleAuthRequest, session: Session = Depends(get_session)) -> AuthUser:
    """Google ログイン（AUTH_MODE=google のときのみ有効）。

    GIS の credential を検証し、**allowlist に載っている確認済み email のみ** を
    既定テナントに紐付ける（F-2）。永続的な users テーブルは MVP では持たず、email を
    実行者識別子（監査の user_id）として用いる。役割別 users は後続で追加する受け皿。

    ここで返すのは表示用の識別情報のみで、**このレスポンスは認可の資格情報ではない**。
    以後のデータ API は Authorization: Bearer <ID トークン> を毎回検証する（F-1）。
    """
    if get_settings().normalized_auth_mode != "google":
        raise ApiProblem(
            403, "Google ログインは無効です", detail="AUTH_MODE=mock のためモックログインを使用してください。"
        )
    try:
        identity = verify_google_credential(body.credential)
    except GoogleAuthError as exc:
        raise ApiProblem(401, "Google 認証に失敗しました", detail=str(exc)) from exc

    # allowlist・email_verified の照合（deps.py の Bearer 経路と同一の関門）。
    # 片方だけに置くと素通りする経路が残るため、必ず共通関数を通す。
    user_id = authorize_google_identity(identity)

    tenant = resolve_default_tenant(session)
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
