"""three_lines.py — 3ライン算出（FR-05・サーバー側実行）。

算出正本は ``app/db/seams.py`` の ``CALC_RULE_V1``。フロント ``lib/calc.ts`` と同一の式・
丸めで実装し、AI は数値を生成しない（RFP 2-3）。seed データ（鶏もも肉/丸紅畜産）で
RFP デモの3ライン（目標585 / 着地599 / 撤退615）を再現する。

  目標   = max(相場, 0.95 × 過去最安)
  着地   = clamp(0.5×過去平均 + 0.3×計画単価 + 0.2×相場, 目標, 撤退)
  撤退   = min(許容上限, 現行 × (1 + max(0, 相場前年同月比) + 2pt))  ※下落局面は0扱い
  欠損時は相場・現行でフォールバックする。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.db.seams import CALC_RULE_V1


def _round_half_up(x: float) -> int:
    """四捨五入（.5 は切り上げ）。JS の Math.round と一致させ、フロント calc.ts と丸めを統一する。

    Python 組み込み round() は銀行丸め（.5 を偶数へ）のため、算出値がフロントと食い違う
    （例: 598.5 → round=598 だが Math.round=599）。本関数で half-up に統一する。
    """
    return int(math.floor(x + 0.5))

# CALC_RULE_V1.params から係数を取り出す（正本と一致させる）。
_W = CALC_RULE_V1["params"]["landing_weights"]
LANDING_W_PAST_AVG = _W["past_avg"]  # 0.5
LANDING_W_PLAN = _W["plan_price"]  # 0.3
LANDING_W_MARKET = _W["market_rate"]  # 0.2
WALKAWAY_MARGIN_PT = CALC_RULE_V1["params"]["walkaway_margin_pt"]  # 0.02
TARGET_PAST_MIN_RATIO = CALC_RULE_V1["params"]["target_past_min_ratio"]  # 0.95


@dataclass
class RateInputs:
    market_rate: float  # 直近相場 ¥/kg
    current_price: float  # 現行仕入単価 ¥/kg
    yoy_rate: float  # 相場前年同月比（小数。例 0.032）


@dataclass
class PlanInputs:
    plan_price: float  # 計画仕入単価 ¥/kg
    ceiling_price: float  # 許容上限 ¥/kg
    monthly_volume: float  # 月次発注量 kg


def is_plan_ready(plan: PlanInputs) -> bool:
    """3ライン算出に足る計画入力が揃っているか（デザインガイド §3.3）。"""
    return plan.plan_price > 0 and plan.monthly_volume > 0 and plan.ceiling_price > 0


def _clamp(x: float, lo: float, hi: float) -> float:
    """x を [lo, hi] に収める。lo>hi の異常入力時は hi を返す（calc.ts と一致）。"""
    return min(max(x, lo), hi)


def calc_auto_lines(rate: RateInputs, plan: PlanInputs, past_prices: list[float]) -> dict[str, int]:
    """3本のライン（自動算出値）を CALC_RULE_V1 で計算する。

    past_prices は「直接一致（同一商材×取引先）」の決着単価のみを渡す想定。
    空なら相場を過去最安・過去平均の代替に用いる（欠損フォールバック）。
    """
    market = rate.market_rate
    current = rate.current_price if rate.current_price > 0 else market
    yoy = rate.yoy_rate

    past_min = min(past_prices) if past_prices else market
    past_avg = (sum(past_prices) / len(past_prices)) if past_prices else market

    # 目標 = max(相場, 0.95×過去最安)
    target = _round_half_up(max(market, TARGET_PAST_MIN_RATIO * past_min))
    # 撤退 = min(許容上限, 現行×(1 + max(0, 相場前年同月比) + 2pt))
    # 下落局面（前年同月比<0）は 0 扱い＝撤退は常に「現行+2pt」を保つ（CALC_RULE_V1 の確定解釈）。
    walkaway = _round_half_up(
        min(plan.ceiling_price, current * (1 + max(0.0, yoy) + WALKAWAY_MARGIN_PT))
    )
    # 着地 = clamp(0.5×過去平均 + 0.3×計画単価 + 0.2×相場, 目標, 撤退)
    landing_raw = (
        LANDING_W_PAST_AVG * past_avg
        + LANDING_W_PLAN * plan.plan_price
        + LANDING_W_MARKET * market
    )
    landing = _round_half_up(_clamp(landing_raw, target, walkaway))

    return {"target": target, "landing": landing, "walkaway": walkaway}


def calc_annual_impact(plan: PlanInputs, target: float, landing: float) -> dict[str, float]:
    """年間影響額（対計画）。影響額 = (計画仕入単価 − ライン単価) × 年間発注量(=月次×12)。"""
    annual_volume = plan.monthly_volume * 12
    return {
        "target_yen": (plan.plan_price - target) * annual_volume,
        "landing_yen": (plan.plan_price - landing) * annual_volume,
    }
