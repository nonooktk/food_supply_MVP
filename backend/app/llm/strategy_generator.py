"""strategy_generator.py — 交渉ポイント/シナリオの AI 生成（FR-08）。

PoC llm/analyzer.py の骨格（並列 GPT・JSON モード・プロンプトインジェクション対策
``{}`` → ``{{}}`` エスケープ）を流用し、購買交渉ドメインへ置換する。KRE 供給の過去経緯・
グラフ補完と、本体算出の3ライン・自社計画・相場を根拠に、交渉ポイント3件と交渉シナリオを生成する。

AI は価格を決めない（RFP 2-3）。数値は本体が算出・記録した3ライン・過去決着単価のみを引用する。
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

from openai import AzureOpenAI

from app.config import get_settings
from app.llm.prompts import (
    POINTS_SYSTEM_PROMPT,
    POINTS_USER_PROMPT_TEMPLATE,
    SCENARIO_SYSTEM_PROMPT,
    SCENARIO_USER_PROMPT_TEMPLATE,
)

logger = logging.getLogger(__name__)


@dataclass
class PastCaseFact:
    case_no: str
    company: str
    product: str
    period: str
    settled_price: float
    snippet: str = ""
    relation: Optional[str] = None  # None=直接一致 / "same_supplier"=グラフ補完


@dataclass
class StrategyContext:
    """AI 生成の入力事実（KRE 供給＋本体算出）。"""

    company: str
    product: str
    quoted_price: float
    current_price: float
    market_rate: float
    yoy_rate: Optional[float]  # 小数（0.032 = +3.2%）。未算出時 None
    target: float
    landing: float
    walkaway: float
    plan_price: float
    monthly_volume: float
    annual_volume: float
    ceiling_price: float
    past_cases: list[PastCaseFact] = field(default_factory=list)
    graph_summary: str = ""


@lru_cache(maxsize=1)
def _get_client() -> AzureOpenAI:
    """AzureOpenAI クライアントをシングルトンで返す（テストは本関数を差し替える）。"""
    s = get_settings()
    return AzureOpenAI(
        azure_endpoint=s.azure_openai_endpoint,
        api_key=s.azure_openai_api_key,
        api_version=s.azure_openai_api_version,
    )


def _escape_braces(text: str) -> str:
    """プロンプトインジェクション・format 事故対策。中括弧を無効化する（PoC 流用）。"""
    return text.replace("{", "{{").replace("}", "}}")


def build_context_text(ctx: StrategyContext) -> str:
    """StrategyContext を人間可読な事実ブロックに整形する（プロンプトの {context} に入る）。"""
    lines = [
        f"取引先: {ctx.company}",
        f"商材: {ctx.product}",
        f"提示見積: ¥{ctx.quoted_price:.0f}/kg / 現行単価: ¥{ctx.current_price:.0f}/kg",
        (
            f"直近相場: ¥{ctx.market_rate:.0f}/kg（前年同月比 {ctx.yoy_rate * 100:+.1f}%）"
            if ctx.yoy_rate is not None
            else f"直近相場: ¥{ctx.market_rate:.0f}/kg（前年同月比 未算出）"
        ),
        "3ライン（本体が算出。AIはこれ以外の価格を作らないこと）:",
        f"  目標 ¥{ctx.target:.0f}/kg ／ 着地 ¥{ctx.landing:.0f}/kg ／ 撤退 ¥{ctx.walkaway:.0f}/kg",
        f"自社計画: 計画単価 ¥{ctx.plan_price:.0f}/kg ／ 月次 {ctx.monthly_volume:.0f}kg ／ "
        f"年間 {ctx.annual_volume:.0f}kg ／ 許容上限 ¥{ctx.ceiling_price:.0f}/kg",
    ]
    if ctx.past_cases:
        lines.append("過去の決着実績（引用可能な根拠）:")
        for p in ctx.past_cases:
            tag = "同一取引先の別商材" if p.relation == "same_supplier" else "同一商材"
            lines.append(
                f"  [{p.case_no}] {p.company}／{p.product}（{p.period}・{tag}）"
                f" 決着 ¥{p.settled_price:.0f}/kg。{p.snippet}"
            )
    else:
        lines.append("過去の決着実績: なし（初回取引）")
    if ctx.graph_summary:
        lines.append(f"関連文脈（グラフ補完）: {ctx.graph_summary}")
    return "\n".join(lines)


def _call_json(system_prompt: str, user_prompt: str, label: str) -> dict:
    """1 回の GPT 呼び出し（JSON モード）。結果を dict で返す。"""
    client = _get_client()
    model = get_settings().azure_openai_chat_deployment
    t0 = time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    logger.info("[TIMER] strategy/%s: %.2fs", label, time.perf_counter() - t0)
    return json.loads(response.choices[0].message.content)


def generate_strategy(ctx: StrategyContext) -> dict:
    """交渉ポイント（3件）と交渉シナリオを並列生成して返す。

    返り値: ``{"points": [{"text": str, "citation_case_nos": [str]}], "scenario": str}``
    """
    context_text = _escape_braces(build_context_text(ctx))
    points_user = POINTS_USER_PROMPT_TEMPLATE.format(context=context_text)
    scenario_user = SCENARIO_USER_PROMPT_TEMPLATE.format(context=context_text)

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_points = ex.submit(_call_json, POINTS_SYSTEM_PROMPT, points_user, "points")
        f_scenario = ex.submit(_call_json, SCENARIO_SYSTEM_PROMPT, scenario_user, "scenario")
        points_json = f_points.result()
        scenario_json = f_scenario.result()
    logger.info("[TIMER] strategy/total(2並列): %.2fs", time.perf_counter() - t0)

    points = points_json.get("points", [])
    # ちょうど3件に整える（過不足はプロンプト逸脱時の保険）。
    points = [p for p in points if isinstance(p, dict) and p.get("text")][:3]
    scenario = str(scenario_json.get("scenario", "")).strip()
    return {"points": points, "scenario": scenario}
