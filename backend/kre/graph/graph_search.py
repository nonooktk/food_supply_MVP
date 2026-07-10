"""graph_search.py — 購買ドメインの GraphRAG（NetworkX + JSON 永続化）。

PoC `retrieval/graph_search.py`（NetworkX・depth=1 隣接・`build_context()`）を転用し、ノード/
エッジ種別を食材購買ドメインへ再設計する（設計 v3 §4）。MVP は NetworkX＋JSON、将来 Cosmos DB。

ノード種別・ID 接頭辞（§4.1・fixture と一致）:
- `product_spec`  … `{tenant}:spec:{spec_id}`
- `supplier`      … `{tenant}:sup:{supplier_id}`
- `case`          … `{tenant}:case:{case_no}`
- `rate_change_reason` … `{tenant}:rc:{RC-xx}`
- `origin`        … `{tenant}:origin:{産地}`

エッジ種別（relation・§4.1）:
- `対象商材`（case→spec） / `取引先`（case→supplier） / `主張変動理由`（case→rc・claimed）
- `認めた変動理由`（case→rc・accepted） / `産地`（spec→origin） / `同一商材`（case↔case・同一 spec_id）

ID 名前空間は AI Search と共有する `{tenant}:{type}:{pk}`（§4.2）。これにより AI Search の
ヒット case id → グラフ case ノードの名前引きが O(1) で成立する。テナント境界は id 接頭辞に
埋め込まれ、`enforce_tenant_boundary`（stub.py）で越境要素を機構的に除去できる（§9.3）。

補完の考え方（§4.1）:
F-03 で AI Search のヒット案件を種として、depth 分の隣接展開に加え、取引先・変動理由の
ハブノード経由で「**同一取引先の別商材**」「**同一変動理由の他社事例**」を補完する。

設計正典: outputs/freeradicals-rfp/02_アーキテクチャ設計書_draft-v3.md §4
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Optional

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from kre.contract import GraphContext, GraphEdge, GraphNode

# グラフ JSON の既定保存先（build_index が生成、engine が読込）。テナント単位に 1 ファイル。
DEFAULT_GRAPH_DIR = Path(__file__).resolve().parent / "data"

# RC-xx 形式の変動理由 id だけをグラフ化する（seed で名称→RC 変換に漏れた自由記述は除外）。
_RC_PATTERN = re.compile(r"^RC-\d+$")


# ==============================================================================
# ラベル生成
# ==============================================================================
def spec_label(product_name: Optional[str], origin: Optional[str], storage_type: Optional[str]) -> str:
    """スペックの表示ラベルを「商材名／産地／温度帯」で組み立てる（未定は省く）。"""
    parts = [p for p in (product_name, origin, storage_type) if p]
    return "／".join(parts) if parts else "（スペック）"


def _case_label(case: m.NegotiationCase, spec_name: str, supplier_name: str) -> str:
    """案件の表示ラベル（案件番号＋商材＋取引先＋種別）。"""
    bits = [case.case_no]
    if spec_name:
        bits.append(spec_name)
    if supplier_name:
        bits.append(supplier_name)
    if case.case_type:
        bits.append(case.case_type)
    return " ".join(bits)


# ==============================================================================
# DB → グラフレコード（nodes / edges）
# ==============================================================================
def build_graph_records(session: Session, tenant_id: str) -> tuple[list[dict], list[dict]]:
    """1テナント分の業務テーブルからノード／エッジのレコード列を構築する（§4.1）。

    Returns:
        (nodes, edges)
        nodes: [{"id","type","label"}]
        edges: [{"source","target","relation"}]（PoC の edges.json と同じキー）
    """
    ns = tenant_id
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def add_node(nid: str, ntype: str, label: str) -> None:
        nodes.setdefault(nid, {"id": nid, "type": ntype, "label": label})

    def add_edge(src: str, dst: str, relation: str) -> None:
        edges.append({"source": src, "target": dst, "relation": relation})

    # 共有マスタ: 変動理由名（テナント非依存）。
    reason_name = {
        r.reason_id: r.reason_name
        for r in session.execute(select(m.RateChangeReason)).scalars()
    }

    def add_rc(rc_id: str) -> Optional[str]:
        """RC-xx なら rc ノードを追加して id を返す。自由記述は None。"""
        rc_id = str(rc_id).strip()
        if not _RC_PATTERN.match(rc_id):
            return None
        rid = f"{ns}:rc:{rc_id}"
        add_node(rid, "rate_change_reason", reason_name.get(rc_id, rc_id))
        return rid

    # 商材名の逆引き（product_id → product_name）。
    product_name = {
        p.product_id: p.product_name
        for p in session.execute(
            select(m.Product).where(m.Product.tenant_id == ns)
        ).scalars()
    }

    # supplier ノード。
    for sup in session.execute(
        select(m.Supplier).where(m.Supplier.tenant_id == ns)
    ).scalars():
        add_node(f"{ns}:sup:{sup.supplier_id}", "supplier", sup.supplier_name)

    # product_spec / origin ノード＋産地エッジ。
    spec_name: dict[int, str] = {}
    for spec in session.execute(
        select(m.ProductSpec).where(m.ProductSpec.tenant_id == ns)
    ).scalars():
        label = spec_label(product_name.get(spec.product_id), spec.origin, spec.storage_type)
        spec_name[spec.spec_id] = label
        sid = f"{ns}:spec:{spec.spec_id}"
        add_node(sid, "product_spec", label)
        if spec.origin:
            oid = f"{ns}:origin:{spec.origin}"
            add_node(oid, "origin", spec.origin)
            add_edge(sid, oid, "産地")

    # supplier 名の逆引き（case ラベル用）。
    supplier_name = {
        s.supplier_id: s.supplier_name
        for s in session.execute(
            select(m.Supplier).where(m.Supplier.tenant_id == ns)
        ).scalars()
    }

    # case ノード＋対象商材／取引先／主張変動理由エッジ。同一 spec の case を集約。
    cases_by_spec: dict[int, list[str]] = {}
    for case in session.execute(
        select(m.NegotiationCase).where(m.NegotiationCase.tenant_id == ns)
    ).scalars():
        cid = f"{ns}:case:{case.case_no}"
        add_node(
            cid,
            "case",
            _case_label(case, spec_name.get(case.spec_id, ""), supplier_name.get(case.supplier_id, "")),
        )
        add_edge(cid, f"{ns}:spec:{case.spec_id}", "対象商材")
        add_edge(cid, f"{ns}:sup:{case.supplier_id}", "取引先")
        for rc in case.claimed_reasons or []:
            rid = add_rc(rc)
            if rid:
                add_edge(cid, rid, "主張変動理由")
        cases_by_spec.setdefault(case.spec_id, []).append(cid)

    # 認めた変動理由エッジ（negotiation_results.accepted_reasons）。
    for res in session.execute(
        select(m.NegotiationResult).where(m.NegotiationResult.tenant_id == ns)
    ).scalars():
        cid = f"{ns}:case:{res.case_no}"
        if cid not in nodes:
            continue  # 親 case が無い決着は無視（FK 上は起きない）
        for rc in res.accepted_reasons or []:
            rid = add_rc(rc)
            if rid:
                add_edge(cid, rid, "認めた変動理由")

    # 同一商材エッジ（同一 spec_id の case ペア・BR-10 補完）。
    for cids in cases_by_spec.values():
        for i in range(len(cids)):
            for j in range(i + 1, len(cids)):
                add_edge(cids[i], cids[j], "同一商材")

    return list(nodes.values()), edges


# ==============================================================================
# JSON 永続化（テナント単位 1 ファイル）
# ==============================================================================
def graph_path(tenant_id: str, base_dir: Path = DEFAULT_GRAPH_DIR) -> Path:
    """テナントのグラフ JSON パス。ファイル名の区切りは `_` へ置換（安全側）。"""
    safe = tenant_id.replace("/", "_").replace(":", "_")
    return Path(base_dir) / f"{safe}.json"


def save_graph_records(
    tenant_id: str, nodes: list[dict], edges: list[dict], base_dir: Path = DEFAULT_GRAPH_DIR
) -> Path:
    """ノード／エッジを JSON に保存する。"""
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    path = graph_path(tenant_id, base_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"tenant_id": tenant_id, "nodes": nodes, "edges": edges}, f, ensure_ascii=False, indent=2)
    return path


def load_graph_records(
    tenant_id: str, base_dir: Path = DEFAULT_GRAPH_DIR
) -> Optional[tuple[list[dict], list[dict]]]:
    """JSON からノード／エッジを読み込む。ファイルが無ければ None。"""
    path = graph_path(tenant_id, base_dir)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("nodes", []), data.get("edges", [])


# ==============================================================================
# PurchasingGraph（NetworkX ラッパ）
# ==============================================================================
class PurchasingGraph:
    """購買ドメインのグラフ。無向 MultiGraph に relation と向き(src,dst)を保持する。

    無向にするのは depth 展開を双方向にたどるため。emit 時は元の向き(src→dst)を復元する。
    """

    def __init__(self, graph: nx.MultiGraph, node_index: dict[str, dict]) -> None:
        self.g = graph
        self.nodes = node_index  # id -> {"id","type","label"}

    @classmethod
    def from_records(cls, nodes: list[dict], edges: list[dict]) -> "PurchasingGraph":
        node_index = {n["id"]: n for n in nodes}
        g = nx.MultiGraph()
        for n in nodes:
            g.add_node(n["id"], **n)
        for e in edges:
            s, t = e["source"], e["target"]
            # 端点が未定義のエッジは張らない（越境・不整合の混入防止）。
            if s in node_index and t in node_index:
                g.add_edge(s, t, relation=e["relation"], src=s, dst=t)
        return cls(g, node_index)

    @classmethod
    def from_db(cls, session: Session, tenant_id: str) -> "PurchasingGraph":
        nodes, edges = build_graph_records(session, tenant_id)
        return cls.from_records(nodes, edges)

    def node_type(self, node_id: str) -> Optional[str]:
        n = self.nodes.get(node_id)
        return n["type"] if n else None

    def neighbors(self, node_id: str) -> list[tuple[str, str, str, str]]:
        """node_id に接続する (相手ノードid, relation, 元src, 元dst) を列挙する。"""
        if node_id not in self.g:
            return []
        out: list[tuple[str, str, str, str]] = []
        for _, other, data in self.g.edges(node_id, data=True):
            out.append((other, data.get("relation", ""), data.get("src", node_id), data.get("dst", other)))
        return out


# ==============================================================================
# Context Builder（検索ヒット → グラフ補完）
# ==============================================================================
def build_graph_context(
    pgraph: PurchasingGraph,
    seed_ids: Iterable[str],
    *,
    depth: int = 1,
    max_neighbors: int = 20,
    node_types: Optional[Iterable[str]] = None,
    edge_types: Optional[Iterable[str]] = None,
) -> GraphContext:
    """種ノード（AI Search ヒット由来）から depth 展開＋ハブ展開で文脈を組み立てる（§4.1）。

    - depth: 種からの隣接展開ホップ数（MVP=1）。0 以下なら空文脈。
    - ハブ展開: 展開で得た supplier / rate_change_reason ノード経由で
      「同一取引先の別商材」「同一変動理由の他社事例」を補完する。
    - node_types / edge_types: 展開対象の絞り込み（§11 の graph.node_types / edge_types）。
    """
    if depth <= 0:
        return GraphContext()

    node_type_set = set(node_types) if node_types is not None else None
    edge_type_set = set(edge_types) if edge_types is not None else None

    picked_nodes: dict[str, dict] = {}
    picked_edges: list[tuple[str, str, str]] = []
    edge_seen: set[tuple[str, str, str]] = set()

    def take_node(nid: str) -> bool:
        nd = pgraph.nodes.get(nid)
        if nd is None:
            return False
        if node_type_set is not None and nd["type"] not in node_type_set:
            return False
        picked_nodes.setdefault(nid, nd)
        return True

    def take_edge(src: str, dst: str, relation: str) -> None:
        if edge_type_set is not None and relation not in edge_type_set:
            return
        if src in picked_nodes and dst in picked_nodes:
            key = (src, dst, relation)
            if key not in edge_seen:
                edge_seen.add(key)
                picked_edges.append(key)

    seeds = [s for s in seed_ids if s in pgraph.nodes]
    for s in seeds:
        take_node(s)

    visited: set[str] = set(seeds)
    hubs: set[str] = set()

    # ---- depth ホップの隣接展開 ----
    frontier = set(seeds)
    for _ in range(depth):
        nxt: set[str] = set()
        for nid in frontier:
            count = 0
            for other, relation, esrc, edst in pgraph.neighbors(nid):
                if count >= max_neighbors:
                    break
                if take_node(other):
                    take_edge(esrc, edst, relation)
                    count += 1
                    if pgraph.node_type(other) in ("supplier", "rate_change_reason"):
                        hubs.add(other)
                    if other not in visited:
                        visited.add(other)
                        nxt.add(other)
        frontier = nxt

    # ---- ハブ展開: 同一取引先の別商材 / 同一変動理由の他社事例 ----
    other_specs: list[str] = []  # 別商材（summary 用）
    other_cases: list[str] = []  # 他社事例（summary 用）
    for hub in list(hubs):
        hub_type = pgraph.node_type(hub)
        count = 0
        for other, relation, esrc, edst in pgraph.neighbors(hub):
            if count >= max_neighbors:
                break
            if pgraph.node_type(other) == "case" and other not in seeds:
                if take_node(other):
                    take_edge(esrc, edst, relation)
                    count += 1
                    if hub_type == "rate_change_reason":
                        other_cases.append(other)
                    # その案件の対象商材（別商材）を引き込む。
                    for o2, rel2, es2, ed2 in pgraph.neighbors(other):
                        if rel2 == "対象商材" and take_node(o2):
                            take_edge(es2, ed2, rel2)
                            if hub_type == "supplier" and o2 not in [s for s in seeds]:
                                other_specs.append(o2)

    summary = _summarize(pgraph, seeds, hubs, other_specs, other_cases, picked_nodes)

    nodes = [GraphNode(id=n["id"], type=n["type"], label=n["label"]) for n in picked_nodes.values()]
    edges = [GraphEdge(src=s, dst=d, relation=r) for (s, d, r) in picked_edges]
    return GraphContext(nodes=nodes, edges=edges, summary_text=summary)


def _summarize(
    pgraph: PurchasingGraph,
    seeds: list[str],
    hubs: set[str],
    other_specs: list[str],
    other_cases: list[str],
    picked_nodes: dict[str, dict],
) -> str:
    """補完結果を自然文に要約する（FR-08 生成の材料）。"""
    supplier_labels = sorted(
        {pgraph.nodes[h]["label"] for h in hubs if pgraph.node_type(h) == "supplier"}
    )
    reason_labels = sorted(
        {pgraph.nodes[h]["label"] for h in hubs if pgraph.node_type(h) == "rate_change_reason"}
    )
    same_spec_cases = sum(
        1 for nid in picked_nodes if pgraph.node_type(nid) == "case" and nid not in seeds
    )

    parts: list[str] = []
    if supplier_labels:
        parts.append(f"取引先『{'・'.join(supplier_labels)}』に関する案件文脈を補完。")
    if reason_labels:
        parts.append(f"変動理由『{'・'.join(reason_labels)}』が関与。")
    if other_specs:
        spec_labels = sorted({pgraph.nodes[s]["label"] for s in other_specs if s in pgraph.nodes})
        if spec_labels:
            parts.append(f"同一取引先の別商材（{'・'.join(spec_labels)}）でも関連案件あり。")
    if other_cases:
        parts.append(f"同一変動理由の他社事例が {len(set(other_cases))} 件。")
    if same_spec_cases:
        parts.append(f"同一商材の過去案件が {same_spec_cases} 件（過去経緯参照）。")
    return " ".join(parts)
