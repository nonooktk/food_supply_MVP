"""test_vector_store_filter.py — テナントフィルタ AND 強制の検証（設計 §3.2・受け入れ条件(4)）。

Azure に接続せず、OData フィルタ組み立て（純関数）だけを検証する。
"""

from __future__ import annotations

import pytest

from kre.retrieval.vector_store import TenantScopeError, build_tenant_filter


def test_tenant_clause_is_always_first_and_anded() -> None:
    """tenant_id 句が常に先頭・AND 強制されること。"""
    f = build_tenant_filter("t-frd", {"supplier_id": 12, "spec_id": 305})
    assert f.startswith("tenant_id eq 't-frd'")
    assert " and supplier_id eq 12" in f
    assert " and spec_id eq 305" in f


def test_empty_tenant_is_rejected() -> None:
    """テナント未指定は例外で拒否（Deny by Default・越境防御）。"""
    with pytest.raises(TenantScopeError):
        build_tenant_filter("", {"supplier_id": 12})


def test_only_tenant_when_no_filters() -> None:
    """追加フィルタが無ければ tenant 句のみ。"""
    assert build_tenant_filter("t-frd") == "tenant_id eq 't-frd'"


def test_infomart_and_year_month_range() -> None:
    """infomart_code（文字列等値）と year_month_range（範囲）が展開されること。"""
    f = build_tenant_filter(
        "t-frd", {"infomart_code": "113501", "year_month_range": ["2025-01", "2025-07"]}
    )
    assert "infomart_code eq '113501'" in f
    assert "year_month ge '2025-01' and year_month le '2025-07'" in f


def test_odata_single_quote_is_escaped() -> None:
    """テナント値のシングルクォートがエスケープされること（OData インジェクション防止）。"""
    f = build_tenant_filter("t-o'brien")
    assert "tenant_id eq 't-o''brien'" in f
