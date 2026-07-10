"""test_tenant_isolation.py — テナント越境ゼロの検証（設計書 §10.5 受け入れ条件(4)・§9.3）。

要求 tenant 以外の hit / node / edge / citation が1件も混入しないことを検証する。
スタブでも他テナント fixture を混ぜ（＝汚染データを注入し）、機構的除去が効くことを確かめる。
"""

from __future__ import annotations

import pytest

from kre.contract import (
    Citation,
    GraphContext,
    GraphEdge,
    GraphNode,
    Hit,
    Ref,
    RetrieveQuery,
    RetrieveRequest,
    RetrieveResult,
)
from kre.stub import StubRetrievalEngine, enforce_tenant_boundary


def _all_identifiers(result: RetrieveResult) -> list[str]:
    """result 中に現れる全 id（hits / citations / nodes / edges の端点）を集める。"""
    ids: list[str] = []
    ids += [h.id for h in result.hits]
    ids += [c.id for c in result.citations]
    ids += [n.id for n in result.graph_context.nodes]
    for e in result.graph_context.edges:
        ids += [e.src, e.dst]
    return ids


def _req(tenant_id: str) -> RetrieveRequest:
    return RetrieveRequest(tenant_id=tenant_id, query=RetrieveQuery(free_text="値上げ 過去経緯"))


def test_each_tenant_gets_only_own_data(stub: StubRetrievalEngine) -> None:
    """同梱 fixtures（t-frd + t-acme）で、各テナントは自テナントの id のみ受け取ること。"""
    frd = stub.retrieve(_req("t-frd"))
    assert _all_identifiers(frd), "t-frd はヒットを持つはず"
    assert all(i.startswith("t-frd:") for i in _all_identifiers(frd))
    assert not any("t-acme" in i for i in _all_identifiers(frd))

    acme = stub.retrieve(_req("t-acme"))
    assert all(i.startswith("t-acme:") for i in _all_identifiers(acme))
    assert not any("t-frd" in i for i in _all_identifiers(acme))


def _poisoned_result() -> RetrieveResult:
    """t-frd の結果に t-acme のデータを故意に混入させた汚染 result を作る。"""
    return RetrieveResult(
        hits=[
            Hit(id="t-frd:case:No.500023", source="case", score=0.9, snippet="自社", ref=Ref(table="negotiation_cases", pk="No.500023")),
            Hit(id="t-acme:case:No.700088", source="case", score=0.95, snippet="他テナント混入", ref=Ref(table="negotiation_cases", pk="No.700088")),
        ],
        graph_context=GraphContext(
            nodes=[
                GraphNode(id="t-frd:sup:12", type="supplier", label="丸紅畜産"),
                GraphNode(id="t-acme:sup:44", type="supplier", label="スターゼン(他テナント)"),
            ],
            edges=[
                GraphEdge(src="t-frd:case:No.500023", dst="t-frd:sup:12", relation="取引先"),
                # 片端が他テナント → 除去対象。
                GraphEdge(src="t-frd:case:No.500023", dst="t-acme:sup:44", relation="取引先"),
                # 両端が他テナント → 除去対象。
                GraphEdge(src="t-acme:case:No.700088", dst="t-acme:sup:44", relation="取引先"),
            ],
            summary_text="混入テスト",
        ),
        citations=[
            Citation(id="t-frd:case:No.500023", label="自社", ref=Ref(table="negotiation_cases", pk="No.500023")),
            Citation(id="t-acme:case:No.700088", label="他テナント混入", ref=Ref(table="negotiation_cases", pk="No.700088")),
        ],
        config_version="retrieval-2026-07-09",
    )


def test_enforce_tenant_boundary_strips_foreign() -> None:
    """enforce_tenant_boundary が他テナント要素をすべて除去すること（純粋関数レベル）。"""
    cleaned = enforce_tenant_boundary(_poisoned_result(), "t-frd")
    ids = _all_identifiers(cleaned)
    assert ids, "自テナント要素は残るはず"
    assert not any("t-acme" in i for i in ids)
    # 自テナント要素は保持される。
    assert any(i == "t-frd:case:No.500023" for i in ids)
    # 片端が他テナントのエッジも除去され、残るエッジは両端とも t-frd。
    for e in cleaned.graph_context.edges:
        assert e.src.startswith("t-frd:") and e.dst.startswith("t-frd:")


def test_stub_blocks_injected_cross_tenant_data() -> None:
    """汚染 fixture を t-frd に登録しても、retrieve が他テナント混入をゼロにすること。"""
    engine = StubRetrievalEngine({"t-frd": _poisoned_result()})
    result = engine.retrieve(_req("t-frd"))
    assert not any("t-acme" in i for i in _all_identifiers(result))


def test_negative_control_leak_without_enforcement() -> None:
    """負の対照: 越境防御を切ると混入が残る＝防御が越境を止めていることの証左。"""
    engine = StubRetrievalEngine({"t-frd": _poisoned_result()}, enforce_tenant=False)
    result = engine.retrieve(_req("t-frd"))
    assert any("t-acme" in i for i in _all_identifiers(result)), (
        "enforce_tenant=False では混入が残るはず（防御機構の必要性を示す）"
    )


def test_unregistered_tenant_yields_no_data(stub: StubRetrievalEngine) -> None:
    """未登録テナントには一切データを返さない（越境以前にゼロ件）。"""
    result = stub.retrieve(_req("t-ghost"))
    assert _all_identifiers(result) == []
