"""stub.py — KRE 契約テスト用スタブ実装（設計書 draft-v3 §5・§10）。

``fixtures/`` の代表 fixture を返す ``StubRetrievalEngine`` を提供する。本体（``app/``）は
``USE_KRE_STUB=true`` のときこれを DI で注入し、AI Search / Azure OpenAI 未接続でも
FR-03 / FR-08供給 を並行実装できる（§1・§5）。

安全設計（テナント越境ゼロ・§9.3・§10.5 受け入れ条件(4)）:
- ``retrieve`` は ``req.tenant_id`` を唯一の源泉とし、``enforce_tenant_boundary`` で
  id 接頭辞（``{tenant}:{type}:{pk}``・§4.2）が要求テナントと一致しない hit / node / edge /
  citation を機構的に除去する。fixture に他テナントデータが混入しても越境を物理的に遮断する。

config 反映（§10.5 受け入れ条件(2)・§11）:
- ``search.top_k`` でヒット件数を制限し、``graph.enabled`` / ``options.include_graph`` で
  グラフ補完の有無を切り替える。既定 config では fixture と完全一致する（top_k=10・graph 有効）。

設計正典: outputs/freeradicals-rfp/02_アーキテクチャ設計書_draft-v3.md §5・§9・§10・§11
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from kre.config.loader import RetrievalConfig, load_retrieval_config
from kre.contract import (
    EngineHealth,
    GraphContext,
    IndexEvent,
    RetrieveRequest,
    RetrieveResult,
)

# 同梱 fixture ディレクトリ（backend/kre/fixtures/）。
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _tenant_of(identifier: str) -> Optional[str]:
    """id（``{tenant}:{type}:{pk}``・§4.2）からテナント部を取り出す。

    区切りが無い id は所属不明として None を返す（越境防御では除去対象になる）。
    """
    if ":" in identifier:
        return identifier.split(":", 1)[0]
    return None


def enforce_tenant_boundary(result: RetrieveResult, tenant_id: str) -> RetrieveResult:
    """RetrieveResult から要求テナント以外の要素を機構的に除去する（越境ゼロ・§10.5(4)）。

    - hit / citation: id 接頭辞が tenant_id と一致するものだけ残す。
    - node: id 接頭辞が一致するものだけ残す。
    - edge: src・dst の双方が一致するものだけ残す（片側でも他テナントなら除去）。

    summary_text は自然文のため機械的除去はせず保持する（越境の実害は id を持つ要素で生じる）。
    """
    hits = [h for h in result.hits if _tenant_of(h.id) == tenant_id]
    citations = [c for c in result.citations if _tenant_of(c.id) == tenant_id]
    nodes = [n for n in result.graph_context.nodes if _tenant_of(n.id) == tenant_id]
    edges = [
        e
        for e in result.graph_context.edges
        if _tenant_of(e.src) == tenant_id and _tenant_of(e.dst) == tenant_id
    ]
    return result.model_copy(
        update={
            "hits": hits,
            "citations": citations,
            "graph_context": GraphContext(
                nodes=nodes, edges=edges, summary_text=result.graph_context.summary_text
            ),
        },
        deep=True,
    )


def _load_fixture_envelopes(fixtures_dir: Path) -> dict[str, RetrieveResult]:
    """fixtures ディレクトリの *.json（エンベロープ形式）を tenant_id → RetrieveResult に読む。

    エンベロープ形式: ``{"tenant_id": str, "request": {...}, "result": {RetrieveResult}}``
    """
    registry: dict[str, RetrieveResult] = {}
    for path in sorted(fixtures_dir.glob("*.json")):
        with open(path, "r", encoding="utf-8") as f:
            envelope = json.load(f)
        tenant_id = envelope["tenant_id"]
        registry[tenant_id] = RetrieveResult.model_validate(envelope["result"])
    return registry


class StubRetrievalEngine:
    """fixture を返す RetrievalEngine スタブ実装（§5・§10）。

    - テナント単位に代表 fixture を1件保持し、クエリ内容には依らず当該テナントの
      代表結果を返す（並行開発を担保するためのスタブ・§10 前文）。
    - 越境防御・config 反映は本モジュール冒頭の docstring 参照。
    """

    def __init__(
        self,
        registry: dict[str, RetrieveResult],
        *,
        config: Optional[RetrievalConfig] = None,
        enforce_tenant: bool = True,
    ) -> None:
        self._registry = registry
        self._config = config or load_retrieval_config()
        self._enforce_tenant = enforce_tenant
        # doc_count はテナント横断のヒット総数を初期値にする（health 用の擬似値）。
        self._doc_count = sum(len(r.hits) for r in registry.values())
        self._last_sync_at: Optional[datetime] = None

    # ---- ファクトリ --------------------------------------------------------
    @classmethod
    def from_fixtures(
        cls,
        fixtures_dir: Path = FIXTURES_DIR,
        *,
        config: Optional[RetrievalConfig] = None,
        enforce_tenant: bool = True,
    ) -> "StubRetrievalEngine":
        """同梱 fixtures ディレクトリからスタブを構築する。"""
        return cls(
            _load_fixture_envelopes(fixtures_dir),
            config=config,
            enforce_tenant=enforce_tenant,
        )

    # ---- RetrievalEngine Protocol 実装 ------------------------------------
    def retrieve(self, req: RetrieveRequest) -> RetrieveResult:
        """要求テナントの代表 fixture を返す（越境防御・config 反映を適用）。

        該当テナントの fixture が無い場合は空結果（hits/graph/citations 空）を返す。
        """
        base = self._registry.get(req.tenant_id)
        if base is None:
            return RetrieveResult(config_version=self._config.config_version)

        result = base.model_copy(deep=True)

        # 1) 越境ゼロ: 要求テナント以外の要素を機構的に除去する（§10.5(4)）。
        if self._enforce_tenant:
            result = enforce_tenant_boundary(result, req.tenant_id)

        # 2) config / options 反映（§11・§10.5(2)）。
        top_k = req.options.top_k if req.options.top_k is not None else self._config.search.top_k
        include_graph = (
            req.options.include_graph
            if req.options.include_graph is not None
            else self._config.graph.enabled
        )
        result.hits = result.hits[:top_k]
        if not include_graph:
            result.graph_context = GraphContext(summary_text=result.graph_context.summary_text)
        # config_version を反映（再現性の担保・§11）。
        result.config_version = self._config.config_version

        return result

    def index_upsert(self, ev: IndexEvent) -> None:
        """取込イベントを受けて doc_count / last_sync_at を更新する（§10.5）。

        スタブでは索引実体を持たないため、件数と同期時刻の擬似更新のみ行う。
        """
        if ev.op == "upsert":
            self._doc_count += 1
        elif ev.op == "delete":
            self._doc_count = max(0, self._doc_count - 1)
        self._last_sync_at = datetime.now(timezone.utc)

    def health(self) -> EngineHealth:
        """スタブの健全性を返す（索引・グラフは常に ready 扱い）。"""
        return EngineHealth(
            index_ready=True,
            graph_ready=True,
            last_sync_at=self._last_sync_at,
            doc_count=self._doc_count,
        )


def default_stub() -> StubRetrievalEngine:
    """既定の同梱 fixtures / 既定 config でスタブを構築する簡易ファクトリ（本体 DI 用）。"""
    return StubRetrievalEngine.from_fixtures()
