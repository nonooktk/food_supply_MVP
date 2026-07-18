"""seams.py — 未確定点を吸収する調整シーム（設計 v3 §8.6）。

発注者確認待ちの仕様を「設定 / インターフェース差し替え」で吸収する抽象化点をまとめる。
本体コードの改修なしに切り替えられる粒度で定義する。

含むもの:
- CaseType: 案件種別の拡張 enum（既定: 仕入のみ。将来 販売系を追加可能）
- GradeMode: グレード運用フラグ（free_text ⇄ mastered）
- CALC_RULE_V1: 3ライン算出式 v1.0 の定義（model_versions.definition へ投入）
"""

from __future__ import annotations

from enum import Enum


class CaseType(str, Enum):
    """案件種別（調整シーム #1）。

    既定は仕入交渉のみ（見積 / 値上げ要請 / 契約更新）。将来 [確認1] で販売側が対象に
    入った場合は、ここに販売系メンバーを追加するだけで拡張できる（列は TEXT のまま）。
    """

    # ----- 仕入交渉（MVP 既定） -----
    QUOTE = "見積"
    PRICE_INCREASE_REQUEST = "値上げ要請"
    CONTRACT_RENEWAL = "契約更新"
    # ----- 販売側（将来拡張の受け口。既定では未使用） -----
    # PRICE_INCREASE_NOTICE = "値上げ通知"  # [確認1] 回答後に有効化


# 既定（仕入のみ）で許可する案件種別の集合。バリデーションはこの集合で行う。
PURCHASE_CASE_TYPES: frozenset[str] = frozenset(
    {CaseType.QUOTE.value, CaseType.PRICE_INCREASE_REQUEST.value, CaseType.CONTRACT_RENEWAL.value}
)


def is_allowed_case_type(value: str, *, include_sales: bool = False) -> bool:
    """案件種別が許可集合に含まれるか判定する（既定: 仕入のみ）。

    include_sales=True で販売系を含む拡張集合に切り替える（[確認1] 回答後の受け口）。
    """
    allowed = set(PURCHASE_CASE_TYPES)
    if include_sales:
        allowed |= {m.value for m in CaseType}
    return value in allowed


class GradeMode(str, Enum):
    """グレード運用フラグ（調整シーム #4）。

    既定は自由記述（free_text）。グレードマスタ化が決まれば mastered に切り替える。
    """

    FREE_TEXT = "free_text"
    MASTERED = "mastered"


# MVP 既定のグレード運用。
DEFAULT_GRADE_MODE: GradeMode = GradeMode.FREE_TEXT


def validate_grade(value: str | None, *, mode: GradeMode = DEFAULT_GRADE_MODE) -> str | None:
    """グレード値を運用モードに応じて検証する。

    free_text: 何でも許容（空欄可）。mastered: グレードマスタ照合（MVP では未実装のため素通し）。
    """
    if value is None:
        return None
    value = value.strip()
    if mode is GradeMode.FREE_TEXT:
        return value or None
    # mastered モードのマスタ照合はマスタ確定後に実装する（[確認4]）。
    return value or None


# ------------------------------------------------------------------------------
# 3ライン算出式 v1.0（調整シーム #2 / FR-05）
#   目標   = max(相場, 0.95 × 過去最安)
#   着地   = clamp(0.5 × 過去平均 + 0.3 × 計画単価 + 0.2 × 相場, 目標, 撤退)
#   撤退   = min(許容上限, 現行 × (1 + 相場前年同月比 + 2pt))
#   欠損時フォールバック・根拠表示あり。AI は数値を生成しない（RFP 2-3）。
#   出典: RPF「3ライン算出モデル_v1_20260706」/ テーブル定義 表紙シート
# ------------------------------------------------------------------------------
CALC_RULE_V1_LABEL = "ルールv1.0"

CALC_RULE_V1: dict = {
    "lines": {
        "target": {
            "formula": "max(market_rate, 0.95 * past_min)",
            "desc": "目標 = max(相場, 0.95×過去最安)",
        },
        "landing": {
            "formula": "clamp(0.5*past_avg + 0.3*plan_price + 0.2*market_rate, target, walkaway)",
            "desc": "着地 = clamp(0.5×過去平均 + 0.3×計画単価 + 0.2×相場, 目標, 撤退)",
        },
        "walkaway": {
            "formula": "min(max_acceptable_price, current_price * (1 + max(0, yoy_rate) + 0.02))",
            "desc": "撤退 = min(許容上限, 現行×(1 + max(0, 相場前年同月比) + 2pt))。"
            "下落局面（前年同月比<0）は0扱いとし、撤退は常に現行+2ptを保つ"
            "（GraphRAG評価用期待解v1の答え合わせ・2026-07-11で確定した解釈）。",
        },
    },
    "params": {"landing_weights": {"past_avg": 0.5, "plan_price": 0.3, "market_rate": 0.2},
               "walkaway_margin_pt": 0.02, "target_past_min_ratio": 0.95},
    "fallback": "欠損時はフォールバックし根拠を表示する。",
    "policy": "AI は数値を生成しない（RFP 2-3）。3ラインは本式で機械的に算出する。",
    "source": "RPF 3ライン算出モデル_v1_20260706 / テーブル定義 表紙",
}

# 過去に使われた暫定式（strategy_sheets が参照するため版として保持。非活性）。
CALC_RULE_V09_LABEL = "ルールv0.9(暫定式)"
CALC_RULE_V09: dict = {
    "note": "v1.0 以前の暫定式。過去の作戦シートが calc_version として参照する履歴版。",
    "superseded_by": CALC_RULE_V1_LABEL,
}
