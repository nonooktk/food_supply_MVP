"""pricing.py — 相場・過去決着・自社計画の読み取り補助（Repository 経由）。

3ライン算出（services/three_lines.py）と相場/計画エンドポイントが共有する読み取りを集約する。
すべて ``TenantScopedRepository`` 経由で、テナント境界は Repository が強制する（§2.8 ルール1）。
"""

from __future__ import annotations

from typing import Optional

from app.db import models as m
from app.db.repository import TenantScopedRepository


def latest_market_rate(repo: TenantScopedRepository, spec_id: int) -> Optional[m.MarketRate]:
    """当該スペックの最新（year_month 最大）相場を返す。"""
    return repo.first(
        m.MarketRate, m.MarketRate.spec_id == spec_id, order_by=m.MarketRate.year_month.desc()
    )


def market_rate_count(repo: TenantScopedRepository, spec_id: int) -> int:
    """当該スペックの相場レコード数（正規化済み件数の目安）。"""
    return repo.count(m.MarketRate, m.MarketRate.spec_id == spec_id)


def past_settled_prices(repo: TenantScopedRepository, spec_id: int, exclude_case_no: str) -> list[float]:
    """同一スペックの過去決着単価（final_price）のリスト（当該案件を除く）。"""
    results = repo.past_results_for_spec(spec_id, exclude_case_no)
    return [float(r.final_price) for r in results if r.final_price is not None]


def plan_for_spec(
    repo: TenantScopedRepository, spec_id: int, period: Optional[str] = None
) -> Optional[m.CompanyPlan]:
    """スペックの自社計画を返す。period 一致を優先し、無ければ最初の1件。"""
    plans = repo.list(m.CompanyPlan, m.CompanyPlan.spec_id == spec_id)
    if not plans:
        return None
    if period:
        for p in plans:
            if p.period == period:
                return p
    return plans[0]
