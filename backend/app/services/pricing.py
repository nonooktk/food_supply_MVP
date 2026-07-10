"""pricing.py — 相場・過去決着・自社計画のクエリ補助（読み取り）。

3ライン算出（services/three_lines.py）と相場/計画エンドポイントが共有する DB 取得を集約する。
すべてテナント境界内で完結する。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m


def latest_market_rate(session: Session, tenant_id: str, spec_id: int) -> Optional[m.MarketRate]:
    """当該スペックの最新（year_month 最大）相場を返す。"""
    return session.execute(
        select(m.MarketRate)
        .where(m.MarketRate.tenant_id == tenant_id, m.MarketRate.spec_id == spec_id)
        .order_by(m.MarketRate.year_month.desc())
        .limit(1)
    ).scalar_one_or_none()


def market_rate_count(session: Session, tenant_id: str, spec_id: int) -> int:
    """当該スペックの相場レコード数（正規化済み件数の目安）。"""
    rows = session.execute(
        select(m.MarketRate.rate_id).where(
            m.MarketRate.tenant_id == tenant_id, m.MarketRate.spec_id == spec_id
        )
    ).all()
    return len(rows)


def past_settled_prices(
    session: Session, tenant_id: str, spec_id: int, exclude_case_no: str
) -> list[float]:
    """同一スペックの過去決着単価（final_price）のリスト（当該案件を除く）。

    3ライン算出の「過去最安・過去平均」に用いる直接一致データ。
    """
    rows = session.execute(
        select(m.NegotiationResult.final_price)
        .join(
            m.NegotiationCase,
            (m.NegotiationResult.tenant_id == m.NegotiationCase.tenant_id)
            & (m.NegotiationResult.case_no == m.NegotiationCase.case_no),
        )
        .where(
            m.NegotiationResult.tenant_id == tenant_id,
            m.NegotiationCase.spec_id == spec_id,
            m.NegotiationResult.case_no != exclude_case_no,
            m.NegotiationResult.final_price.is_not(None),
        )
    ).all()
    return [float(r[0]) for r in rows]


def plan_for_spec(
    session: Session, tenant_id: str, spec_id: int, period: Optional[str] = None
) -> Optional[m.CompanyPlan]:
    """スペックの自社計画を返す。period 一致を優先し、無ければ最初の1件。"""
    plans = session.execute(
        select(m.CompanyPlan).where(
            m.CompanyPlan.tenant_id == tenant_id, m.CompanyPlan.spec_id == spec_id
        )
    ).scalars().all()
    if not plans:
        return None
    if period:
        for p in plans:
            if p.period == period:
                return p
    return plans[0]
