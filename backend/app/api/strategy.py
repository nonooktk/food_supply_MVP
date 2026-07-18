"""strategy.py — 作戦シートの AI 生成・保存（画面④・FR-08）。

- POST /cases/{case_no}/strategy/generate … KRE 供給（過去経緯・グラフ・引用元）＋本体算出
  （3ライン・自社計画・相場）を根拠に交渉ポイント3件＋シナリオを生成し、strategy_sheets に保存。
- GET  /cases/{case_no}/strategy          … 保存済み下書き（無ければ null）。
- PUT  /cases/{case_no}/strategy          … 編集済み下書きを保存。

KRE は DI（USE_KRE_STUB で stub ⇄ 本実装）。AI は価格を決めない（RFP 2-3）。Citation は
KRE の citations と DB の過去決着から構築する。生成は同期（数秒）。DB は Repository 経由。
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_repo, get_retrieval_engine, get_trace_id
from app.api.lines import _compute as compute_three_lines
from app.db import models as m
from app.db.repository import TenantScopedRepository
from app.errors import ApiProblem
from app.llm.strategy_generator import PastCaseFact, StrategyContext, generate_strategy
from app.observability.logging import emit_audit, emit_error
from app.schemas import Citation, StrategyDraft, StrategyPoint
from app.services.case_view import load_case, product_display
from app.services.pricing import latest_market_rate, plan_for_spec
from kre.contract import RetrieveQuery, RetrieveRequest

router = APIRouter(tags=["strategy"])


def _result_snippet(result: m.NegotiationResult) -> str:
    bits = []
    if result.final_price is not None:
        bits.append(f"決着 ¥{int(result.final_price)}/kg")
    if result.staff_memo:
        bits.append(result.staff_memo)
    elif result.result_tags:
        bits.append("・".join(result.result_tags))
    # 次回への申し送り（次回案件の判断材料）を明示ラベル付きで提示（issue #6 Want）。
    if result.handover_note:
        bits.append(f"申し送り: {result.handover_note}")
    return "。".join(bits) if bits else "過去の決着記録。"


def _past_facts_and_citations(
    repo: TenantScopedRepository, current: m.NegotiationCase
) -> tuple[list[PastCaseFact], dict[str, Citation]]:
    """DB の関連過去決着から、生成用の事実と引用元プール（case_no→Citation）を作る。"""
    facts: list[PastCaseFact] = []
    pool: dict[str, Citation] = {}
    for result, past in repo.related_past_results(current.spec_id, current.supplier_id, current.case_no):
        supplier = repo.get(m.Supplier, supplier_id=past.supplier_id)
        spec = repo.get(m.ProductSpec, spec_id=past.spec_id)
        product = repo.get(m.Product, product_id=spec.product_id) if spec is not None else None
        company = supplier.supplier_name if supplier else ""
        prod_name = product_display(product, spec)
        snippet = _result_snippet(result)
        relation = None if past.spec_id == current.spec_id else "same_supplier"
        facts.append(
            PastCaseFact(
                case_no=past.case_no,
                company=company,
                product=prod_name,
                period=past.period or "",
                settled_price=float(result.final_price) if result.final_price is not None else 0.0,
                snippet=snippet,
                relation=relation,
            )
        )
        pool[past.case_no] = Citation(
            case_no=past.case_no, company=company, product=prod_name, snippet=snippet
        )
    return facts, pool


def _merge_kre_citations(
    repo: TenantScopedRepository, kre_citations, pool: dict[str, Citation]
) -> str:
    """KRE の citations を引用元プールへ統合（case ヒットの ref を DB 解決）。既存 DB 由来を優先。"""
    for c in kre_citations:
        ref = getattr(c, "ref", None)
        if ref is None or ref.table != "negotiation_cases":
            continue
        case_no = ref.pk
        if case_no in pool:
            continue  # DB 由来を優先
        case = repo.get(m.NegotiationCase, case_no=case_no)
        if case is not None:
            supplier = repo.get(m.Supplier, supplier_id=case.supplier_id)
            spec = repo.get(m.ProductSpec, spec_id=case.spec_id)
            product = repo.get(m.Product, product_id=spec.product_id) if spec is not None else None
            pool[case_no] = Citation(
                case_no=case_no,
                company=supplier.supplier_name if supplier else "",
                product=product_display(product, spec),
                snippet=c.label,
            )
        else:
            # DB に無い（別データ）場合は KRE のラベルをそのまま引用元にする。
            pool[case_no] = Citation(case_no=case_no, company="", product="", snippet=c.label)
    return ""


def _build_context(
    repo: TenantScopedRepository, case: m.NegotiationCase, engine, trace_id: str
) -> tuple[StrategyContext, dict[str, Citation]]:
    """生成に渡す StrategyContext と引用元プールを組み立てる。"""
    lines = compute_three_lines(repo, case)
    by_type = {ln.type: ln.value for ln in lines.lines}
    plan_row = plan_for_spec(repo, case.spec_id, case.period)
    latest = latest_market_rate(repo, case.spec_id)

    facts, pool = _past_facts_and_citations(repo, case)

    # KRE を契約越しに呼び、グラフ文脈・引用元を得る（DI・越境ゼロは KRE 側）。ベストエフォート。
    graph_summary = ""
    try:
        res = engine.retrieve(
            RetrieveRequest(
                tenant_id=repo.tenant_id,
                query=RetrieveQuery(spec_id=case.spec_id, supplier_id=case.supplier_id),
            )
        )
        graph_summary = res.graph_context.summary_text or ""
        _merge_kre_citations(repo, res.citations, pool)
    except Exception as exc:  # noqa: BLE001 - KRE 障害は生成を止めない
        emit_error("strategy.kre_retrieve", tenant_id=repo.tenant_id, trace_id=trace_id,
                   error=type(exc).__name__, case_no=case.case_no)

    supplier = repo.get(m.Supplier, supplier_id=case.supplier_id)
    spec = repo.get(m.ProductSpec, spec_id=case.spec_id)
    product = repo.get(m.Product, product_id=spec.product_id) if spec is not None else None

    ctx = StrategyContext(
        company=supplier.supplier_name if supplier else "",
        product=product_display(product, spec),
        quoted_price=float(case.proposed_price or 0),
        current_price=float(case.current_price or 0),
        market_rate=float(latest.price_yen_kg) if latest and latest.price_yen_kg is not None else 0.0,
        yoy_rate=float(latest.yoy_change) / 100.0 if latest and latest.yoy_change is not None else None,
        target=float(by_type.get("target", 0)),
        landing=float(by_type.get("landing", 0)),
        walkaway=float(by_type.get("walkaway", 0)),
        plan_price=float(plan_row.planned_price or 0) if plan_row else 0.0,
        monthly_volume=float(plan_row.volume_kg_month or 0) if plan_row else 0.0,
        annual_volume=float(plan_row.annual_volume_kg or 0) if plan_row else 0.0,
        ceiling_price=float(plan_row.max_acceptable_price or 0) if plan_row else 0.0,
        past_cases=facts,
        graph_summary=graph_summary,
    )
    return ctx, pool


def _to_draft(generated: dict, pool: dict[str, Citation]) -> StrategyDraft:
    """生成結果（citation_case_nos）を StrategyDraft（Citation 付き）へ写像する。"""
    points: list[StrategyPoint] = []
    for p in generated.get("points", []):
        cites = [pool[cn] for cn in p.get("citation_case_nos", []) if cn in pool]
        points.append(StrategyPoint(text=p["text"], citations=cites))
    return StrategyDraft(points=points, scenario=generated.get("scenario", ""))


def _persist_draft(repo: TenantScopedRepository, case_no: str, draft: StrategyDraft) -> None:
    """作戦シートへ AI 生成物を保存する（ai_points は JSON 文字列、ai_scenario はテキスト）。"""
    sheet = repo.get(m.StrategySheet, case_no=case_no)
    if sheet is None:
        sheet = repo.add(m.StrategySheet(case_no=case_no))
        repo.session.flush()
    sheet.ai_points = json.dumps(
        [pt.model_dump(by_alias=True) for pt in draft.points], ensure_ascii=False
    )
    sheet.ai_scenario = draft.scenario
    repo.session.flush()
    repo.session.commit()


def _load_draft(repo: TenantScopedRepository, case_no: str) -> Optional[StrategyDraft]:
    sheet = repo.get(m.StrategySheet, case_no=case_no)
    if sheet is None or (not sheet.ai_scenario and not sheet.ai_points):
        return None
    points: list[StrategyPoint] = []
    if sheet.ai_points:
        try:
            for p in json.loads(sheet.ai_points):
                points.append(StrategyPoint.model_validate(p))
        except (json.JSONDecodeError, ValueError):
            points = []
    return StrategyDraft(points=points, scenario=sheet.ai_scenario or "")


@router.post("/cases/{case_no}/strategy/generate", response_model=StrategyDraft)
def generate(
    case_no: str,
    repo: TenantScopedRepository = Depends(get_repo),
    engine=Depends(get_retrieval_engine),
    user_id: str = Depends(get_current_user),
    trace_id: str = Depends(get_trace_id),
) -> StrategyDraft:
    """交渉ポイント3件＋シナリオを AI 生成して保存する。"""
    case = load_case(repo, case_no)
    if case is None:
        raise ApiProblem(404, "案件が見つかりません", detail=f"{case_no} は存在しません。")

    ctx, pool = _build_context(repo, case, engine, trace_id)
    try:
        generated = generate_strategy(ctx)
    except Exception as exc:  # noqa: BLE001 - 生成失敗はユーザーに 502 で返す
        emit_error("strategy.generate", tenant_id=repo.tenant_id, trace_id=trace_id,
                   error=type(exc).__name__, case_no=case_no)
        raise ApiProblem(502, "AI 生成に失敗しました", detail="時間をおいて再実行してください。") from exc

    draft = _to_draft(generated, pool)
    _persist_draft(repo, case_no, draft)
    emit_audit("strategy.generate", tenant_id=repo.tenant_id, user_id=user_id,
               trace_id=trace_id, case_no=case_no, points=len(draft.points))
    return draft


@router.get("/cases/{case_no}/strategy", response_model=Optional[StrategyDraft])
def get_strategy(
    case_no: str,
    repo: TenantScopedRepository = Depends(get_repo),
) -> Optional[StrategyDraft]:
    """保存済みの作戦シート下書きを返す（無ければ null）。"""
    if load_case(repo, case_no) is None:
        raise ApiProblem(404, "案件が見つかりません", detail=f"{case_no} は存在しません。")
    return _load_draft(repo, case_no)


@router.put("/cases/{case_no}/strategy", response_model=StrategyDraft)
def save_strategy(
    case_no: str,
    body: StrategyDraft,
    repo: TenantScopedRepository = Depends(get_repo),
    user_id: str = Depends(get_current_user),
    trace_id: str = Depends(get_trace_id),
) -> StrategyDraft:
    """編集済みの作戦シート下書きを保存する。"""
    if load_case(repo, case_no) is None:
        raise ApiProblem(404, "案件が見つかりません", detail=f"{case_no} は存在しません。")
    _persist_draft(repo, case_no, body)
    emit_audit("strategy.save", tenant_id=repo.tenant_id, user_id=user_id,
               trace_id=trace_id, case_no=case_no)
    return body
