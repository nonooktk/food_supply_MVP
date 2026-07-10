"""case_view.py — DB モデル → API スキーマの変換ヘルパ。

案件のステータス写像・商材表示名の組み立てなど、複数エンドポイントで共有する読み取り用の
変換を集約する。書き込み系のテナント強制は Repository（二層防御の第1層）が担う。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.schemas import CaseDetail, CaseStatus

# DB の日本語ステータス ⇄ フロントのステータスキー。
_DB_TO_UI_STATUS: dict[str, CaseStatus] = {
    "交渉前": "before",
    "交渉中": "negotiating",
    "完了": "done",
}
_UI_TO_DB_STATUS: dict[str, str] = {v: k for k, v in _DB_TO_UI_STATUS.items()}


def load_case(session: Session, tenant_id: str, case_no: str) -> Optional[m.NegotiationCase]:
    """テナント境界内で案件を1件取得する（無ければ None）。"""
    return session.execute(
        select(m.NegotiationCase).where(
            m.NegotiationCase.tenant_id == tenant_id,
            m.NegotiationCase.case_no == case_no,
        )
    ).scalar_one_or_none()


def db_status_to_ui(value: Optional[str]) -> CaseStatus:
    """DB ステータス文字列をフロントのキーへ写像する（未知値は before 扱い）。"""
    return _DB_TO_UI_STATUS.get(value or "", "before")


def ui_status_to_db(value: str) -> str:
    """フロントのステータスキーを DB 文字列へ写像する。"""
    return _UI_TO_DB_STATUS.get(value, "交渉前")


def product_display(product: Optional[m.Product], spec: Optional[m.ProductSpec]) -> str:
    """商材の表示名を「商材名（産地・温度帯）」の形で組み立てる。

    産地・温度帯が無ければ商材名のみ。product が無い場合は空文字。
    """
    if product is None:
        return ""
    name = product.product_name or ""
    if spec is None:
        return name
    attrs = [a for a in (spec.origin, spec.storage_type) if a]
    return f"{name}（{'・'.join(attrs)}）" if attrs else name


def build_case_detail(
    session: Session,
    case: m.NegotiationCase,
    *,
    supplier: Optional[m.Supplier] = None,
    spec: Optional[m.ProductSpec] = None,
    product: Optional[m.Product] = None,
) -> CaseDetail:
    """NegotiationCase から CaseDetail を組み立てる。

    関連（取引先・スペック・商材）は未指定なら本関数内で取得する。すべてテナント境界内。
    """
    tid = case.tenant_id
    if supplier is None:
        supplier = session.execute(
            select(m.Supplier).where(
                m.Supplier.tenant_id == tid, m.Supplier.supplier_id == case.supplier_id
            )
        ).scalar_one_or_none()
    if spec is None:
        spec = session.execute(
            select(m.ProductSpec).where(
                m.ProductSpec.tenant_id == tid, m.ProductSpec.spec_id == case.spec_id
            )
        ).scalar_one_or_none()
    if product is None and spec is not None:
        product = session.execute(
            select(m.Product).where(
                m.Product.tenant_id == tid, m.Product.product_id == spec.product_id
            )
        ).scalar_one_or_none()

    return CaseDetail(
        case_no=case.case_no,
        company=supplier.supplier_name if supplier else "",
        product=product_display(product, spec),
        status=db_status_to_ui(case.status),
        updated_at=case.updated_at.strftime("%m/%d") if case.updated_at else "",
        assignee=case.created_by or "",
        quoted_price=float(case.proposed_price) if case.proposed_price is not None else 0.0,
        target_period=case.period or "",
        current_step="collect",
    )
