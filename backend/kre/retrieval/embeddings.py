"""embeddings.py — Azure OpenAI Embeddings ラッパ（設計 v3 §3・§11）。

PoC `retrieval/embeddings.py` を流用。`text-embedding-3-small`（1536 次元）を Azure OpenAI
経由で生成し、AI Search のベクトル検索とインデックス投入の双方で共有する。

流用元との差分:
- 設定参照を PoC の ``from config import settings`` から本リポジトリの
  ``from app.config import get_settings`` へ変更（config は本体 app 側に集約されている）。
- クライアント／埋め込み関数はテスト・課金配慮のため注入可能にする（``client`` 引数）。
  既定では Azure OpenAI クライアントを遅延生成し、テストでは注入で置き換えて Azure を呼ばない。

設計正典: outputs/freeradicals-rfp/02_アーキテクチャ設計書_draft-v3.md §3・§11
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import List, Optional

logger = logging.getLogger(__name__)

# text-embedding-3-small の次元数（設計 §3.1 / §11・PoC と同一）。
EMBED_DIM = 1536


@lru_cache(maxsize=1)
def _get_client():
    """AzureOpenAI クライアントをシングルトンで返す（遅延生成）。

    import 時に Azure 設定を要求しないよう、関数内で遅延 import・遅延生成する。
    未接続環境（スタブ利用時）でも本モジュールの import 自体は失敗させない。
    """
    from openai import AzureOpenAI

    from app.config import get_settings

    settings = get_settings()
    return AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )


def _deployment() -> str:
    """埋め込みデプロイ名（.env の AZURE_OPENAI_EMBED_DEPLOYMENT）。"""
    from app.config import get_settings

    return get_settings().azure_openai_embed_deployment


def embed_text(text: str, *, client=None) -> List[float]:
    """単一テキストの Embedding ベクトルを返す（1536 次元）。

    Args:
        text: 埋め込み対象テキスト。
        client: テスト・再利用のための Azure OpenAI クライアント注入口（None なら既定）。
    """
    client = client or _get_client()
    response = client.embeddings.create(model=_deployment(), input=[text])
    return response.data[0].embedding


def embed_batch(
    texts: List[str], batch_size: int = 16, *, client: Optional[object] = None
) -> List[List[float]]:
    """複数テキストをバッチで Embedding 化する。

    Azure OpenAI の batch 上限を考慮して ``batch_size`` 単位に分割する。課金は入力トークン量に
    比例するため、投入対象（seed 件数分）に限って呼び出す運用とする（設計 §11・課金配慮）。
    """
    client = client or _get_client()
    all_vectors: List[List[float]] = []
    deployment = _deployment()
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = client.embeddings.create(model=deployment, input=batch)
        all_vectors.extend([d.embedding for d in response.data])
        logger.debug("Embedded %d/%d texts", i + len(batch), len(texts))
    return all_vectors
