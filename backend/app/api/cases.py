"""cases.py — 交渉案件の CRUD・検索・状態管理（画面①③）。

- GET  /cases                … 一覧・検索（keyword / status）
- POST /cases                … 作成（NumberingService 採番・冪等キー・監査）
- GET  /cases/{case_no}      … 詳細
- PATCH /cases/{case_no}/status … 状態遷移

読み書きとも ``TenantScopedRepository``（get_repo）経由に統一し、テナント境界を強制する
（§2.8 ルール1・二層防御の第1層）。採番のみ内部ユーティリティ（numbering.py）を例外的に使う。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, Query

from app.api.deps import get_current_user, get_repo, get_trace_id, idempotency_store
from app.db import models as m
from app.db.numbering import SequentialNumberingService
from app.db.repository import TenantScopedRepository
from app.errors import ApiProblem
from app.observability.logging import emit_audit
from app.schemas import CaseCreateInput, CaseDetail, CaseListResult, CaseStatusUpdate
from app.services.case_view import build_case_detail, load_case, ui_status_to_db

router = APIRouter(tags=["cases"])
_numbering = SequentialNumberingService()


@router.get("/cases", response_model=CaseListResult)
def list_cases(
    repo: TenantScopedRepository = Depends(get_repo),
    keyword: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
) -> CaseListResult:
    """案件一覧を返す（保存時期の新しい順）。keyword / status で絞り込む。"""
    cases = repo.list(m.NegotiationCase)
    # 保存時期の新しい順（updated_at 降順）。
    cases.sort(key=lambda c: c.updated_at or 0, reverse=True)

    items: list[CaseDetail] = [build_case_detail(repo, c) for c in cases]

    # 表示名を含めた絞り込みはアプリ層で実施（company/product は結合後の表示名）。
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

    # supplier_id はテナントスコープ済み Repository で確認する。他テナントの ID も
    # 見つからないため、取引先マスタを経由しない案件作成・テナント越境をともに防ぐ。
    supplier = repo.get(m.Supplier, supplier_id=body.supplier_id)
    if supplier is None:
        raise ApiProblem(422, "取引先が未登録です", detail="登録済みの取引先を選択してください。")

    spec_id = _resolve_spec(repo, body.product.strip())
    # 採番は内部ユーティリティ（tenant 必須・Repository 外の例外。numbering.py の説明参照）。
    case_no = _numbering.next_case_no(repo.session, tenant_id)

    case = repo.add(
        m.NegotiationCase(
            case_no=case_no,
            supplier_id=supplier.supplier_id,
            spec_id=spec_id,
            period=body.target_period,
            status="交渉前",
            proposed_price=body.quoted_price,
            created_by=user_id,
            data_origin="アプリ登録",
        )
    )
    repo.session.flush()
    detail = build_case_detail(repo, case)
    repo.session.commit()

    emit_audit("case.create", tenant_id=tenant_id, user_id=user_id, trace_id=trace_id, case_no=case_no)

    if idempotency_key:
        idempotency_store.put(tenant_id, idempotency_key, detail)
    return detail


@router.get("/cases/{case_no}", response_model=CaseDetail)
def get_case(
    case_no: str,
    repo: TenantScopedRepository = Depends(get_repo),
) -> CaseDetail:
    """案件詳細を返す。"""
    case = load_case(repo, case_no)
    if case is None:
        raise ApiProblem(404, "案件が見つかりません", detail=f"{case_no} は存在しません。")
    return build_case_detail(repo, case)


@router.patch("/cases/{case_no}/status", response_model=CaseDetail)
def update_status(
    case_no: str,
    body: CaseStatusUpdate,
    repo: TenantScopedRepository = Depends(get_repo),
    user_id: str = Depends(get_current_user),
    trace_id: str = Depends(get_trace_id),
) -> CaseDetail:
    """案件の状態を遷移させる（交渉前 → 交渉中 → 完了）。"""
    case = load_case(repo, case_no)
    if case is None:
        raise ApiProblem(404, "案件が見つかりません", detail=f"{case_no} は存在しません。")
    case.status = ui_status_to_db(body.status)
    repo.session.flush()
    detail = build_case_detail(repo, case)
    repo.session.commit()
    emit_audit(
        "case.status_change",
        tenant_id=repo.tenant_id,
        user_id=user_id,
        trace_id=trace_id,
        case_no=case_no,
        status=body.status,
    )
    return detail
