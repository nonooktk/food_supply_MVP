"""contract.py — KRE（関連知識検索エンジン）インターフェース契約。

本体アプリ（``app/``）と KRE（``kre/``）の唯一の結合面。設計書 draft-v3 §10 に忠実に、
次を定義する。

- ``RetrievalEngine`` Protocol … ``retrieve`` / ``index_upsert`` / ``health`` の3メソッド（§10.1）
- Pydantic データ契約 … ``RetrieveRequest`` / ``RetrieveResult`` / ``IndexEvent`` /
  ``EngineHealth`` とその構成型（§10.2）
- ``RETRIEVE_RESULT_JSON_SCHEMA`` … ``RetrieveResult`` の正準 JSON Schema（§10.3）

この契約を先に固定することで、本体は ``stub.py`` の StubRetrievalEngine で FR-03 / FR-08供給 を
並行実装できる（§10 前文・§5 DI）。将来 KRE を別 Container Apps（HTTP/gRPC）へ切り出しても、
本契約は JSON シリアライズ可能なデータ契約に保つため本体の呼び出し口は不変（§9.4）。

設計正典: outputs/freeradicals-rfp/02_アーキテクチャ設計書_draft-v3.md §9〜§11
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Literal, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

# エンジン実装の版（RetrieveResult.engine_version の既定・§10.2）。
# 本実装（AzureRetrievalEngine）へ差し替えた際は各実装が自身の版を名乗る。
ENGINE_VERSION = "kre-0.1.0"

# 検索ヒットの出所区分（§10.2 / §10.3 の enum・§3.1 の source フィールドに対応）。
HitSource = Literal["case", "strategy", "result", "market", "spec", "supplier"]

# IndexEvent.op（取込契約の操作種別・§10.2）。
IndexOp = Literal["upsert", "delete"]

# IndexEvent.entity の既知集合（§10.2 は "..." で拡張を許すため str だが、既知値を明示）。
KNOWN_ENTITIES: tuple[str, ...] = ("case", "result", "spec", "supplier", "market", "strategy")


# ==============================================================================
# RetrieveRequest 系（§10.2）
# ==============================================================================
class RetrieveQuery(BaseModel):
    """検索クエリ。§10.2 の「次のいずれか」を1モデルに集約する。

    - ``{case_no}``                                … 案件番号ピンポイント
    - ``{free_text}``                              … 自由文
    - ``{spec_id?, supplier_id?, reason_tags?}``   … 属性クエリ

    いずれか1つ以上の指定を必須とする（すべて未指定は不正）。
    """

    model_config = ConfigDict(extra="forbid")

    case_no: Optional[str] = None
    free_text: Optional[str] = None
    spec_id: Optional[int] = None
    supplier_id: Optional[int] = None
    reason_tags: Optional[list[str]] = None

    @model_validator(mode="after")
    def _require_at_least_one(self) -> "RetrieveQuery":
        if not any(
            v is not None
            for v in (self.case_no, self.free_text, self.spec_id, self.supplier_id, self.reason_tags)
        ):
            raise ValueError(
                "RetrieveQuery は case_no / free_text / spec_id / supplier_id / reason_tags "
                "のいずれか1つ以上を指定してください（§10.2）"
            )
        return self


class RetrieveFilters(BaseModel):
    """検索の絞り込み条件（§10.2）。AI Search の OData フィルタへ写像される（§3.2）。

    ※ ``tenant_id`` はここに含めない。テナント境界は ``RetrieveRequest.tenant_id`` を
      唯一の源泉とし、KRE 内で AND 強制する（§3.2・§9.3・§10.5 受け入れ条件(4)）。
    """

    model_config = ConfigDict(extra="forbid")

    infomart_code: Optional[str] = None
    supplier_id: Optional[int] = None
    spec_id: Optional[int] = None
    # 相場ドキュメントの月レンジ（例: ["2025-01", "2025-07"]）。
    year_month_range: Optional[list[str]] = None


class RetrieveOptions(BaseModel):
    """retrieval_config（§11）の一部を単発上書きするオプション（§10.2）。

    特定クエリだけ ``top_k`` や ``depth`` を変えたい場合に使う（§11 末尾）。
    None のキーは config 既定値にフォールバックする。
    """

    model_config = ConfigDict(extra="forbid")

    top_k: Optional[int] = Field(default=None, ge=1)
    include_graph: Optional[bool] = None
    depth: Optional[int] = Field(default=None, ge=0)


class RetrieveRequest(BaseModel):
    """KRE への検索要求（§10.2）。

    ``tenant_id`` は必須であり、テナント越境を物理的に遮断する唯一の源泉である
    （§9.3・§10.5 受け入れ条件(4)）。本体は JWT から解決した tenant_id をここに渡す。
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    query: RetrieveQuery
    filters: RetrieveFilters = Field(default_factory=RetrieveFilters)
    options: RetrieveOptions = Field(default_factory=RetrieveOptions)


# ==============================================================================
# RetrieveResult 系（§10.2 / §10.3）
# ==============================================================================
class Ref(BaseModel):
    """業務テーブルへの参照（§10.2 hits[].ref / citations[].ref）。"""

    model_config = ConfigDict(extra="forbid")

    table: str
    pk: str


class Hit(BaseModel):
    """検索ヒット1件（§10.2 hits[]）。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    source: HitSource
    score: float
    snippet: str
    ref: Ref


class GraphNode(BaseModel):
    """グラフ補完のノード（§10.2 graph_context.nodes[]・§4.1）。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    label: str


class GraphEdge(BaseModel):
    """グラフ補完のエッジ（§10.2 graph_context.edges[]・§4.1）。"""

    model_config = ConfigDict(extra="forbid")

    src: str
    dst: str
    relation: str


class GraphContext(BaseModel):
    """グラフ展開した文脈（§10.2 graph_context）。

    「同一取引先の別商材」「同一変動理由の他社事例」を depth=1 で補完する（§4.1・§10.4）。
    """

    model_config = ConfigDict(extra="forbid")

    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    summary_text: str = ""


class Citation(BaseModel):
    """引用元（§10.2 citations[]）。FR-08 の最終生成に根拠として渡される。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    # §10.3 では citations[].ref は単なる object。fixture は {table, pk} 形なので Ref で保持する。
    ref: Ref


class RetrieveResult(BaseModel):
    """KRE の検索結果（§10.2 / §10.3）。本体はこれを FR-03 表示・FR-08 生成入力に使う。"""

    model_config = ConfigDict(extra="forbid")

    hits: list[Hit] = Field(default_factory=list)
    graph_context: GraphContext = Field(default_factory=GraphContext)
    citations: list[Citation] = Field(default_factory=list)
    engine_version: str = ENGINE_VERSION
    config_version: str


# ==============================================================================
# IndexEvent（取込契約・§10.2）
# ==============================================================================
class IndexEvent(BaseModel):
    """本体 → KRE の取込イベント（§10.2）。

    本体は業務テーブルを書いた後にこのイベント（または再index要求）を発行する。
    索引とグラフの一貫性維持（整合 sync）は KRE 責務（§9.3）。
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    op: IndexOp
    # 既知集合は KNOWN_ENTITIES。将来の拡張（§10.2 の "..."）を許すため str のまま。
    entity: str
    pk: str
    # 本体テーブルからの再読込で足りる場合は payload 省略可。
    payload: Optional[dict] = None


# ==============================================================================
# EngineHealth（§10.2）
# ==============================================================================
class EngineHealth(BaseModel):
    """KRE の健全性（§10.2）。IndexEvent 発行後に doc_count / last_sync_at が更新される（§10.5）。"""

    model_config = ConfigDict(extra="forbid")

    index_ready: bool
    graph_ready: bool
    last_sync_at: Optional[datetime] = None
    doc_count: int = 0


# ==============================================================================
# RetrievalEngine Protocol（§10.1）
# ==============================================================================
@runtime_checkable
class RetrievalEngine(Protocol):
    """本体と KRE の唯一の結合面（§10.1）。

    本体はこの Protocol に対してコーディングし、実装（stub ⇄ 本実装）を DI で差し替える（§5）。
    """

    def retrieve(self, req: RetrieveRequest) -> RetrieveResult:
        """検索＋グラフ補完＋引用元供給を行い結果を返す。"""
        ...

    def index_upsert(self, ev: IndexEvent) -> None:
        """取込イベントを受けて索引・グラフの整合を更新する。"""
        ...

    def health(self) -> EngineHealth:
        """エンジンの健全性を返す。"""
        ...


# ==============================================================================
# RetrieveResult の正準 JSON Schema（§10.3 を逐語で保持）
# ==============================================================================
# jsonschema ライブラリ非依存で契約を明文化するため、設計書 §10.3 の JSON Schema を
# 正準アーティファクトとしてここに保持する。tests/kre 側の最小検証器で適合を検査する。
RETRIEVE_RESULT_JSON_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "RetrieveResult",
    "type": "object",
    "required": ["hits", "graph_context", "citations", "engine_version", "config_version"],
    "properties": {
        "hits": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "source", "score", "snippet", "ref"],
                "properties": {
                    "id": {"type": "string"},
                    "source": {"enum": ["case", "strategy", "result", "market", "spec", "supplier"]},
                    "score": {"type": "number"},
                    "snippet": {"type": "string"},
                    "ref": {
                        "type": "object",
                        "required": ["table", "pk"],
                        "properties": {"table": {"type": "string"}, "pk": {"type": "string"}},
                    },
                },
            },
        },
        "graph_context": {
            "type": "object",
            "required": ["nodes", "edges", "summary_text"],
            "properties": {
                "nodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "type", "label"],
                        "properties": {
                            "id": {"type": "string"},
                            "type": {"type": "string"},
                            "label": {"type": "string"},
                        },
                    },
                },
                "edges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["src", "dst", "relation"],
                        "properties": {
                            "src": {"type": "string"},
                            "dst": {"type": "string"},
                            "relation": {"type": "string"},
                        },
                    },
                },
                "summary_text": {"type": "string"},
            },
        },
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "label", "ref"],
                "properties": {
                    "id": {"type": "string"},
                    "label": {"type": "string"},
                    "ref": {"type": "object"},
                },
            },
        },
        "engine_version": {"type": "string"},
        "config_version": {"type": "string"},
    },
}


def retrieve_result_json_schema() -> dict:
    """RetrieveResult の正準 JSON Schema（§10.3）の deep copy を返す。

    呼び出し側が破壊的に変更しても定数を汚さないようコピーを返す。
    """
    return copy.deepcopy(RETRIEVE_RESULT_JSON_SCHEMA)
