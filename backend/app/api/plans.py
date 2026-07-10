"""plans.py — 自社計画（画面②の計画フォーム・F-04）。

- GET /cases/{case_no}/plan … 案件のスペックの自社計画を返す（無ければ空）。
- PUT /cases/{case_no}/plan … 自社計画を保存（upsert）。3ライン算出の入力になる。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_repo, get_session, get_trace_id
from app.db import models as m
from app.db.repository import TenantScopedRepository
from app.errors import ApiProblem
from app.observability.logging import emit_audit
from app.schemas import CompanyPlan
from app.services.case_view import load_case
from app.services.pricing import plan_for_spec

router = APIRouter(tags=["plans"])


def _to_schema(plan: m.CompanyPlan | None) -> CompanyPlan:
    if plan is None:
        return CompanyPlan(target_cost_rate=0, plan_price=0, monthly_volume=0, ceiling_price=0)
    return CompanyPlan(
        target_cost_rate=float(plan.target_cost_rate) if plan.target_cost_rate is not None else 0,
        plan_price=float(plan.planned_price) if plan.planned_price is not None else 0,
        monthly_volume=float(plan.volume_kg_month) if plan.volume_kg_month is not None else 0,
        ceiling_price=float(plan.max_acceptable_price) if plan.max_acceptable_price is not None else 0,
    )


@router.get("/cases/{case_no}/plan", response_model=CompanyPlan)
def get_plan(
    case_no: str,
    session: Session = Depends(get_session),
    repo: TenantScopedRepository = Depends(get_repo),
) -> CompanyPlan:
    """案件のスペックの自社計画を返す。"""
    case = load_case(session, repo.tenant_id, case_no)
    if case is None:
        raise ApiProblem(404, "案件が見つかりません", detail=f"{case_no} は存在しません。")
    plan = plan_for_spec(session, repo.tenant_id, case.spec_id, case.period)
    return _to_schema(plan)


@router.put("/cases/{case_no}/plan", response_model=CompanyPlan)
def save_plan(
    case_no: str,
    body: CompanyPlan,
    session: Session = Depends(get_session),
    repo: TenantScopedRepository = Depends(get_repo),
    user_id: str = Depends(get_current_user),
    trace_id: str = Depends(get_trace_id),
) -> CompanyPlan:
    """自社計画を保存（upsert）。既存があれば更新、無ければ作成する。"""
    case = load_case(session, repo.tenant_id, case_no)
    if case is None:
        raise ApiProblem(404, "案件が見つかりません", detail=f"{case_no} は存在しません。")

    plan = plan_for_spec(session, repo.tenant_id, case.spec_id, case.period)
    if plan is None:
        plan = repo.add(m.CompanyPlan(spec_id=case.spec_id, period=case.period))
    plan.target_cost_rate = body.target_cost_rate
    plan.planned_price = body.plan_price
    plan.volume_kg_month = int(body.monthly_volume)
    plan.annual_volume_kg = int(body.monthly_volume) * 12
    plan.max_acceptable_price = body.ceiling_price
    session.flush()
    session.commit()

    emit_audit("plan.save", tenant_id=repo.tenant_id, user_id=user_id, trace_id=trace_id, case_no=case_no)
    return _to_schema(plan)
