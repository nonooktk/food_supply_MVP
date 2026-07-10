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

from typing import Optional, TypeVar

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.db import models as m
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

    def first(self, model: type[T], *criteria, order_by=None) -> T | None:
        """条件・並び替え付きで先頭1件を取得する（常に tenant_id で絞り込む）。"""
        stmt = self.select(model)
        for c in criteria:
            stmt = stmt.where(c)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        return self.session.execute(stmt.limit(1)).scalars().first()

    def count(self, model: type[T], *criteria) -> int:
        """自テナント行数を返す（条件を AND で重ねられる）。"""
        stmt = select(func.count()).select_from(model).where(model.tenant_id == self.tenant_id)
        for c in criteria:
            stmt = stmt.where(c)
        return int(self.session.execute(stmt).scalar_one())

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

    # ---- 過去決着の JOIN 読み取り（テナント境界内で完結） ---------------------
    def past_results_for_spec(self, spec_id: int, exclude_case_no: str) -> list[m.NegotiationResult]:
        """同一スペックの過去決着（final_price あり・当該案件を除く）を返す。

        3ライン算出の「過去最安・過去平均」に用いる直接一致データ。JOIN の起点は
        ``select(NegotiationResult)`` にテナント条件を AND した Select で、越境を機構的に防ぐ。
        """
        stmt = (
            self.select(m.NegotiationResult)
            .join(
                m.NegotiationCase,
                (m.NegotiationResult.tenant_id == m.NegotiationCase.tenant_id)
                & (m.NegotiationResult.case_no == m.NegotiationCase.case_no),
            )
            .where(
                m.NegotiationCase.spec_id == spec_id,
                m.NegotiationResult.case_no != exclude_case_no,
                m.NegotiationResult.final_price.is_not(None),
            )
        )
        return list(self.session.execute(stmt).scalars().all())

    def related_past_results(
        self, spec_id: int, supplier_id: int, exclude_case_no: str
    ) -> list[tuple[m.NegotiationResult, m.NegotiationCase]]:
        """関連する過去決着（同一スペック=直接一致 / 同一取引先=グラフ補完）を返す。

        過去経緯表示（FR-03）用。決着日の新しい順。テナント境界は select 起点で強制。
        """
        stmt = (
            select(m.NegotiationResult, m.NegotiationCase)
            .join(
                m.NegotiationCase,
                (m.NegotiationResult.tenant_id == m.NegotiationCase.tenant_id)
                & (m.NegotiationResult.case_no == m.NegotiationCase.case_no),
            )
            .where(
                m.NegotiationResult.tenant_id == self.tenant_id,
                m.NegotiationCase.case_no != exclude_case_no,
                (m.NegotiationCase.spec_id == spec_id)
                | (m.NegotiationCase.supplier_id == supplier_id),
            )
            .order_by(m.NegotiationResult.result_date.desc())
        )
        return [tuple(row) for row in self.session.execute(stmt).all()]

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
