"""test_graph_search.py — 購買 GraphRAG の検証（設計 §4）。

DB から構築したグラフで、ノード/エッジ種別・ID 名前空間・depth=1 補完（同一取引先の別商材・
同一変動理由の他社事例）を検証する。Azure 非接続。
"""

from __future__ import annotations

from kre.graph.graph_search import (
    PurchasingGraph,
    build_graph_context,
    build_graph_records,
    load_graph_records,
    save_graph_records,
)


def test_nodes_and_edges_built_with_shared_id_namespace(purchasing_session) -> None:
    """{tenant}:{type}:{pk} の ID 規則で期待ノード/エッジが構築されること（§4.1・§4.2）。"""
    nodes, edges = build_graph_records(purchasing_session, "t-frd")
    ids = {n["id"] for n in nodes}
    types = {n["id"]: n["type"] for n in nodes}

    # 種となる案件と、取引先・スペック・変動理由・産地のノード。
    assert "t-frd:case:No.500023" in ids
    assert types["t-frd:sup:12"] == "supplier"
    assert types["t-frd:spec:305"] == "product_spec"
    assert types["t-frd:rc:RC-03"] == "rate_change_reason"
    assert types["t-frd:origin:ブラジル産"] == "origin"

    relations = {(e["source"], e["target"], e["relation"]) for e in edges}
    assert ("t-frd:case:No.500023", "t-frd:sup:12", "取引先") in relations
    assert ("t-frd:case:No.500023", "t-frd:spec:305", "対象商材") in relations
    assert ("t-frd:case:No.500023", "t-frd:rc:RC-03", "主張変動理由") in relations
    # 認めた変動理由（決着由来）。
    assert ("t-frd:case:No.500023", "t-frd:rc:RC-03", "認めた変動理由") in relations
    # 同一商材（spec305 を共有する No.500023 と No.500099）。
    same_item = {
        (e["source"], e["target"]) for e in edges if e["relation"] == "同一商材"
    }
    assert ("t-frd:case:No.500023", "t-frd:case:No.500099") in same_item or (
        "t-frd:case:No.500099",
        "t-frd:case:No.500023",
    ) in same_item


def test_no_cross_tenant_ids_in_records(purchasing_session) -> None:
    """t-frd のグラフに t-acme の id が混入しないこと（越境ゼロ・§9.3）。"""
    nodes, edges = build_graph_records(purchasing_session, "t-frd")
    all_ids = [n["id"] for n in nodes]
    all_ids += [e["source"] for e in edges] + [e["target"] for e in edges]
    assert all(i.startswith("t-frd:") for i in all_ids)
    assert not any("t-acme" in i for i in all_ids)


def test_context_completes_other_product_and_other_supplier(purchasing_session) -> None:
    """受け入れ条件(3): 種案件から『同一取引先の別商材』『同一変動理由の他社事例』が補完されること。"""
    pgraph = PurchasingGraph.from_db(purchasing_session, "t-frd")
    ctx = build_graph_context(pgraph, ["t-frd:case:No.500023"], depth=1, max_neighbors=20)

    node_ids = {n.id for n in ctx.nodes}
    labels = {n.label for n in ctx.nodes}

    # 同一取引先（丸紅畜産・sup12）の別商材（鶏むね肉・spec306）が補完される。
    assert "t-frd:spec:306" in node_ids
    assert any("鶏むね肉" in lbl for lbl in labels)
    # 同一変動理由（RC-03）の他社事例（No.500099・東西ミート）が補完される。
    assert "t-frd:case:No.500099" in node_ids
    # summary に両補完が言及される。
    assert "別商材" in ctx.summary_text
    assert "他社事例" in ctx.summary_text


def test_depth_zero_yields_empty_context(purchasing_session) -> None:
    """depth<=0 では空文脈（グラフ補完なし）。"""
    pgraph = PurchasingGraph.from_db(purchasing_session, "t-frd")
    ctx = build_graph_context(pgraph, ["t-frd:case:No.500023"], depth=0)
    assert ctx.nodes == []
    assert ctx.edges == []


def test_edge_type_filter_limits_relations(purchasing_session) -> None:
    """edge_types で relation を絞れること（§11 graph.edge_types）。"""
    pgraph = PurchasingGraph.from_db(purchasing_session, "t-frd")
    ctx = build_graph_context(
        pgraph, ["t-frd:case:No.500023"], depth=1, edge_types=["取引先"]
    )
    assert {e.relation for e in ctx.edges} <= {"取引先"}


def test_graph_json_roundtrip(purchasing_session, tmp_path) -> None:
    """グラフ JSON の保存→読込→再構築が同値であること（永続化の担保・§4.3）。"""
    nodes, edges = build_graph_records(purchasing_session, "t-frd")
    save_graph_records("t-frd", nodes, edges, tmp_path)
    loaded = load_graph_records("t-frd", tmp_path)
    assert loaded is not None
    ln, le = loaded
    assert {n["id"] for n in ln} == {n["id"] for n in nodes}
    assert len(le) == len(edges)
    # 再構築したグラフでも補完が成立する。
    pgraph = PurchasingGraph.from_records(ln, le)
    ctx = build_graph_context(pgraph, ["t-frd:case:No.500023"], depth=1)
    assert "t-frd:spec:306" in {n.id for n in ctx.nodes}
