"""search.py — 過去経緯（画面②の過去経緯パネル・FR-03）。KRE 呼出の BFF。

- GET /cases/{case_no}/past-cases … 同一スペック/取引先の過去決着を返す。

設計 v3 §5.1 のとおり、本エンドポイントは KRE（RetrievalEngine）を DI で呼ぶ BFF。
MVP では過去経緯の実データ（決着単価等）を DB から構築し、KRE スタブ（USE_KRE_STUB=true）を
契約越しに呼び出してグラフ文脈・引用元を得る（越境ゼロは KRE 契約側で担保・§10.5(4)）。
KRE 本実装が入ったら、ヒットの ref 解決に置き換える。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_tenant, get_retrieval_engine, get_session
from app.db import models as m
from app.errors import ApiProblem
from app.schemas import Citation, PastCase, PastCaseResult
from app.services.case_view import load_case, product_display
from kre.contract import RetrieveQuery, RetrieveRequest

router = APIRouter(tags=["search"])


def _build_citation(case: m.NegotiationCase, result: m.NegotiationResult, company: str, product: str) -> Citation:
    """過去案件の決着記録から引用元スニペットを組み立てる。"""
    bits = []
    if result.final_price is not None:
        bits.append(f"決着 ¥{int(result.final_price)}/kg")
    if result.staff_memo:
        bits.append(result.staff_memo)
    elif result.result_tags:
        bits.append("・".join(result.result_tags))
    snippet = "。".join(bits) if bits else "過去の決着記録。"
    return Citation(case_no=case.case_no, company=company, product=product, snippet=snippet)


@router.get("/cases/{case_no}/past-cases", response_model=PastCaseResult)
def get_past_cases(
    case_no: str,
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_current_tenant),
    engine=Depends(get_retrieval_engine),
) -> PastCaseResult:
    """当該案件のスペック/取引先に関連する過去決着を返す。"""
    current = load_case(session, tenant_id, case_no)
    if current is None:
        raise ApiProblem(404, "案件が見つかりません", detail=f"{case_no} は存在しません。")

    # KRE を契約越しに呼ぶ（DI・グラフ文脈/引用元供給。越境ゼロは KRE 側で強制）。
    # KRE はエンリッチメントのためベストエフォート。障害時も DB 由来の過去経緯は返す
    # （デザインガイド §3.2 の部分エラー耐性）。本実装導入時は hits.ref 解決に置き換える。
    try:
        engine.retrieve(
            RetrieveRequest(
                tenant_id=tenant_id,
                query=RetrieveQuery(spec_id=current.spec_id, supplier_id=current.supplier_id),
            )
        )
    except Exception:  # noqa: BLE001 - KRE 障害は過去経緯表示を止めない
        pass

    try:
        # 過去決着の実データを DB から構築（同一スペック=直接一致 / 同一取引先=グラフ補完）。
        rows = session.execute(
            select(m.NegotiationResult, m.NegotiationCase)
            .join(
                m.NegotiationCase,
                (m.NegotiationResult.tenant_id == m.NegotiationCase.tenant_id)
                & (m.NegotiationResult.case_no == m.NegotiationCase.case_no),
            )
            .where(
                m.NegotiationResult.tenant_id == tenant_id,
                m.NegotiationCase.case_no != case_no,
                (m.NegotiationCase.spec_id == current.spec_id)
                | (m.NegotiationCase.supplier_id == current.supplier_id),
            )
            .order_by(m.NegotiationResult.result_date.desc())
        ).all()

        items: list[PastCase] = []
        for result, past in rows:
            supplier = session.execute(
                select(m.Supplier).where(
                    m.Supplier.tenant_id == tenant_id, m.Supplier.supplier_id == past.supplier_id
                )
            ).scalar_one_or_none()
            spec = session.execute(
                select(m.ProductSpec).where(
                    m.ProductSpec.tenant_id == tenant_id, m.ProductSpec.spec_id == past.spec_id
                )
            ).scalar_one_or_none()
            product = None
            if spec is not None:
                product = session.execute(
                    select(m.Product).where(
                        m.Product.tenant_id == tenant_id, m.Product.product_id == spec.product_id
                    )
                ).scalar_one_or_none()
            company = supplier.supplier_name if supplier else ""
            prod_name = product_display(product, spec)

            # 同一スペックは直接一致（relation なし）、それ以外（同一取引先の別商材）はグラフ補完。
            relation = None if past.spec_id == current.spec_id else "same_supplier"
            items.append(
                PastCase(
                    case_no=past.case_no,
                    company=company,
                    product=prod_name,
                    period=past.period or "",
                    settled_price=float(result.final_price) if result.final_price is not None else 0.0,
                    citations=[_build_citation(past, result, company, prod_name)],
                    relation=relation,
                )
            )

        state = "ready" if items else "empty"
        return PastCaseResult(state=state, items=items)
    except ApiProblem:
        raise
    except Exception:  # noqa: BLE001 - 過去経緯は部分エラーを許容（デザインガイド §3.2）
        return PastCaseResult(state="error", items=[])
