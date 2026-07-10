"""cases.py — 交渉案件の CRUD・検索・状態管理（画面①③）。

- GET  /cases                … 一覧・検索（keyword / status）
- POST /cases                … 作成（NumberingService 採番・冪等キー・監査）
- GET  /cases/{case_no}      … 詳細
- PATCH /cases/{case_no}/status … 状態遷移

テナント境界は get_repo（TenantScopedRepository）で強制する（二層防御の第1層）。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_tenant,
    get_current_user,
    get_repo,
    get_session,
    get_trace_id,
    idempotency_store,
)
from app.db import models as m
from app.db.numbering import SequentialNumberingService
from app.db.repository import TenantScopedRepository
from app.errors import ApiProblem
from app.observability.logging import emit_audit
from app.schemas import CaseCreateInput, CaseDetail, CaseListResult, CaseStatus, CaseStatusUpdate
from app.services.case_view import build_case_detail, load_case, ui_status_to_db

router = APIRouter(tags=["cases"])
_numbering = SequentialNumberingService()


@router.get("/cases", response_model=CaseListResult)
def list_cases(
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_current_tenant),
    keyword: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
) -> CaseListResult:
    """案件一覧を返す（保存時期の新しい順）。keyword / status で絞り込む。"""
    cases = session.execute(
        select(m.NegotiationCase)
        .where(m.NegotiationCase.tenant_id == tenant_id)
        .order_by(m.NegotiationCase.updated_at.desc())
    ).scalars().all()

    items: list[CaseDetail] = [build_case_detail(session, c) for c in cases]

    # DB 非依存の絞り込み（表示名を含めて検索するためアプリ層で実施）。
    if status and status != "all":
        items = [it for it in items if it.status == status]
    kw = (keyword or "").strip()
    if kw:
        items = [
            it
            for it in items
            if kw in it.case_no or kw in it.company or kw in it.product or kw in it.assignee
        ]
    return CaseListResult(items=items, total=len(items))


def _resolve_supplier(repo: TenantScopedRepository, company: str) -> int:
    """取引先名から supplier_id を解決（無ければ作成）。"""
    found = repo.list(m.Supplier, m.Supplier.supplier_name == company)
    if found:
        return found[0].supplier_id
    sup = repo.add(m.Supplier(supplier_name=company))
    repo.session.flush()
    return sup.supplier_id


def _resolve_spec(repo: TenantScopedRepository, product_name: str) -> int:
    """商材表示名から spec_id を解決（無ければ商材＋スペックを最小作成）。

    画面①のフォームは商材を1つの表示文字列で渡すため、MVP では product_name にそのまま格納し、
    スペック属性は空で作る（後続で正規化・マスタ紐付けを行う想定）。
    """
    prod = repo.list(m.Product, m.Product.product_name == product_name)
    if prod:
        product_id = prod[0].product_id
        specs = repo.list(m.ProductSpec, m.ProductSpec.product_id == product_id)
        if specs:
            return specs[0].spec_id
    else:
        new_prod = repo.add(m.Product(product_name=product_name, unit="kg"))
        repo.session.flush()
        product_id = new_prod.product_id
    spec = repo.add(m.ProductSpec(product_id=product_id))
    repo.session.flush()
    return spec.spec_id


@router.post("/cases", response_model=CaseDetail, status_code=201)
def create_case(
    body: CaseCreateInput,
    session: Session = Depends(get_session),
    repo: TenantScopedRepository = Depends(get_repo),
    user_id: str = Depends(get_current_user),
    trace_id: str = Depends(get_trace_id),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> CaseDetail:
    """案件を新規作成する。Idempotency-Key があれば重複作成を防ぐ。"""
    tenant_id = repo.tenant_id

    # 冪等: 同一キーの再送には初回の結果を返し、副作用を再実行しない。
    if idempotency_key:
        cached = idempotency_store.get(tenant_id, idempotency_key)
        if cached is not None:
            return cached

    supplier_id = _resolve_supplier(repo, body.company.strip())
    spec_id = _resolve_spec(repo, body.product.strip())
    case_no = _numbering.next_case_no(session, tenant_id)

    case = repo.add(
        m.NegotiationCase(
            case_no=case_no,
            supplier_id=supplier_id,
            spec_id=spec_id,
            period=body.target_period,
            status="交渉前",
            proposed_price=body.quoted_price,
            created_by=user_id,
            data_origin="アプリ登録",
        )
    )
    session.flush()
    detail = build_case_detail(session, case)
    session.commit()

    emit_audit("case.create", tenant_id=tenant_id, user_id=user_id, trace_id=trace_id, case_no=case_no)

    if idempotency_key:
        idempotency_store.put(tenant_id, idempotency_key, detail)
    return detail


@router.get("/cases/{case_no}", response_model=CaseDetail)
def get_case(
    case_no: str,
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_current_tenant),
) -> CaseDetail:
    """案件詳細を返す。"""
    case = load_case(session, tenant_id, case_no)
    if case is None:
        raise ApiProblem(404, "案件が見つかりません", detail=f"{case_no} は存在しません。")
    return build_case_detail(session, case)


@router.patch("/cases/{case_no}/status", response_model=CaseDetail)
def update_status(
    case_no: str,
    body: CaseStatusUpdate,
    session: Session = Depends(get_session),
    repo: TenantScopedRepository = Depends(get_repo),
    user_id: str = Depends(get_current_user),
    trace_id: str = Depends(get_trace_id),
) -> CaseDetail:
    """案件の状態を遷移させる（交渉前 → 交渉中 → 完了）。"""
    case = load_case(session, repo.tenant_id, case_no)
    if case is None:
        raise ApiProblem(404, "案件が見つかりません", detail=f"{case_no} は存在しません。")
    case.status = ui_status_to_db(body.status)
    session.flush()
    detail = build_case_detail(session, case)
    session.commit()
    emit_audit(
        "case.status_change",
        tenant_id=repo.tenant_id,
        user_id=user_id,
        trace_id=trace_id,
        case_no=case_no,
        status=body.status,
    )
    return detail
