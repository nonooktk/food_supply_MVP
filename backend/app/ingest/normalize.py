"""normalize.py — 取込データの正規化ルール（要件 N-06）。

外部データ（農水省CSV等）はフォーマットが不統一のため、生データ着地層 (`raw_imports`) に
無加工で着地させたうえで、本モジュールのルールで正規化してから正規化層へ upsert する。

正規化ルール（N-06）:
- 年月: `Jul-25` → `2025-07`（英語月名略記＋2桁年）
- 前年同月比: `+3.2%` / `3.20%` / `3.2` → `Decimal('3.2')`（%記号・符号除去、数値化）
- 全角 → 半角（数字・英字・記号）
- コード: ゼロ埋め（`infomart_code` は 6 桁の文字列）
"""

from __future__ import annotations

import unicodedata
from decimal import Decimal, InvalidOperation

# 英語月名略記 → 月番号。
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


class NormalizeError(ValueError):
    """正規化に失敗したことを表す例外（raw_imports.normalize_error に記録する）。"""


def to_halfwidth(value: str) -> str:
    """全角の英数字・記号を半角へ正規化する（NFKC）。"""
    return unicodedata.normalize("NFKC", value)


def normalize_year_month(value: str) -> str:
    """年月表記を `YYYY-MM` に正規化する。

    受理する形式の例: `Jul-25` / `2025-07` / `2025/7` / `2025-7`。
    """
    if value is None:
        raise NormalizeError("年月が空です。")
    s = to_halfwidth(str(value)).strip()

    # 既に YYYY-MM / YYYY/M 形式
    for sep in ("-", "/"):
        if sep in s:
            left, _, right = s.partition(sep)
            left, right = left.strip(), right.strip()
            # 'Jul-25' 形式（左が月名）
            if left[:3].lower() in _MONTHS and right.isdigit():
                month = _MONTHS[left[:3].lower()]
                year = _to_full_year(right)
                return f"{year:04d}-{month:02d}"
            # 'YYYY-MM' 形式（左が年）
            if left.isdigit() and right.isdigit():
                year = _to_full_year(left)
                month = int(right)
                if not 1 <= month <= 12:
                    raise NormalizeError(f"月が範囲外です: {value!r}")
                return f"{year:04d}-{month:02d}"
    raise NormalizeError(f"年月の形式を解釈できません: {value!r}")


def _to_full_year(token: str) -> int:
    """2桁年を 2000 年代に、4桁年はそのまま整数化する。"""
    n = int(token)
    return 2000 + n if n < 100 else n


def normalize_percent(value: str | float | int | None) -> Decimal | None:
    """`+3.2%` / `3.20%` / `3.2` 等を Decimal に正規化する（%・符号・全角を除去）。"""
    if value is None or value == "":
        return None
    s = to_halfwidth(str(value)).strip().replace("%", "").replace("+", "").replace(",", "")
    try:
        return Decimal(s)
    except InvalidOperation as exc:
        raise NormalizeError(f"数値に変換できません: {value!r}") from exc


def zero_pad_code(value: str | int | None, width: int = 6) -> str | None:
    """コードを指定桁数でゼロ埋めした文字列にする（infomart_code は 6 桁）。"""
    if value is None or value == "":
        return None
    s = to_halfwidth(str(value)).strip()
    # 小数点付き（Excel 由来の '113501.0' 等）を吸収する。
    if s.endswith(".0"):
        s = s[:-2]
    if not s.isdigit():
        raise NormalizeError(f"コードが数字ではありません: {value!r}")
    return s.zfill(width)
