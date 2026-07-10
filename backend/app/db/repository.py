"""repository.py — テナントスコープ付き Repository（設計 v3 §2.8・二層防御の第1層）。

MySQL 8.4 は RLS 非対応のため、テナント分離はアプリ層で必須化する。業務テーブルへの
アクセスは本 Repository 経由に限定し、素の SQLAlchemy セッションを画面／サービス層へ露出しない。

必須ルール（設計 v3 §2.8）:
1. 全クエリに `tenant_id` 条件を強制する。
2. `tenant_id` の唯一の源泉は認証（JWT）。リクエストボディ／クエリ由来の値は信用しない。
   → FastAPI 側で `Depends(get_current_tenant)` が解決した値をコンストラクタに注入する。
3. 書込時も強制付与。他テナント行の UPDATE/DELETE はゼロ件化する。
4. 付与漏れの機構的防止。業務モデルへのアクセスをこのクラスに集約する。
5. 共有マスタは対象外。`model_versions` は「参照＝自テナント＋共通(NULL)、書込＝自テナントのみ」。
"""

from __future__ import annotations

from typing import TypeVar

from sqlalchemy import delete as sa_delete
from sqlalchemy import or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.db.models import Base, ModelVersion

T = TypeVar("T", bound=Base)


class TenantIsolationError(RuntimeError):
    """テナントスコープを持たないモデルに対しスコープ操作を要求した場合の例外。"""


def _require_tenant_column(model: type) -> None:
    """モデルが `tenant_id` 列を持つことを保証する（持たなければ機構的に失敗させる）。"""
    if not hasattr(model, "tenant_id"):
        raise TenantIsolationError(
            f"{model.__name__} は tenant_id を持たない共有マスタです。"
            f"テナントスコープ Repository の対象外です。"
        )


class TenantScopedRepository:
    """`tenant_id` を全操作へ強制注入する Repository。

    使い方:
        repo = TenantScopedRepository(session, tenant_id="...JWT由来...")
        rows = repo.list(Supplier)                 # 自テナント行のみ
        repo.add(Supplier(supplier_name="X"))      # tenant_id を強制付与
    """

    def __init__(self, session: Session, tenant_id: str) -> None:
        if not tenant_id:
            # tenant 未解決（未認証）は Deny by Default（設計 v3 §6.2）。
            raise TenantIsolationError("tenant_id が未指定です（未認証アクセスは拒否）。")
        self.session = session
        self.tenant_id = tenant_id

    # ---- 読み取り -----------------------------------------------------------
    def select(self, model: type[T]) -> Select:
        """`tenant_id` 条件を必ず AND した Select を返す（全クエリの起点）。"""
        _require_tenant_column(model)
        return select(model).where(model.tenant_id == self.tenant_id)

    def list(self, model: type[T], *criteria) -> list[T]:
        """自テナント行を一覧取得する。追加条件は AND で重ねる。"""
        stmt = self.select(model)
        for c in criteria:
            stmt = stmt.where(c)
        return list(self.session.execute(stmt).scalars().all())

    def get(self, model: type[T], **filters) -> T | None:
        """主キー等で 1 件取得する（常に tenant_id で絞り込む）。"""
        stmt = self.select(model)
        for key, value in filters.items():
            stmt = stmt.where(getattr(model, key) == value)
        return self.session.execute(stmt).scalars().first()

    def count(self, model: type[T]) -> int:
        """自テナント行数を返す。"""
        return len(self.list(model))

    # ---- 書き込み -----------------------------------------------------------
    def add(self, obj: T) -> T:
        """`tenant_id` を強制付与して追加する（リクエスト由来の値は上書き）。"""
        _require_tenant_column(type(obj))
        obj.tenant_id = self.tenant_id
        self.session.add(obj)
        return obj

    def update_where(self, model: type[T], values: dict, *criteria) -> int:
        """自テナント行のみを一括更新する。影響行数を返す（他テナントはゼロ件）。"""
        _require_tenant_column(model)
        stmt = sa_update(model).where(model.tenant_id == self.tenant_id)
        for c in criteria:
            stmt = stmt.where(c)
        stmt = stmt.values(**values)
        result = self.session.execute(stmt)
        return result.rowcount or 0

    def delete_where(self, model: type[T], *criteria) -> int:
        """自テナント行のみを削除する。影響行数を返す（他テナントはゼロ件）。"""
        _require_tenant_column(model)
        stmt = sa_delete(model).where(model.tenant_id == self.tenant_id)
        for c in criteria:
            stmt = stmt.where(c)
        result = self.session.execute(stmt)
        return result.rowcount or 0

    # ---- model_versions 専用（自テナント＋共通(NULL)を参照） -----------------
    def list_model_versions(self, model_type: str | None = None, *, active_only: bool = True) -> list[ModelVersion]:
        """算出式・プロンプト等の版を取得する。参照は自テナント行＋共通(tenant_id IS NULL)。"""
        stmt = select(ModelVersion).where(
            or_(ModelVersion.tenant_id == self.tenant_id, ModelVersion.tenant_id.is_(None))
        )
        if model_type is not None:
            stmt = stmt.where(ModelVersion.model_type == model_type)
        if active_only:
            stmt = stmt.where(ModelVersion.is_active.is_(True))
        return list(self.session.execute(stmt).scalars().all())
