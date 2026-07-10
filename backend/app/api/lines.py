"""lines.py — 3ライン（目標/着地/撤退）の算出と保存（画面③・FR-05〜09）。

- GET /cases/{case_no}/three-lines … CALC_RULE_V1 で自動算出し、保存済みの手修正を重ねて返す。
- PUT /cases/{case_no}/three-lines … 手修正値（＋理由）を strategy_sheets に保存して再返却。

算出はサーバー側で実行（AI は数値を生成しない・RFP 2-3）。未修正ラインは取得のたびに最新の
相場・計画から再算出する（3本まとめて凍結しない）。手修正ラインのみ *_final に保存する。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_repo, get_session, get_trace_id
from app.db import models as m
from app.db.repository import TenantScopedRepository
from app.db.seams import CALC_RULE_V1_LABEL
from app.errors import ApiProblem
from app.observability.logging import emit_audit
from app.schemas import AnnualImpact, ThreeLine, ThreeLineResult, ThreeLineSaveInput
from app.services.case_view import load_case
from app.services.pricing import latest_market_rate, past_settled_prices, plan_for_spec
from app.services.three_lines import (
    PlanInputs,
    RateInputs,
    calc_annual_impact,
    calc_auto_lines,
    is_plan_ready,
)

router = APIRouter(tags=["lines"])

_LINE_TYPES = ("target", "landing", "walkaway")


def _load_sheet(session: Session, tenant_id: str, case_no: str) -> Optional[m.StrategySheet]:
    return session.execute(
        select(m.StrategySheet).where(
            m.StrategySheet.tenant_id == tenant_id, m.StrategySheet.case_no == case_no
        )
    ).scalar_one_or_none()


def _empty_result() -> ThreeLineResult:
    """算出に必要な入力（②自社計画）が未充足のときの結果。"""
    return ThreeLineResult(lines=[], impact=AnnualImpact(target_yen=0, landing_yen=0), ready=False)


def _compute(session: Session, tenant_id: str, case: m.NegotiationCase) -> ThreeLineResult:
    """CALC_RULE_V1 の自動算出に保存済み手修正を重ねた結果を返す。"""
    latest = latest_market_rate(session, tenant_id, case.spec_id)
    plan_row = plan_for_spec(session, tenant_id, case.spec_id, case.period)
    if plan_row is None:
        return _empty_result()

    plan = PlanInputs(
        plan_price=float(plan_row.planned_price or 0),
        ceiling_price=float(plan_row.max_acceptable_price or 0),
        monthly_volume=float(plan_row.volume_kg_month or 0),
    )
    if not is_plan_ready(plan):
        return _empty_result()

    market = float(latest.price_yen_kg) if latest and latest.price_yen_kg is not None else 0.0
    yoy = float(latest.yoy_change) / 100.0 if latest and latest.yoy_change is not None else 0.0
    rate = RateInputs(
        market_rate=market,
        current_price=float(case.current_price or 0),
        yoy_rate=yoy,
    )
    past = past_settled_prices(session, tenant_id, case.spec_id, case.case_no)
    auto = calc_auto_lines(rate, plan, past)

    # 保存済みの手修正を重ねる（*_final が入っているラインのみ手修正扱い）。
    sheet = _load_sheet(session, tenant_id, case.case_no)
    finals: dict[str, Optional[float]] = {t: None for t in _LINE_TYPES}
    reason = None
    if sheet is not None:
        finals["target"] = None if sheet.target_final is None else float(sheet.target_final)
        finals["landing"] = None if sheet.landing_final is None else float(sheet.landing_final)
        finals["walkaway"] = None if sheet.walkaway_final is None else float(sheet.walkaway_final)
        reason = sheet.line_edit_reason

    lines: list[ThreeLine] = []
    effective: dict[str, float] = {}
    for t in _LINE_TYPES:
        auto_v = float(auto[t])
        final_v = finals[t]
        # 手修正とみなすのは「確定値があり、かつ自動算出値と異なる」ときのみ。
        # （seed の作戦シートは未修正ラインにも確定値が入るため、値一致は未修正扱いにする）
        edited = final_v is not None and round(final_v) != round(auto_v)
        if edited:
            lines.append(ThreeLine(type=t, value=final_v, auto_value=auto_v, is_edited=True, edit_reason=reason))
            effective[t] = final_v
        else:
            lines.append(ThreeLine(type=t, value=auto_v, auto_value=auto_v, is_edited=False))
            effective[t] = auto_v

    impact = calc_annual_impact(plan, effective["target"], effective["landing"])
    return ThreeLineResult(
        lines=lines,
        impact=AnnualImpact(target_yen=impact["target_yen"], landing_yen=impact["landing_yen"]),
        ready=True,
    )


@router.get("/cases/{case_no}/three-lines", response_model=ThreeLineResult)
def get_three_lines(
    case_no: str,
    session: Session = Depends(get_session),
    repo: TenantScopedRepository = Depends(get_repo),
) -> ThreeLineResult:
    """3ラインを自動算出（＋保存済み手修正）で返す。"""
    case = load_case(session, repo.tenant_id, case_no)
    if case is None:
        raise ApiProblem(404, "案件が見つかりません", detail=f"{case_no} は存在しません。")
    return _compute(session, repo.tenant_id, case)


@router.put("/cases/{case_no}/three-lines", response_model=ThreeLineResult)
def save_three_lines(
    case_no: str,
    body: ThreeLineSaveInput,
    session: Session = Depends(get_session),
    repo: TenantScopedRepository = Depends(get_repo),
    user_id: str = Depends(get_current_user),
    trace_id: str = Depends(get_trace_id),
) -> ThreeLineResult:
    """手修正値（＋理由）を保存する。修正済みラインのみ *_final に格納する。"""
    tenant_id = repo.tenant_id
    case = load_case(session, tenant_id, case_no)
    if case is None:
        raise ApiProblem(404, "案件が見つかりません", detail=f"{case_no} は存在しません。")

    submitted = {ln.type: ln for ln in body.lines}
    edited_reasons = [f"{ln.type}: {ln.edit_reason}" for ln in body.lines if ln.is_edited and ln.edit_reason]

    # 現在の自動算出値（保存時のスナップショット用）。
    auto_result = _compute(session, tenant_id, case)
    auto_by_type = {ln.type: ln.auto_value for ln in auto_result.lines}

    sheet = _load_sheet(session, tenant_id, case_no)
    if sheet is None:
        sheet = repo.add(m.StrategySheet(case_no=case_no))
        session.flush()

    for t in _LINE_TYPES:
        ln = submitted.get(t)
        auto_v = auto_by_type.get(t)
        setattr(sheet, f"{t}_auto", auto_v)
        # 手修正されたラインのみ確定値を保存。未修正は None（取得時に再算出）。
        setattr(sheet, f"{t}_final", ln.value if (ln and ln.is_edited) else None)

    sheet.line_edit_reason = " / ".join(edited_reasons) if edited_reasons else None
    sheet.calc_version = CALC_RULE_V1_LABEL
    sheet.saved_at = datetime.now(timezone.utc)
    sheet.data_origin = "アプリ登録"

    # 影響額スナップショット（対計画・年間）。
    plan_row = plan_for_spec(session, tenant_id, case.spec_id, case.period)
    if plan_row is not None:
        annual = int(plan_row.annual_volume_kg or (int(plan_row.volume_kg_month or 0) * 12))
        eff = {ln.type: ln.value for ln in _compute(session, tenant_id, case).lines}
        pp = float(plan_row.planned_price or 0)
        sheet.impact_target = int((pp - eff.get("target", 0)) * annual)
        sheet.impact_landing = int((pp - eff.get("landing", 0)) * annual)
        sheet.impact_walkaway = int((pp - eff.get("walkaway", 0)) * annual)
    if case.current_price is not None and case.proposed_price is not None:
        sheet.price_diff = float(case.proposed_price) - float(case.current_price)

    session.flush()
    session.commit()

    emit_audit("lines.save", tenant_id=tenant_id, user_id=user_id, trace_id=trace_id, case_no=case_no)
    return _compute(session, tenant_id, case)
