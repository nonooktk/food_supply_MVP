"""test_normalize.py — N-06 正規化ルールのユニットテスト。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.ingest.normalize import (
    NormalizeError,
    normalize_percent,
    normalize_year_month,
    to_halfwidth,
    zero_pad_code,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Jul-25", "2025-07"), ("Jan-26", "2026-01"), ("Dec-25", "2025-12"),
     ("2025-07", "2025-07"), ("2025/7", "2025-07")],
)
def test_normalize_year_month(raw: str, expected: str) -> None:
    assert normalize_year_month(raw) == expected


def test_normalize_year_month_invalid() -> None:
    with pytest.raises(NormalizeError):
        normalize_year_month("2025-13")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("+3.2%", Decimal("3.2")), ("3.20%", Decimal("3.20")), ("3.2", Decimal("3.2")),
     ("60%", Decimal("60")), ("", None), (None, None)],
)
def test_normalize_percent(raw, expected) -> None:
    assert normalize_percent(raw) == expected


def test_to_halfwidth() -> None:
    # 全角数字・記号 → 半角
    assert to_halfwidth("１２３．５％") == "123.5%"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("113501", "113501"), (113501, "113501"), ("1235", "001235"), ("113501.0", "113501")],
)
def test_zero_pad_code(raw, expected: str) -> None:
    assert zero_pad_code(raw) == expected


def test_zero_pad_code_non_numeric() -> None:
    with pytest.raises(NormalizeError):
        zero_pad_code("ABC")
