"""test_services_three_lines.py — 3ライン算出（CALC_RULE_V1）の純粋関数テスト。"""

from __future__ import annotations

from app.services.three_lines import (
    PlanInputs,
    RateInputs,
    calc_annual_impact,
    calc_auto_lines,
    is_plan_ready,
)


def test_rfp_demo_numbers() -> None:
    """RFP デモ（鶏もも肉/丸紅畜産）で 目標585 / 着地599 / 撤退615 を再現する。"""
    rate = RateInputs(market_rate=585, current_price=609, yoy_rate=0.064)
    plan = PlanInputs(plan_price=595, ceiling_price=615, monthly_volume=18000)
    past = [609.0, 605.0, 612.0, 598.0]  # 過去4案件の決着単価
    auto = calc_auto_lines(rate, plan, past)
    assert auto == {"target": 585, "landing": 599, "walkaway": 615}


def test_annual_impact_vs_plan() -> None:
    """年間影響額 = (計画単価 − ライン) × 月次×12。"""
    plan = PlanInputs(plan_price=595, ceiling_price=615, monthly_volume=18000)
    impact = calc_annual_impact(plan, target=585, landing=600)
    assert impact["target_yen"] == (595 - 585) * 216000  # +2,160,000
    assert impact["landing_yen"] == (595 - 600) * 216000  # -1,080,000


def test_fallback_without_past() -> None:
    """過去価格が無いときは相場を過去最安・過去平均の代替に用いる。"""
    rate = RateInputs(market_rate=600, current_price=600, yoy_rate=0.0)
    plan = PlanInputs(plan_price=600, ceiling_price=650, monthly_volume=1000)
    auto = calc_auto_lines(rate, plan, [])
    # 目標 = max(600, 0.95×600=570) = 600
    assert auto["target"] == 600
    # 撤退 = min(650, 600×1.02=612) = 612
    assert auto["walkaway"] == 612


def test_landing_is_clamped() -> None:
    """着地は [目標, 撤退] に収まる。"""
    rate = RateInputs(market_rate=585, current_price=609, yoy_rate=0.064)
    plan = PlanInputs(plan_price=595, ceiling_price=615, monthly_volume=18000)
    auto = calc_auto_lines(rate, plan, [609, 605, 612, 598])
    assert auto["target"] <= auto["landing"] <= auto["walkaway"]


def test_is_plan_ready() -> None:
    assert is_plan_ready(PlanInputs(plan_price=595, ceiling_price=615, monthly_volume=18000))
    assert not is_plan_ready(PlanInputs(plan_price=0, ceiling_price=615, monthly_volume=18000))
    assert not is_plan_ready(PlanInputs(plan_price=595, ceiling_price=0, monthly_volume=18000))
    assert not is_plan_ready(PlanInputs(plan_price=595, ceiling_price=615, monthly_volume=0))
