"""tenancy.py — ログイン／認証経路で使うテナント解決。

もとは ``app/api/auth.py`` の ``_resolve_default_tenant`` だった処理を、認証層（app/auth/）へ
移設したもの。データ API の認証依存（``app/api/deps.py``）とログイン API（``app/api/auth.py``）の
**両方**から呼ぶ必要があり、api 層に置いたままだと循環 import になるため。

MVP のスコープ: users テーブル（email → テナントの対応表）はまだ持たないため、
検証済みアカウントは既定テナントに解決する。複数テナント運用時はここを差し替える。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Tenant
from app.errors import ApiProblem

# 初回ログインの自動プロビジョニング先（既定テナント）。名称一致 → 単一テナント の順で解決する。
DEFAULT_TENANT_NAME = "freeradicals"


def resolve_default_tenant(session: Session, tenant_key: str = "") -> Tenant:
    """ログインのテナントを解決する。

    tenant_id 完全一致 → tenant_name 完全一致 → 既定名 → テナントが1件だけならそれ（デモ）。
    Google ログインの紐付け先は「既定テナント（freeradicals）」。
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
