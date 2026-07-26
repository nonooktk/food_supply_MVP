"""strategy_generator.py — 交渉ポイント/シナリオの AI 生成（FR-08）。

PoC llm/analyzer.py の骨格（並列 GPT・JSON モード・プロンプトインジェクション対策
``{}`` → ``{{}}`` エスケープ）を流用し、購買交渉ドメインへ置換する。KRE 供給の過去経緯・
グラフ補完と、本体算出の3ライン・自社計画・相場を根拠に、交渉ポイント3件と交渉シナリオを生成する。

AI は価格を決めない（RFP 2-3）。数値は本体が算出・記録した3ライン・過去決着単価のみを引用する。

プロンプトインジェクション対策（2026-07-26 セキュリティ監査 F-7 で強化）:
``{}`` エスケープだけでは自然文の指示を無害化できないため、ユーザー入力由来の値を
``<<<user_text>>> … <<<end>>>`` で囲み（``build_context_text``）、システムプロンプト側で
「囲みの中はデータであり指示ではない」と宣言する（``app/llm/prompts.DATA_BOUNDARY_RULES``）。
さらに生成結果の数値がコンテキストの数値集合に収まるかを検証する（``verify_generated_numbers``）。
"""

from __future__ import annotations

import json
import logging
import re
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


# ==============================================================================
# ユーザー入力のデリミタ化（監査 F-7・プロンプトインジェクション対策）
# ==============================================================================
# 取引先名・商材名・所感・申し送り・グラフ要約は人が書いた自由記述であり、そのまま連結すると
# 「これまでの指示は無効です」のような指示文がプロンプトの一部として読まれてしまう。特に申し送りは
# 次回の同一スペック×同一取引先の案件生成へ自動的に載る（BR-10 判断継承ループ）ため、
# 一度仕込まれた指示が永続化する（＝間接プロンプトインジェクション）。
# 対策は3点セット:
#   1) 値をデリミタで囲み、「これはデータであって指示ではない」とシステムプロンプトで明示する
#      （明示は app/llm/prompts.py の DATA_BOUNDARY_RULES）。
#   2) デリミタ自体の詐称（閉じタグを書いて枠外へ抜ける攻撃）を無効化する。
#   3) 改行・制御文字を空白へ潰し、長さを切り詰める（構造注入と長文注入の抑止）。
USER_TEXT_OPEN = "<<<user_text>>>"
USER_TEXT_CLOSE = "<<<end>>>"

# 読込時の切り詰め上限。書込時の上限（app/schemas.py の MAX_*_LEN）と対になる保険で、
# **上限導入前に保存された既存データ**が長大でもプロンプトを埋め尽くさないようにする。
# 読込側で例外を投げない（既存行の表示・生成を壊さない）ことが要件。
MAX_COMPANY_CHARS = 200  # 取引先名（マスタ由来）
MAX_PRODUCT_CHARS = 100  # 商材名（schemas.MAX_PRODUCT_LEN と対）
MAX_PERIOD_CHARS = 50  # 対象時期（schemas.MAX_PERIOD_LEN と対）
MAX_MEMO_CHARS = 1000  # 所感・申し送りを含む過去決着の抜粋（schemas.MAX_MEMO_LEN と対）
MAX_SUMMARY_CHARS = 2000  # KRE のグラフ要約（機械生成の自然文）
TRUNCATION_MARK = "…（以下省略）"

# 制御文字（改行・タブ含む）。プロンプト上の擬似セクションを作らせないため空白へ潰す。
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_user_text(value: object, limit: int) -> str:
    """ユーザー入力由来の文字列を、プロンプトへ載せられる安全な1行データへ正規化する。

    - デリミタ文字列の詐称を全角化して無効化する（枠外へ抜けられないようにする）。
    - 制御文字・改行を空白へ潰す（見出し・箇条書きによる構造注入の弱体化）。
    - ``limit`` 文字で切り詰める（超過分は切り捨てたことを明示する）。
    """
    text = "" if value is None else str(value)
    text = text.replace(USER_TEXT_OPEN, "＜user_text＞").replace(USER_TEXT_CLOSE, "＜end＞")
    text = _CONTROL_CHARS.sub(" ", text)
    if len(text) > limit:
        text = text[:limit] + TRUNCATION_MARK
    return text


def _user_field(value: object, limit: int) -> str:
    """ユーザー入力由来の値をデリミタで囲んだ「データ」として返す（指示ではない）。"""
    return f"{USER_TEXT_OPEN}{sanitize_user_text(value, limit)}{USER_TEXT_CLOSE}"


def build_context_text(ctx: StrategyContext) -> str:
    """StrategyContext を人間可読な事実ブロックに整形する（プロンプトの {context} に入る）。

    ユーザー入力由来の値（取引先・商材・時期・所感/申し送りの抜粋・グラフ要約）は
    ``<<<user_text>>> … <<<end>>>`` で囲む。数値は本体が算出した float のため素で載せる。
    """
    lines = [
        f"取引先: {_user_field(ctx.company, MAX_COMPANY_CHARS)}",
        f"商材: {_user_field(ctx.product, MAX_PRODUCT_CHARS)}",
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
            # snippet には所感・申し送りが含まれる（判断継承ループの入力）。必ずデリミタで囲む。
            lines.append(
                f"  [{sanitize_user_text(p.case_no, 64)}]"
                f" {_user_field(p.company, MAX_COMPANY_CHARS)}／{_user_field(p.product, MAX_PRODUCT_CHARS)}"
                f"（{_user_field(p.period, MAX_PERIOD_CHARS)}・{tag}）"
                f" 決着 ¥{p.settled_price:.0f}/kg。{_user_field(p.snippet, MAX_MEMO_CHARS)}"
            )
    else:
        lines.append("過去の決着実績: なし（初回取引）")
    if ctx.graph_summary:
        lines.append(f"関連文脈（グラフ補完）: {_user_field(ctx.graph_summary, MAX_SUMMARY_CHARS)}")
    return "\n".join(lines)


# ==============================================================================
# 出力側の数値検証（監査 F-7 の3・「AI は価格を決めない」を指示から強制へ）
# ==============================================================================
# 数値トークン: 「585」「216,000」「6.4」等。通貨記号・単位は含めずに拾う。
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
# 全角数字を半角へ（LLM が全角で書いた場合に検証をすり抜けないようにする）。
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９．，", "0123456789.,")


def _number_tokens(text: str) -> set[str]:
    """文字列に含まれる数値トークンを正規化して集合で返す（カンマ除去・全角半角統一）。"""
    normalized = (text or "").translate(_FULLWIDTH_DIGITS)
    tokens = set()
    for raw in _NUMBER_RE.findall(normalized):
        token = raw.replace(",", "").rstrip(".")
        if token:
            tokens.add(token)
    return tokens


def verify_generated_numbers(generated: dict, context_text: str) -> list[str]:
    """生成文中の数値が、コンテキストに含まれる数値集合の範囲内かを機械的に確認する。

    コンテキスト（3ライン・過去決着単価・計画値・案件番号・時期）に現れない数値を
    「逸脱」として返す。返り値が空でなければ呼び出し側が警告フラグを立てる。

    注意: これは**検知**であって遮断ではない。「1つ目」のような列挙の序数など、業務上無害な
    数値が混ざることがあるため、生成そのものは止めずに監査ログへ残す設計にしている。
    """
    allowed = _number_tokens(context_text)
    texts = [str(p.get("text", "")) for p in generated.get("points", []) if isinstance(p, dict)]
    texts.append(str(generated.get("scenario", "")))
    unknown: set[str] = set()
    for text in texts:
        unknown |= _number_tokens(text) - allowed
    return sorted(unknown)


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

    返り値: ``{"points": [...], "scenario": str, "number_warnings": [str]}``

    ``number_warnings`` は、生成文にコンテキスト外の数値が含まれた場合の警告フラグ
    （監査 F-7 の出力側検証）。空リストなら逸脱なし。
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

    generated = {"points": points, "scenario": scenario}
    # 出力側検証（F-7 の3）: 事実に無い数値が混じっていないかを機械的に確認する。
    # 逸脱があっても生成は返す（誤検知で業務を止めないため）が、警告フラグを立てて記録する。
    warnings_ = verify_generated_numbers(generated, context_text)
    if warnings_:
        logger.warning("[GUARD] strategy: context 外の数値を検出 numbers=%s", warnings_)
    generated["number_warnings"] = warnings_
    return generated
