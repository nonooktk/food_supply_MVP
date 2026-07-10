"""vector_store.py — Azure AI Search クライアント（テナントフィルタ AND 強制）。

PoC `retrieval/vector_store.py`（ChromaDB→AI Search 書き換え版）を流用し、購買ドメインへ置換する。
BM25（全文）＋ベクトル（HNSW cosine）のハイブリッド検索を行う点は不変。

流用元との差分（設計 v3 §3.2・受け入れ条件(4)）:
- **テナント越境の物理遮断**: 全検索で ``tenant_id eq '<current_tenant>'`` を OData フィルタに
  **AND 強制**する。``tenant_id`` は必須引数であり、未指定・空文字は例外で拒否する
  （Deny by Default）。ユーザー指定フィルタは常にこのテナント句と AND で結合する。
- select フィールドを PoC の機密レベル系から購買ドメイン（§3.1）へ差し替える。
- クライアント／埋め込み関数を注入可能にし、テストでは Azure を呼ばずに検証できる。

設計正典: outputs/freeradicals-rfp/02_アーキテクチャ設計書_draft-v3.md §3
"""

from __future__ import annotations

import base64
import logging
from functools import lru_cache
from typing import Callable, List, Optional

from kre.retrieval.embeddings import embed_text

logger = logging.getLogger(__name__)

# AI Search から取得するフィールド（設計 §3.1）。
# ``doc_id`` は論理ID ``{tenant}:{type}:{pk}``（§4.2）。AI Search のドキュメントキー(``id``)は
# 使用可能文字が英数字・_・-・= に限られ ':'/'.' を含められないため、``id`` は doc_id を
# URL-safe Base64 符号化したキーとし、論理IDは ``doc_id`` フィールドで保持・返却する。
SELECT_FIELDS: tuple[str, ...] = (
    "doc_id",
    "content",
    "source",
    "name",
    "tenant_id",
    "infomart_code",
    "supplier_id",
    "spec_id",
    "year_month",
    "reason_tags",
)


def encode_doc_key(logical_id: str) -> str:
    """論理ID ``{tenant}:{type}:{pk}`` を AI Search 準拠のキーへ符号化する。

    URL-safe Base64（A-Za-z0-9-_ と = 埋め）は AI Search の許容キー文字集合に収まる。
    復号は不要（論理IDは ``doc_id`` フィールドに別途保持する）。
    """
    return base64.urlsafe_b64encode(logical_id.encode("utf-8")).decode("ascii")


class TenantScopeError(ValueError):
    """テナント未指定のまま検索しようとした場合の例外（越境防御・Deny by Default）。"""


def _odata_quote(value: str) -> str:
    """OData 文字列リテラル用にシングルクォートをエスケープ（'→''）する。"""
    return str(value).replace("'", "''")


def build_tenant_filter(tenant_id: str, filters: Optional[dict] = None) -> str:
    """``tenant_id eq '<t>'`` を先頭に AND 強制した OData フィルタ式を組み立てる（設計 §3.2）。

    Args:
        tenant_id: 検索対象テナント（唯一の源泉・必須）。空なら TenantScopeError。
        filters: 追加の絞り込み。以下のキーを解釈する（いずれも省略可）。
            - ``infomart_code``: str（等値）
            - ``supplier_id``: int（等値）
            - ``spec_id``: int（等値）
            - ``year_month_range``: [from, to]（``year_month`` の範囲・両端含む）

    Returns:
        例: ``tenant_id eq 't-xxxx' and supplier_id eq 12``
    """
    if not tenant_id:
        raise TenantScopeError("tenant_id が未指定です（未認証の検索は拒否・§9.3）。")

    # 常に先頭・AND 強制（設計 §3.2 の骨子）。
    clauses: List[str] = [f"tenant_id eq '{_odata_quote(tenant_id)}'"]
    filters = filters or {}

    infomart_code = filters.get("infomart_code")
    if infomart_code:
        clauses.append(f"infomart_code eq '{_odata_quote(infomart_code)}'")

    supplier_id = filters.get("supplier_id")
    if supplier_id is not None:
        clauses.append(f"supplier_id eq {int(supplier_id)}")

    spec_id = filters.get("spec_id")
    if spec_id is not None:
        clauses.append(f"spec_id eq {int(spec_id)}")

    ym_range = filters.get("year_month_range")
    if ym_range and len(ym_range) == 2 and ym_range[0] and ym_range[1]:
        lo, hi = _odata_quote(ym_range[0]), _odata_quote(ym_range[1])
        clauses.append(f"year_month ge '{lo}' and year_month le '{hi}'")

    return " and ".join(clauses)


@lru_cache(maxsize=1)
def _get_client():
    """SearchClient をシングルトンで返す（遅延生成）。"""
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient

    from app.config import get_settings

    settings = get_settings()
    return SearchClient(
        endpoint=settings.azure_search_endpoint,
        index_name=settings.azure_search_index_name,
        credential=AzureKeyCredential(settings.azure_search_api_key),
    )


def _vector_weight(hybrid_weight: Optional[float]) -> Optional[float]:
    """hybrid_weight（0..1・ベクトル寄与比）を VectorizedQuery.weight へ写像する。

    0.5 で均衡（weight=1.0）。0 に近いほどキーワード寄り、1 に近いほどベクトル寄り。
    """
    if hybrid_weight is None:
        return None
    hw = min(max(float(hybrid_weight), 0.01), 0.99)
    return round(hw / (1.0 - hw), 3)


def search(
    query: str,
    n: int = 5,
    *,
    tenant_id: str,
    filters: Optional[dict] = None,
    hybrid_weight: Optional[float] = None,
    client=None,
    embed_fn: Optional[Callable[[str], List[float]]] = None,
) -> List[dict]:
    """Azure AI Search ハイブリッド検索（全文 BM25 + ベクトル）。テナント AND 強制。

    Args:
        query: 検索クエリ文字列。
        n: 上位 N 件。
        tenant_id: 検索対象テナント（必須・唯一の源泉）。空なら TenantScopeError。
        filters: 追加絞り込み（build_tenant_filter が解釈するキー）。
        hybrid_weight: ベクトル寄与比（0..1・§11 search.hybrid_weight）。
        client: SearchClient 注入口（テスト用。None なら既定）。
        embed_fn: クエリ埋め込み関数注入口（テスト用。None なら embed_text）。

    Returns:
        list[dict]: 各ヒット {id, content, score, source, name, tenant_id,
        infomart_code, supplier_id, spec_id, year_month, reason_tags}。
    """
    odata_filter = build_tenant_filter(tenant_id, filters)  # 未指定テナントはここで拒否
    client = client or _get_client()
    embed_fn = embed_fn or embed_text

    from azure.search.documents.models import VectorizedQuery

    query_vector = embed_fn(query)
    vq_kwargs = dict(vector=query_vector, k_nearest_neighbors=n, fields="content_vector")
    weight = _vector_weight(hybrid_weight)
    if weight is not None:
        vq_kwargs["weight"] = weight
    vector_query = VectorizedQuery(**vq_kwargs)

    results = client.search(
        search_text=query,
        vector_queries=[vector_query],
        filter=odata_filter,
        top=n,
        select=list(SELECT_FIELDS),
    )

    items: List[dict] = []
    for r in results:
        items.append(
            {
                # 論理ID（doc_id）を返す。未設定時のみキー(id)へフォールバック。
                "id": r.get("doc_id") or r.get("id", ""),
                "content": r.get("content", ""),
                # @search.score は [0,1] 正規化されない生スコア。PoC 同様そのまま返す。
                "score": round(float(r.get("@search.score", 0.0)), 4),
                "source": r.get("source", ""),
                "name": r.get("name", ""),
                "tenant_id": r.get("tenant_id", ""),
                "infomart_code": r.get("infomart_code"),
                "supplier_id": r.get("supplier_id"),
                "spec_id": r.get("spec_id"),
                "year_month": r.get("year_month"),
                "reason_tags": r.get("reason_tags") or [],
            }
        )
    return items
