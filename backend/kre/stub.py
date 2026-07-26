"""stub.py — KRE 契約テスト用スタブ実装（設計書 draft-v3 §5・§10）。

``fixtures/`` の代表 fixture を返す ``StubRetrievalEngine`` を提供する。本体（``app/``）は
``USE_KRE_STUB=true`` のときこれを DI で注入し、AI Search / Azure OpenAI 未接続でも
FR-03 / FR-08供給 を並行実装できる（§1・§5）。

安全設計（テナント越境ゼロ・§9.3・§10.5 受け入れ条件(4)）:
- ``retrieve`` は ``req.tenant_id`` を唯一の源泉とし、``enforce_tenant_boundary`` で
  id 接頭辞（``{tenant}:{type}:{pk}``・§4.2）が要求テナントと一致しない hit / node / edge /
  citation を機構的に除去する。fixture に他テナントデータが混入しても越境を物理的に遮断する。
- ``graph_context.summary_text``（自然文・id を持たない）も検査対象とする（監査 F-9）。
  他要素の汚染を検知した場合、または要約中に他テナントの id トークンを見つけた場合は、
  要約全体を破棄する（fail-closed）。本体はこの要約を LLM プロンプトへ載せるため
  （``app/api/strategy.py`` → ``StrategyContext.graph_summary``）、ここが唯一の非フィルタ経路
  だった。

config 反映（§10.5 受け入れ条件(2)・§11）:
- ``search.top_k`` でヒット件数を制限し、``graph.enabled`` / ``options.include_graph`` で
  グラフ補完の有無を切り替える。既定 config では fixture と完全一致する（top_k=10・graph 有効）。

設計正典: outputs/freeradicals-rfp/02_アーキテクチャ設計書_draft-v3.md §5・§9・§10・§11
"""

from __future__ import annotations

import json
import logging
import re
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

logger = logging.getLogger(__name__)

# 同梱 fixture ディレクトリ（backend/kre/fixtures/）。
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# 自然文（summary_text）に紛れ込んだ id 形式トークン（``{tenant}:{type}:{pk}``・§4.2）を拾う。
# 3 セグメント固定で照合するため、"10:30:00" のような時刻表記も形式上は一致しうるが、
# その場合も「所属不明」として fail-closed 側（要約破棄）に倒す設計とする（監査 F-9）。
_ID_TOKEN_RE = re.compile(r"[0-9A-Za-z_.\-]+:[0-9A-Za-z_.\-]+:[0-9A-Za-z_.\-]+")


def _tenant_of(identifier: str) -> Optional[str]:
    """id（``{tenant}:{type}:{pk}``・§4.2）からテナント部を取り出す。

    区切りが無い id は所属不明として None を返す（越境防御では除去対象になる）。
    """
    if ":" in identifier:
        return identifier.split(":", 1)[0]
    return None


def _summary_within_boundary(summary_text: str, tenant_id: str, graph_contaminated: bool) -> str:
    """summary_text（自然文）にも越境検査をかける（監査 F-9・§10.5(4) の補強）。

    summary_text は id を持たない自然文のため、接頭辞判定だけでは他テナントの取引先名が
    載ったことを検出できない。そこで**2段の fail-closed 判定**を行う。

    1. 要約の出所であるグラフ（node / edge）から他テナント要素が1件でも除去された
       （``graph_contaminated``）なら、同じ汚染グラフから作られた要約は信頼できない →
       **要約全体を破棄する**。想定シナリオ（グラフ生成不具合・索引再構築時の取り違え・
       将来のクロステナント補完の追加）はいずれもグラフ側の混入を伴うため、ここで捕捉できる。
       要約は ``kre/graph/graph_search.py`` の ``_summarize`` が採用済みノードだけから
       組み立てるので、hit / citation（検索層）の汚染は要約の出所にならない＝判定に含めない。
    2. グラフに除去が無くても、要約中に他テナント（または所属不明）の id トークンが
       含まれていれば同様に破棄する。

    どちらでもなければ要約をそのまま保持する（正常系の情報量を落とさない）。
    """
    if not summary_text:
        return ""
    if graph_contaminated:
        logger.warning(
            "[KRE] グラフに越境要素を検出したため graph_context.summary_text を破棄しました "
            "(tenant_id=%s・監査 F-9)",
            tenant_id,
        )
        return ""
    foreign = [t for t in _ID_TOKEN_RE.findall(summary_text) if _tenant_of(t) != tenant_id]
    if foreign:
        logger.warning(
            "[KRE] summary_text に他テナント id が含まれるため破棄しました "
            "(tenant_id=%s・検出数=%d・監査 F-9)",
            tenant_id,
            len(foreign),
        )
        return ""
    return summary_text


def enforce_tenant_boundary(result: RetrieveResult, tenant_id: str) -> RetrieveResult:
    """RetrieveResult から要求テナント以外の要素を機構的に除去する（越境ゼロ・§10.5(4)）。

    - hit / citation: id 接頭辞が tenant_id と一致するものだけ残す。
    - node: id 接頭辞が一致するものだけ残す。
    - edge: src・dst の双方が一致するものだけ残す（片側でも他テナントなら除去）。
    - summary_text: 自然文のため接頭辞では濾せない。グラフ（node / edge）の汚染検知、または
      要約中の他テナント id 検出をもって**要約全体を破棄**する（fail-closed・監査 F-9）。
      → 対象／対象外の範囲は docs/TASK_knowledge-graph-optimization.md §2.2 に明記している。
    """
    hits = [h for h in result.hits if _tenant_of(h.id) == tenant_id]
    citations = [c for c in result.citations if _tenant_of(c.id) == tenant_id]
    nodes = [n for n in result.graph_context.nodes if _tenant_of(n.id) == tenant_id]
    edges = [
        e
        for e in result.graph_context.edges
        if _tenant_of(e.src) == tenant_id and _tenant_of(e.dst) == tenant_id
    ]
    # グラフ（要約の出所）から1件でも除去された＝要約も信頼できない（fail-closed・F-9）。
    graph_contaminated = len(nodes) != len(result.graph_context.nodes) or len(edges) != len(
        result.graph_context.edges
    )
    summary_text = _summary_within_boundary(
        result.graph_context.summary_text, tenant_id, graph_contaminated
    )
    return result.model_copy(
        update={
            "hits": hits,
            "citations": citations,
            "graph_context": GraphContext(nodes=nodes, edges=edges, summary_text=summary_text),
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
