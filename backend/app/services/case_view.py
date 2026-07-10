"""case_view.py — DB モデル → API スキーマの変換ヘルパ（Repository 経由）。

案件のステータス写像・商材表示名の組み立てなど、複数エンドポイントで共有する読み取り用の
変換を集約する。DB アクセスは ``TenantScopedRepository`` 経由で、テナント境界は Repository が
強制する（§2.8 ルール1・素のセッションを画面/サービス層へ露出しない）。
"""

from __future__ import annotations

from typing import Optional

from app.db import models as m
from app.db.repository import TenantScopedRepository
from app.schemas import CaseDetail, CaseStatus

# DB の日本語ステータス ⇄ フロントのステータスキー。
_DB_TO_UI_STATUS: dict[str, CaseStatus] = {
    "交渉前": "before",
    "交渉中": "negotiating",
    "完了": "done",
}
_UI_TO_DB_STATUS: dict[str, str] = {v: k for k, v in _DB_TO_UI_STATUS.items()}


def load_case(repo: TenantScopedRepository, case_no: str) -> Optional[m.NegotiationCase]:
    """テナント境界内で案件を1件取得する（無ければ None）。"""
    return repo.get(m.NegotiationCase, case_no=case_no)


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
    repo: TenantScopedRepository,
    case: m.NegotiationCase,
    *,
    supplier: Optional[m.Supplier] = None,
    spec: Optional[m.ProductSpec] = None,
    product: Optional[m.Product] = None,
) -> CaseDetail:
    """NegotiationCase から CaseDetail を組み立てる。

    関連（取引先・スペック・商材）は未指定なら Repository 経由で取得する（すべてテナント境界内）。
    """
    if supplier is None:
        supplier = repo.get(m.Supplier, supplier_id=case.supplier_id)
    if spec is None:
        spec = repo.get(m.ProductSpec, spec_id=case.spec_id)
    if product is None and spec is not None:
        product = repo.get(m.Product, product_id=spec.product_id)

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
