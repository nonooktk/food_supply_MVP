"""test_strategy_generator.py — AI 生成器のユニット＋実呼び出し統合（既定スキップ）。"""

from __future__ import annotations

import json
import os

import pytest

from app.llm.strategy_generator import (
    PastCaseFact,
    StrategyContext,
    build_context_text,
    generate_strategy,
)


def _ctx() -> StrategyContext:
    return StrategyContext(
        company="丸紅畜産",
        product="鶏もも肉（ブラジル産・冷凍）",
        quoted_price=620,
        current_price=609,
        market_rate=585,
        yoy_rate=0.064,
        target=585,
        landing=600,
        walkaway=615,
        plan_price=595,
        monthly_volume=18000,
        annual_volume=216000,
        ceiling_price=615,
        past_cases=[
            PastCaseFact("No.123455-a", "丸紅畜産", "鶏もも肉（ブラジル産・冷凍）", "2026Q2", 609, "為替影響を反映", None),
        ],
        graph_summary="丸紅畜産の鶏もも肉は飼料高騰(RC-04)で反復値上げ。",
    )


def test_build_context_text_contains_facts() -> None:
    text = build_context_text(_ctx())
    assert "丸紅畜産" in text
    assert "目標 ¥585" in text and "着地 ¥600" in text and "撤退 ¥615" in text
    assert "No.123455-a" in text
    assert "+6.4%" in text  # 前年比の整形


def test_generate_escapes_braces(monkeypatch: pytest.MonkeyPatch) -> None:
    """コンテキストに中括弧が混じっても format が壊れない（インジェクション対策）。"""

    captured = {}

    class _C:
        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                def create(**kwargs):
                    captured["user"] = kwargs["messages"][1]["content"]

                    class _R:
                        choices = [type("c", (), {"message": type("m", (), {"content": json.dumps({"points": [], "scenario": "s"})})})]

                    return _R()

    monkeypatch.setattr("app.llm.strategy_generator._get_client", lambda: _C())
    ctx = _ctx()
    ctx.graph_summary = "危険な {injection} を含む {{テキスト}}"
    out = generate_strategy(ctx)  # 例外なく完了すること
    assert "scenario" in out
    # エスケープされ、生の {injection} はそのまま波括弧2重化されている
    assert "{{injection}}" in captured["user"]


@pytest.mark.skipif(not os.getenv("RUN_REAL_AI"), reason="実 Azure OpenAI 課金回避（RUN_REAL_AI=1 で実行）")
def test_generate_real_once() -> None:
    """実 Azure OpenAI を1回だけ呼び、ポイント3件＋シナリオが返ることを検証する。"""
    out = generate_strategy(_ctx())
    assert len(out["points"]) == 3
    assert out["scenario"]
    # AI が新たな価格を作らない前提（3ライン・過去決着以外の桁の値を強く要求はしないが、
    # 少なくとも生成が JSON 契約を満たすことを担保する）。
    for p in out["points"]:
        assert p.get("text")
