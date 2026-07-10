"""loader.py — retrieval_config（§11）の型定義と読込。

``retrieval_config.yaml`` を Pydantic モデル ``RetrievalConfig`` に検証付きでロードする。
StubRetrievalEngine（stub.py）はこの config を受け取り、``search.top_k`` による件数制限や
``graph.enabled`` によるグラフ補完の有無を観測可能に反映する（§10.5 受け入れ条件(2)の実証）。

上書き受け口: ``load_retrieval_config(overrides=...)`` に dict を渡すと、ファイル値へ
浅くマージする（Key Vault / 環境変数からの上書きの受け皿・§11）。

設計正典: outputs/freeradicals-rfp/02_アーキテクチャ設計書_draft-v3.md §11
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field

# パッケージ同梱の既定 config ファイル（backend/kre/config/retrieval_config.yaml）。
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "retrieval_config.yaml"


class SearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hybrid_weight: float = 0.5
    top_k: int = Field(default=10, ge=1)
    min_score: float = 0.2


class GraphConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    depth: int = Field(default=1, ge=0)
    max_neighbors: int = Field(default=20, ge=0)
    node_types: list[str] = Field(
        default_factory=lambda: ["product_spec", "supplier", "case", "rate_change_reason", "origin"]
    )
    edge_types: list[str] = Field(
        default_factory=lambda: ["対象商材", "取引先", "主張変動理由", "認めた変動理由", "産地", "同一商材"]
    )


class EmbeddingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = "text-embedding-3-small"


class RerankConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False


class ScoringConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    freshness_decay: float = 0.1
    same_supplier_boost: float = 1.2
    same_reason_boost: float = 1.15


class SyncConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = "on_write"  # {on_write, scheduled}
    interval: Optional[str] = None  # scheduled 時のみ（例 "15m"）


class RetrievalConfig(BaseModel):
    """retrieval_config 全体（§11）。"""

    model_config = ConfigDict(extra="forbid")

    config_version: str = "retrieval-2026-07-09"
    search: SearchConfig = Field(default_factory=SearchConfig)
    graph: GraphConfig = Field(default_factory=GraphConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    rerank: RerankConfig = Field(default_factory=RerankConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)


def load_retrieval_config(
    path: Optional[Path] = None, *, overrides: Optional[dict] = None
) -> RetrievalConfig:
    """retrieval_config.yaml を読み込み ``RetrievalConfig`` を返す。

    Args:
        path: 読込先。None なら同梱の DEFAULT_CONFIG_PATH。
        overrides: トップレベルキーへの浅いマージ上書き（環境変数/Key Vault の受け口）。

    Returns:
        検証済みの RetrievalConfig。
    """
    src = path or DEFAULT_CONFIG_PATH
    with open(src, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if overrides:
        data = {**data, **overrides}
    return RetrievalConfig.model_validate(data)
