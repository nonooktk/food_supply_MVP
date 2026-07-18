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


def test_prompts_forbid_fabricated_numbers() -> None:
    """数値ガード（統合テスト Minor）: 価格に加え数量・割合等も事実にないものは書かない旨が
    ポイント/シナリオ両プロンプトに明記されていること。"""
    from app.llm.prompts import POINTS_SYSTEM_PROMPT, SCENARIO_SYSTEM_PROMPT

    for prompt in (POINTS_SYSTEM_PROMPT, SCENARIO_SYSTEM_PROMPT):
        assert "決めない" in prompt  # 価格ガード（既存）
        assert "数量" in prompt and "割合" in prompt  # 数値全般のガード（追加）
        assert "事実にない数値" in prompt


def test_generated_output_only_uses_context_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    """生成検証（モック）: 生成物に含まれる数値がコンテキストの数値集合に収まることを固定する。"""
    import re

    ctx = _ctx()
    allowed = {"585", "600", "615", "609", "216000", "595"}

    def _fake(system_prompt, user_prompt, label):  # noqa: ANN001
        if label == "scenario":
            return {"scenario": "目標¥585から着地¥600へ寄せ、撤退¥615超は持ち帰る。"}
        return {
            "points": [
                {"text": "目標¥585を起点に交渉（過去決着¥609を根拠）。", "citation_case_nos": ["No.123455-a"]},
                {"text": "年間216000kgの数量を背景に着地¥600を狙う。", "citation_case_nos": []},
                {"text": "撤退¥615を超えたら持ち帰る。", "citation_case_nos": []},
            ]
        }

    monkeypatch.setattr("app.llm.strategy_generator._call_json", _fake)
    out = generate_strategy(ctx)
    texts = [p["text"] for p in out["points"]] + [out["scenario"]]
    for t in texts:
        for num in re.findall(r"\d[\d,\.]*", t):
            assert num.replace(",", "") in allowed, f"事実にない数値: {num!r}（text={t!r}）"


def test_build_context_text_contains_facts() -> None:
    text = build_context_text(_ctx())
    assert "丸紅畜産" in text
    assert "目標 ¥585" in text and "着地 ¥600" in text and "撤退 ¥615" in text
    assert "No.123455-a" in text
    assert "+6.4%" in text  # 前年同月比の整形


def test_build_context_text_yoy_none_shows_uncalculated() -> None:
    """yoy_rate=None（未算出）のとき、前年同月比は 0% ではなく『未算出』と表記されること。"""
    ctx = _ctx()
    ctx.yoy_rate = None
    text = build_context_text(ctx)
    assert "前年同月比 未算出" in text
    assert "+0.0%" not in text  # 未算出を 0% と誤表示しないこと


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
