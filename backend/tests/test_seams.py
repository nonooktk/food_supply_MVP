"""test_seams.py — 調整シーム（case_type / grade / 算出式v1）のテスト。"""

from __future__ import annotations

from app.db.seams import (
    CALC_RULE_V1,
    CALC_RULE_V1_LABEL,
    GradeMode,
    is_allowed_case_type,
    validate_grade,
)


def test_case_type_default_is_purchase_only() -> None:
    """既定（仕入のみ）で許可される案件種別。"""
    assert is_allowed_case_type("見積")
    assert is_allowed_case_type("値上げ要請")
    assert is_allowed_case_type("契約更新")
    # 販売系は既定では不許可
    assert not is_allowed_case_type("値上げ通知")


def test_case_type_include_sales_seam() -> None:
    """include_sales=True（[確認1] 回答後の受け口）で拡張集合に切り替わる。"""
    # 既定 enum に販売系メンバーは未登録のため、現時点では拡張しても仕入のみ。
    # シームが引数で切り替わること自体を検証する（回帰防止）。
    assert is_allowed_case_type("見積", include_sales=True)


def test_grade_default_free_text() -> None:
    """グレードは既定で自由記述（空欄は None）。"""
    assert validate_grade("30/40") == "30/40"
    assert validate_grade("") is None
    assert validate_grade(None) is None


def test_grade_mastered_mode_passes_through() -> None:
    """mastered モードでも MVP では素通し（マスタ確定後に実装）。"""
    assert validate_grade("A5", mode=GradeMode.MASTERED) == "A5"


def test_calc_rule_v1_structure() -> None:
    """算出式 v1.0 に3ラインの式が揃っていること。"""
    assert CALC_RULE_V1_LABEL == "ルールv1.0"
    lines = CALC_RULE_V1["lines"]
    assert set(lines.keys()) == {"target", "landing", "walkaway"}
    assert "max(market_rate" in lines["target"]["formula"]
    assert "clamp(" in lines["landing"]["formula"]
    assert "min(max_acceptable_price" in lines["walkaway"]["formula"]
    # AI は数値を生成しない方針が明記されている（RFP 2-3）
    assert "AI" in CALC_RULE_V1["policy"]
