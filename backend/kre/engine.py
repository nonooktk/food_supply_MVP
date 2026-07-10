"""engine.py — RetrievalEngine 本実装（AzureRetrievalEngine・設計 v3 §5・§9・§10・§11）。

`RetrievalEngine` Protocol（contract.py）の本実装。検索（AI Search ハイブリッド）→ グラフ補完
（GraphRAG・depth 展開）→ テナント越境ゼロ強制（enforce_tenant_boundary）→ `RetrieveResult`
の順で処理する。`retrieval_config`（§11）のノブ（top_k / hybrid_weight / graph.enabled / depth）を
反映する。

DI（§5）:
- 本体 `app/api/deps.py` は ``USE_KRE_STUB=false`` のとき本エンジンを注入する。
  スタブ（stub.py）と同一の Protocol を満たすため、本体の呼び出し口は不変。
- 依存（検索関数・グラフ供給）は注入可能にし、テストでは Azure を呼ばず検証できる。

安全設計（§9.3・§10.5 受け入れ条件(4)）:
- 検索は vector_store.search が ``tenant_id`` を OData で AND 強制（第1の防波堤）。
- 返却直前に enforce_tenant_boundary で id 接頭辞不一致の要素を除去（第2の防波堤）。
  二重防御でテナント越境をゼロにする。

設計正典: outputs/freeradicals-rfp/02_アーキテクチャ設計書_draft-v3.md §5・§9・§10・§11
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from kre.config.loader import RetrievalConfig, load_retrieval_config
from kre.contract import (
    Citation,
    EngineHealth,
    GraphContext,
    Hit,
    HitSource,
    IndexEvent,
    Ref,
    RetrieveQuery,
    RetrieveRequest,
    RetrieveResult,
)
from kre.graph.graph_search import (
    DEFAULT_GRAPH_DIR,
    PurchasingGraph,
    build_graph_context,
    load_graph_records,
)
from kre.retrieval.vector_store import search as vs_search
from kre.stub import enforce_tenant_boundary

logger = logging.getLogger(__name__)

# hit.source → 業務テーブル名（ref.table・§10.2）。
SOURCE_TO_TABLE: dict[str, str] = {
    "case": "negotiation_cases",
    "result": "negotiation_results",
    "market": "market_rates",
    "spec": "product_specs",
    "supplier": "suppliers",
    "strategy": "strategy_sheets",
}
_VALID_SOURCES = set(SOURCE_TO_TABLE.keys())

# 検索関数の型（vector_store.search 互換。テスト時は差し替え）。
SearchFn = Callable[..., list[dict]]


def _pk_of(identifier: str) -> str:
    """id ``{tenant}:{type}:{pk}`` から pk 部を取り出す（pk 内の ':' は保持）。"""
    parts = identifier.split(":", 2)
    return parts[2] if len(parts) == 3 else identifier


def _compose_query_text(query: RetrieveQuery) -> str:
    """RetrieveQuery を検索テキストへ写像する（§10.2 の「いずれか」）。"""
    if query.free_text:
        return query.free_text
    if query.case_no:
        return query.case_no
    bits: list[str] = []
    if query.spec_id is not None:
        bits.append(f"spec:{query.spec_id}")
    if query.supplier_id is not None:
        bits.append(f"supplier:{query.supplier_id}")
    if query.reason_tags:
        bits.extend(query.reason_tags)
    return " ".join(bits)


def _compose_filters(req: RetrieveRequest) -> dict:
    """RetrieveFilters（＋属性クエリ）を vector_store 用フィルタ dict へ写像する。"""
    f = req.filters
    filters: dict = {}
    if f.infomart_code:
        filters["infomart_code"] = f.infomart_code
    # supplier_id / spec_id は filters と query の双方を尊重（filters 優先）。
    supplier_id = f.supplier_id if f.supplier_id is not None else req.query.supplier_id
    spec_id = f.spec_id if f.spec_id is not None else req.query.spec_id
    if supplier_id is not None:
        filters["supplier_id"] = supplier_id
    if spec_id is not None:
        filters["spec_id"] = spec_id
    if f.year_month_range:
        filters["year_month_range"] = f.year_month_range
    return filters


class FileGraphProvider:
    """テナント別グラフ JSON（build_index が生成）を読み込み PurchasingGraph を供給する。"""

    def __init__(self, base_dir: Path = DEFAULT_GRAPH_DIR) -> None:
        self._base_dir = Path(base_dir)
        self._cache: dict[str, Optional[PurchasingGraph]] = {}

    def get(self, tenant_id: str) -> Optional[PurchasingGraph]:
        if tenant_id not in self._cache:
            records = load_graph_records(tenant_id, self._base_dir)
            self._cache[tenant_id] = (
                PurchasingGraph.from_records(*records) if records is not None else None
            )
        return self._cache[tenant_id]


class AzureRetrievalEngine:
    """RetrievalEngine の本実装（AI Search + GraphRAG）。"""

    def __init__(
        self,
        config: Optional[RetrievalConfig] = None,
        *,
        search_fn: Optional[SearchFn] = None,
        graph_provider: Optional[object] = None,
        enforce_tenant: bool = True,
    ) -> None:
        self._config = config or load_retrieval_config()
        self._search_fn = search_fn or vs_search
        # 検索関数を注入した場合（テスト）は health で AI Search へ実接続しない。
        self._live_index = search_fn is None
        self._graph_provider = graph_provider or FileGraphProvider()
        self._enforce_tenant = enforce_tenant
        self._last_sync_at: Optional[datetime] = None
        self._doc_count = 0

    # ---- RetrievalEngine Protocol 実装 ------------------------------------
    def retrieve(self, req: RetrieveRequest) -> RetrieveResult:
        cfg = self._config
        top_k = req.options.top_k if req.options.top_k is not None else cfg.search.top_k
        include_graph = (
            req.options.include_graph
            if req.options.include_graph is not None
            else cfg.graph.enabled
        )
        depth = req.options.depth if req.options.depth is not None else cfg.graph.depth

        query_text = _compose_query_text(req.query)
        filters = _compose_filters(req)

        # 1) 検索（AI Search ハイブリッド・テナント AND 強制）。
        raw_hits = self._search_fn(
            query_text,
            top_k,
            tenant_id=req.tenant_id,
            filters=filters,
            hybrid_weight=cfg.search.hybrid_weight,
        )
        hits = [self._to_hit(h) for h in raw_hits]
        hits = [h for h in hits if h is not None][:top_k]

        # 2) グラフ補完（GraphRAG・depth 展開＋ハブ展開）。
        graph_context = GraphContext()
        if include_graph and depth > 0:
            graph_context = self._build_graph_context(req, hits, depth)

        # 3) 引用元（case ヒットを根拠として供給・FR-08）。
        citations = self._build_citations(hits)

        result = RetrieveResult(
            hits=hits,
            graph_context=graph_context,
            citations=citations,
            config_version=cfg.config_version,
        )

        # 4) テナント越境ゼロ強制（第2の防波堤・§10.5(4)）。
        if self._enforce_tenant:
            result = enforce_tenant_boundary(result, req.tenant_id)
        return result

    def index_upsert(self, ev: IndexEvent) -> None:
        """取込イベントを受けて整合状態を更新する（§10.5）。

        MVP の索引・グラフはバッチ再構築（kre/scripts/build_index.py）で整合を取るため、
        本メソッドは同期時刻と件数の擬似更新に留める（設計 §4.3・§3.2 の sync 方針）。
        単発 upsert の即時反映は kre/services 側の indexer 導入時に接続する。
        """
        if ev.op == "upsert":
            self._doc_count += 1
        elif ev.op == "delete":
            self._doc_count = max(0, self._doc_count - 1)
        self._last_sync_at = datetime.now(timezone.utc)

    def health(self) -> EngineHealth:
        """エンジンの健全性を返す。index/graph の ready は接続設定の有無で判定する。"""
        index_ready = True
        doc_count = self._doc_count
        if self._live_index:
            try:  # 実 index に接続できれば正確な件数を取得（未接続でも health は失敗させない）。
                from kre.retrieval.vector_store import _get_client  # 遅延 import

                doc_count = int(_get_client().get_document_count())
            except Exception as exc:  # noqa: BLE001 - health はベストエフォート
                logger.debug("doc_count の取得に失敗（未接続の可能性）: %s", exc)
                index_ready = self._last_sync_at is not None or self._doc_count > 0
        else:
            index_ready = self._last_sync_at is not None or self._doc_count > 0

        graph_ready = self._graph_ready()
        return EngineHealth(
            index_ready=index_ready,
            graph_ready=graph_ready,
            last_sync_at=self._last_sync_at,
            doc_count=doc_count,
        )

    # ---- 内部ヘルパ --------------------------------------------------------
    def _graph_ready(self) -> bool:
        base = getattr(self._graph_provider, "_base_dir", None)
        if base is None:
            return True
        try:
            return any(Path(base).glob("*.json"))
        except Exception:  # noqa: BLE001
            return False

    def _to_hit(self, raw: dict) -> Optional[Hit]:
        """検索結果 dict を Hit へ写像する。未知 source は捨てる（契約違反を混入させない）。"""
        source = raw.get("source", "")
        if source not in _VALID_SOURCES:
            logger.debug("未知の source を無視: %r（id=%s）", source, raw.get("id"))
            return None
        identifier = raw["id"]
        snippet = raw.get("content", "") or raw.get("name", "")
        return Hit(
            id=identifier,
            source=source,  # type: ignore[arg-type]  # 上で Literal 集合に限定済み
            score=float(raw.get("score", 0.0)),
            snippet=snippet[:400],
            ref=Ref(table=SOURCE_TO_TABLE[source], pk=_pk_of(identifier)),
        )

    def _seed_ids(self, req: RetrieveRequest, hits: list[Hit]) -> list[str]:
        """グラフ展開の種ノード id を決める（case ヒット＋属性クエリの spec/supplier）。"""
        seeds: list[str] = [h.id for h in hits if h.source == "case"]
        # 属性クエリ・フィルタで指定された spec/supplier をハブ種として加える。
        spec_id = req.filters.spec_id if req.filters.spec_id is not None else req.query.spec_id
        supplier_id = (
            req.filters.supplier_id if req.filters.supplier_id is not None else req.query.supplier_id
        )
        if spec_id is not None:
            seeds.append(f"{req.tenant_id}:spec:{spec_id}")
        if supplier_id is not None:
            seeds.append(f"{req.tenant_id}:sup:{supplier_id}")
        # 重複排除（順序保持）。
        seen: set[str] = set()
        uniq: list[str] = []
        for s in seeds:
            if s not in seen:
                seen.add(s)
                uniq.append(s)
        return uniq

    def _build_graph_context(self, req: RetrieveRequest, hits: list[Hit], depth: int) -> GraphContext:
        pgraph = self._graph_provider.get(req.tenant_id)
        if pgraph is None:
            return GraphContext()
        seeds = self._seed_ids(req, hits)
        if not seeds:
            return GraphContext()
        cfg = self._config
        return build_graph_context(
            pgraph,
            seeds,
            depth=depth,
            max_neighbors=cfg.graph.max_neighbors,
            node_types=cfg.graph.node_types,
            edge_types=cfg.graph.edge_types,
        )

    def _build_citations(self, hits: list[Hit]) -> list[Citation]:
        """case ヒットを引用元に変換する（FR-08 の根拠）。"""
        citations: list[Citation] = []
        for h in hits:
            if h.source == "case":
                citations.append(
                    Citation(id=h.id, label=f"{h.ref.pk} {h.snippet[:60]}", ref=h.ref)
                )
        return citations


def default_engine() -> AzureRetrievalEngine:
    """既定 config で本実装を構築する（本体 DI 用・stub.default_stub と対になる）。"""
    return AzureRetrievalEngine()
