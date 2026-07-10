"""results.py — 交渉結果の記録・取得（画面⑤・FR-11/12/13）。

- GET  /reasons                    … 変動理由マスタ（RC-01〜10・共有参照）。
- POST /cases/{case_no}/result     … 決着記録を保存（見積比・目標達成度はサーバー側算出）。
                                      案件ステータスを「完了」に遷移。冪等キー対応。
- GET  /cases/{case_no}/result     … 保存済みの結果記録（無ければ null）。

判断継承（BR-10）: ここで保存した結果は、同一スペック/取引先の新規案件の過去経緯
（search.py /past-cases の **DB 由来経路**）に現れる。書込→読取のループがこれで閉じる。

【KRE インデックス同期について】[現状の設計・重要]:
本エンドポイントは negotiation_results（正本 DB）を更新するのみで、KRE の AI Search インデックス
／グラフへの反映は行わない。KRE への反映は ``kre/scripts/build_index`` の**再実行（手動/バッチ）**で
拾う設計（設計 v3 §3.2・§4.3 の整合 sync 方針）。リアルタイム同期は将来課題であり、
retrieval_config の sync ノブ（§11）で有効化する受け皿を残している。したがって past-cases の
**DB 由来経路は即時**に新結果を反映するが、KRE 検索側は次回インデックス再構築まで反映されない。
DB アクセスは Repository 経由（§2.8 ルール1）。共有マスタ（reasons）のみ非テナントで読む。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user,
    get_repo,
    get_session,
    get_trace_id,
    idempotency_store,
)
from app.api.lines import _compute as compute_three_lines
from app.db import models as m
from app.db.repository import TenantScopedRepository
from app.errors import ApiProblem
from app.observability.logging import emit_audit
from app.schemas import ReasonDirection, ReasonTag, ResultInput, ResultRecord
from app.services.case_view import load_case, product_display

router = APIRouter(tags=["results"])

# DB の影響方向（↑/↓/±）→ フロントの向き（up/down/both）。
_DIRECTION: dict[str, ReasonDirection] = {"↑": "up", "↓": "down", "±": "both"}


def _reason_direction(value: Optional[str]) -> ReasonDirection:
    return _DIRECTION.get(value or "", "both")


def _load_reason_tags(session: Session) -> list[ReasonTag]:
    """変動理由マスタ（共有参照・テナント非依存）を ReasonTag へ写像して返す。"""
    rows = session.execute(
        select(m.RateChangeReason).order_by(m.RateChangeReason.reason_id)
    ).scalars().all()
    return [
        ReasonTag(code=r.reason_id, label=r.reason_name, direction=_reason_direction(r.impact_direction))
        for r in rows
    ]


# ---- 自動計算（フロント workspaceApi の calc と一致させる） --------------------
def _quote_diff_pct(settled: float, quoted: float) -> float:
    """見積比（%）: (決着 − 見積) / 見積 × 100。小数第1位。マイナスは見積より安く決着。"""
    if quoted <= 0:
        return 0.0
    return round((settled - quoted) / quoted * 1000) / 10


def _achievement_pct(settled: float, target: float, walkaway: float) -> float:
    """目標達成度（%）: 撤退で0%、目標で100%（目標より安ければ100%上限）。"""
    if walkaway <= target:
        return 100.0 if settled <= target else 0.0
    pct = (walkaway - settled) / (walkaway - target) * 100
    return float(max(0, min(100, round(pct))))


@router.get("/reasons", response_model=list[ReasonTag])
def list_reasons(session: Session = Depends(get_session)) -> list[ReasonTag]:
    """変動理由マスタ（RC-01〜10）を返す。共有参照のためテナント非依存で読む。"""
    return _load_reason_tags(session)


def _target_walkaway(repo: TenantScopedRepository, case: m.NegotiationCase, quoted: float) -> tuple[float, float]:
    """3ラインの目標/撤退を取り出す（未算出時は見積へフォールバック・フロントと同挙動）。"""
    lines = compute_three_lines(repo, case)
    by = {ln.type: ln.value for ln in lines.lines}
    return float(by.get("target", quoted)), float(by.get("walkaway", quoted))


def _build_record(
    repo: TenantScopedRepository, case: m.NegotiationCase, result: m.NegotiationResult
) -> ResultRecord:
    """negotiation_results から ResultRecord を組み立てる（見積比は都度再計算）。"""
    supplier = repo.get(m.Supplier, supplier_id=case.supplier_id)
    spec = repo.get(m.ProductSpec, spec_id=case.spec_id)
    product = repo.get(m.Product, product_id=spec.product_id) if spec is not None else None
    quoted = float(case.proposed_price or 0)
    settled = float(result.final_price or 0)
    saved = result.updated_at or result.created_at
    return ResultRecord(
        settled_price=settled,
        delivery_timing=result.delivery_term or "",
        payment_terms=result.payment_site or "",
        reason_codes=list(result.accepted_reasons or []),
        note=result.staff_memo or "",
        quote_diff_pct=_quote_diff_pct(settled, quoted),
        achievement_pct=float(result.achievement) if result.achievement is not None else 0.0,
        case_no=case.case_no,
        company=supplier.supplier_name if supplier else "",
        product=product_display(product, spec),
        period=case.period or "",
        saved_at=(saved or datetime.now(timezone.utc)).isoformat(),
    )


@router.post("/cases/{case_no}/result", response_model=ResultRecord, status_code=201)
def save_result(
    case_no: str,
    body: ResultInput,
    repo: TenantScopedRepository = Depends(get_repo),
    user_id: str = Depends(get_current_user),
    trace_id: str = Depends(get_trace_id),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> ResultRecord:
    """決着記録を保存し、案件を完了に遷移する。見積比・目標達成度はサーバー側で算出。"""
    tenant_id = repo.tenant_id
    if idempotency_key:
        cached = idempotency_store.get(tenant_id, f"result:{idempotency_key}")
        if cached is not None:
            return cached

    case = load_case(repo, case_no)
    if case is None:
        raise ApiProblem(404, "案件が見つかりません", detail=f"{case_no} は存在しません。")

    # 変動理由タグを RC マスタで検証（未知コードは 422）。
    valid_codes = {r.code for r in _load_reason_tags(repo.session)}
    unknown = [c for c in body.reason_codes if c not in valid_codes]
    if unknown:
        raise ApiProblem(
            422, "変動理由タグが不正です", detail=f"未知の理由コード: {', '.join(unknown)}",
            extra={"unknown_codes": unknown},
        )

    quoted = float(case.proposed_price or 0)
    target, walkaway = _target_walkaway(repo, case, quoted)
    achievement = _achievement_pct(body.settled_price, target, walkaway)

    # 1案件1結果（既存があれば更新＝再記録）。
    result = repo.get(m.NegotiationResult, case_no=case_no)
    if result is None:
        result = repo.add(m.NegotiationResult(case_no=case_no))
    result.result_date = date.today()
    result.final_price = body.settled_price
    result.delivery_term = body.delivery_timing
    result.payment_site = body.payment_terms
    result.vs_quote = body.settled_price - quoted  # 見積比 改善 ¥（負=見積より安い）
    result.achievement = achievement
    result.result_tags = list(body.reason_codes)
    result.accepted_reasons = list(body.reason_codes)
    result.staff_memo = body.note
    result.data_origin = "アプリ登録"

    # 案件ステータスを完了へ（BR-10: 以後この決着は同一スペックの新案件の過去経緯に現れる）。
    case.status = "完了"
    repo.session.flush()
    record = _build_record(repo, case, result)
    repo.session.commit()

    emit_audit("result.save", tenant_id=tenant_id, user_id=user_id, trace_id=trace_id,
               case_no=case_no, achievement=achievement)
    if idempotency_key:
        idempotency_store.put(tenant_id, f"result:{idempotency_key}", record)
    return record


@router.get("/cases/{case_no}/result", response_model=Optional[ResultRecord])
def get_result(
    case_no: str,
    repo: TenantScopedRepository = Depends(get_repo),
) -> Optional[ResultRecord]:
    """保存済みの結果記録を返す（無ければ null）。"""
    case = load_case(repo, case_no)
    if case is None:
        raise ApiProblem(404, "案件が見つかりません", detail=f"{case_no} は存在しません。")
    result = repo.get(m.NegotiationResult, case_no=case_no)
    if result is None:
        return None
    return _build_record(repo, case, result)
