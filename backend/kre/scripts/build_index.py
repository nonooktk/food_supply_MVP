"""build_index.py — AI Search インデックス構築＋DB→ドキュメント投入＋グラフ生成（設計 v3 §3・§4）。

PoC `scripts/build_ai_search_index.py` を流用し、入力を **JSON ファイル群から MySQL/SQLite の
業務テーブル（tenant_id 付き）** へ差し替える（設計 §3.2）。冪等投入（merge_or_upload）・バッチ・
Embedding 生成ロジックは踏襲する。インデックス名は `.env` の AZURE_SEARCH_INDEX_NAME
（negotiation-docs-v1）。あわせて GraphRAG 用のグラフ JSON（§4）もテナント別に生成・保存する。

使い方（backend/ から。事前に seed 済みであること）:
    # 投入せずドキュメント/グラフ件数のみ確認（Azure 非接続・課金なし）
    .venv/bin/python -m kre.scripts.build_index --dry-run
    # 実投入（Azure OpenAI 埋め込み＋AI Search 投入。課金は seed 件数分のみ）
    .venv/bin/python -m kre.scripts.build_index

設計正典: outputs/freeradicals-rfp/02_アーキテクチャ設計書_draft-v3.md §3・§4
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import models as m
from kre.graph.graph_search import (
    DEFAULT_GRAPH_DIR,
    build_graph_records,
    save_graph_records,
    spec_label,
)
from kre.retrieval.embeddings import EMBED_DIM

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_index")

VECTOR_PROFILE_NAME = "default-vector-profile"
HNSW_CONFIG_NAME = "default-hnsw"
SEMANTIC_CONFIG_NAME = "default-semantic"

_RC_PATTERN = re.compile(r"^RC-\d+$")


# ==============================================================================
# インデックススキーマ（§3.1）
# ==============================================================================
def build_index_schema():
    """negotiation-docs-v1 のインデックススキーマを定義する（設計 §3.1）。"""
    from azure.search.documents.indexes.models import (
        HnswAlgorithmConfiguration,
        HnswParameters,
        SearchableField,
        SearchField,
        SearchFieldDataType,
        SearchIndex,
        SemanticConfiguration,
        SemanticField,
        SemanticPrioritizedFields,
        SemanticSearch,
        SimpleField,
        VectorSearch,
        VectorSearchProfile,
    )

    fields = [
        # ドキュメントキー。論理ID(doc_id)を URL-safe Base64 符号化した値（AI Search のキー制約対応）。
        SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True),
        # 論理ID {tenant}:{type}:{pk}（§4.2・グラフと共有）。検索結果ではこちらを id として返す。
        SimpleField(name="doc_id", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=EMBED_DIM,
            vector_search_profile_name=VECTOR_PROFILE_NAME,
        ),
        SimpleField(name="source", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="name", type=SearchFieldDataType.String, filterable=True),
        # テナント境界の唯一の絞り込み軸（§3.2 で OData AND 強制）。
        SimpleField(name="tenant_id", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="infomart_code", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="supplier_id", type=SearchFieldDataType.Int32, filterable=True, facetable=True),
        SimpleField(name="spec_id", type=SearchFieldDataType.Int32, filterable=True),
        SimpleField(name="year_month", type=SearchFieldDataType.String, filterable=True),
        SearchField(
            name="reason_tags",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            searchable=True,
            filterable=True,
            facetable=True,
        ),
    ]

    vector_search = VectorSearch(
        algorithms=[
            HnswAlgorithmConfiguration(
                name=HNSW_CONFIG_NAME,
                parameters=HnswParameters(m=4, ef_construction=400, ef_search=500, metric="cosine"),
            )
        ],
        profiles=[
            VectorSearchProfile(
                name=VECTOR_PROFILE_NAME, algorithm_configuration_name=HNSW_CONFIG_NAME
            )
        ],
    )

    semantic_search = SemanticSearch(
        configurations=[
            SemanticConfiguration(
                name=SEMANTIC_CONFIG_NAME,
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="name"),
                    content_fields=[SemanticField(field_name="content")],
                    keywords_fields=[SemanticField(field_name="reason_tags")],
                ),
            )
        ]
    )

    return SearchIndex(
        name=get_settings().azure_search_index_name,
        fields=fields,
        vector_search=vector_search,
        semantic_search=semantic_search,
    )


# ==============================================================================
# DB → ドキュメント（自然文 content・§3.2）
# ==============================================================================
def _reason_names(session: Session) -> dict[str, str]:
    return {r.reason_id: r.reason_name for r in session.execute(select(m.RateChangeReason)).scalars()}


def _rc_readable(reasons: Optional[list], reason_names: dict[str, str]) -> tuple[list[str], list[str]]:
    """理由リストを (RC-xx のみのタグ, 表示名リスト) に分解する。"""
    tags: list[str] = []
    labels: list[str] = []
    for r in reasons or []:
        rid = str(r).strip()
        if _RC_PATTERN.match(rid):
            tags.append(rid)
            labels.append(reason_names.get(rid, rid))
        elif rid:
            labels.append(rid)  # 自由記述は表示のみ（タグにはしない）
    return tags, labels


def load_documents(session: Session, tenant_id: str) -> list[dict]:
    """1テナント分の negotiation_cases / results / market_rates を自然文ドキュメント化する。

    id 名前空間は AI Search / グラフ共有の ``{tenant}:{source}:{pk}``（§4.2）。
    """
    ns = tenant_id
    reason_names = _reason_names(session)

    product_name = {
        p.product_id: p.product_name
        for p in session.execute(select(m.Product).where(m.Product.tenant_id == ns)).scalars()
    }
    specs = {
        s.spec_id: s
        for s in session.execute(select(m.ProductSpec).where(m.ProductSpec.tenant_id == ns)).scalars()
    }
    suppliers = {
        s.supplier_id: s
        for s in session.execute(select(m.Supplier).where(m.Supplier.tenant_id == ns)).scalars()
    }

    def spec_text(spec_id: int) -> str:
        s = specs.get(spec_id)
        if s is None:
            return f"spec:{spec_id}"
        return spec_label(product_name.get(s.product_id), s.origin, s.storage_type)

    docs: list[dict] = []

    # --- 交渉案件 ---
    cases = {
        c.case_no: c
        for c in session.execute(
            select(m.NegotiationCase).where(m.NegotiationCase.tenant_id == ns)
        ).scalars()
    }
    for case in cases.values():
        spec = specs.get(case.spec_id)
        sup = suppliers.get(case.supplier_id)
        tags, labels = _rc_readable(case.claimed_reasons, reason_names)
        sup_name = sup.supplier_name if sup else ""
        content = (
            f"【交渉案件 {case.case_no}】{sup_name}／{spec_text(case.spec_id)} の"
            f"{case.case_type or '交渉'}（{case.period or ''}・状態: {case.status or '不明'}）。"
        )
        if case.current_price is not None and case.proposed_price is not None:
            content += f" 現行 {int(case.current_price)} 円/kg → 提示 {int(case.proposed_price)} 円/kg。"
        if labels:
            content += f" 主張理由: {'・'.join(labels)}。"
        if case.volume_kg_month:
            content += f" 数量 {case.volume_kg_month} kg/月。"
        if case.proposed_conditions:
            content += f" 条件: {case.proposed_conditions}。"
        docs.append(
            {
                "id": f"{ns}:case:{case.case_no}",
                "content": content,
                "source": "case",
                "name": f"{spec_text(case.spec_id)}／{sup_name}",
                "tenant_id": ns,
                "infomart_code": (spec.infomart_code if spec else None),
                "supplier_id": case.supplier_id,
                "spec_id": case.spec_id,
                "year_month": None,
                "reason_tags": tags,
            }
        )

    # --- 交渉結果（決着） ---
    for res in session.execute(
        select(m.NegotiationResult).where(m.NegotiationResult.tenant_id == ns)
    ).scalars():
        case = cases.get(res.case_no)
        tags, labels = _rc_readable(res.accepted_reasons, reason_names)
        content = f"【決着 {res.case_no}】"
        if res.final_price is not None:
            content += f"決着単価 {int(res.final_price)} 円/kg。"
        if res.achievement is not None:
            content += f" 目標達成度 {int(res.achievement)}%。"
        if labels:
            content += f" 認めた理由: {'・'.join(labels)}。"
        if res.result_tags:
            content += f" 決着タグ: {'・'.join(res.result_tags)}。"
        if res.staff_memo:
            content += f" 所感: {res.staff_memo}。"
        docs.append(
            {
                "id": f"{ns}:result:{res.result_id}",
                "content": content,
                "source": "result",
                "name": f"{res.case_no} 決着記録",
                "tenant_id": ns,
                "infomart_code": (specs.get(case.spec_id).infomart_code if case and specs.get(case.spec_id) else None),
                "supplier_id": (case.supplier_id if case else None),
                "spec_id": (case.spec_id if case else None),
                "year_month": None,
                "reason_tags": tags,
            }
        )

    # --- 相場 ---
    for rate in session.execute(
        select(m.MarketRate).where(m.MarketRate.tenant_id == ns)
    ).scalars():
        spec = specs.get(rate.spec_id)
        content = f"【相場】{spec_text(rate.spec_id)} の {rate.year_month} 相場"
        if rate.price_yen_kg is not None:
            content += f" {int(rate.price_yen_kg)} 円/kg"
        if rate.yoy_change is not None:
            content += f"（前年同月比 {float(rate.yoy_change):+.1f}%）"
        content += "。"
        if rate.source:
            content += f" 出典: {rate.source}。"
        docs.append(
            {
                "id": f"{ns}:market:{rate.rate_id}",
                "content": content,
                "source": "market",
                "name": f"{spec_text(rate.spec_id)} 相場 {rate.year_month}",
                "tenant_id": ns,
                "infomart_code": (spec.infomart_code if spec else None),
                "supplier_id": None,
                "spec_id": rate.spec_id,
                "year_month": rate.year_month,
                "reason_tags": [],
            }
        )

    return docs


def all_tenant_ids(session: Session) -> list[str]:
    return list(session.execute(select(m.Tenant.tenant_id)).scalars())


def to_search_documents(docs: list[dict]) -> list[dict]:
    """論理IDドキュメントを AI Search 投入形へ変換する。

    - ``doc_id`` = 論理ID ``{tenant}:{type}:{pk}``（グラフと共有・検索で返す値）。
    - ``id``（キー）= 論理IDを URL-safe Base64 符号化（AI Search のキー文字制約対応）。
    """
    from kre.retrieval.vector_store import encode_doc_key

    out: list[dict] = []
    for d in docs:
        logical = d["id"]
        out.append({**d, "doc_id": logical, "id": encode_doc_key(logical)})
    return out


# ==============================================================================
# Azure 投入
# ==============================================================================
def create_or_update_index(index_client, schema) -> None:
    index_name = get_settings().azure_search_index_name
    try:
        index_client.get_index(index_name)
        logger.info("既存インデックスを更新: %s", index_name)
        index_client.create_or_update_index(schema)
    except Exception:  # noqa: BLE001 - 未存在時は新規作成
        logger.info("新規インデックスを作成: %s", index_name)
        index_client.create_index(schema)


def embed_documents(documents: list[dict], *, client=None) -> list[dict]:
    from kre.retrieval.embeddings import embed_batch

    contents = [d["content"] for d in documents]
    logger.info("Embedding 生成開始: %d 件", len(contents))
    vectors = embed_batch(contents, batch_size=16, client=client)
    for d, v in zip(documents, vectors):
        d["content_vector"] = v
    logger.info("Embedding 生成完了")
    return documents


def upload_documents(search_client, documents: list[dict]) -> int:
    BATCH = 100
    total_ok = 0
    for i in range(0, len(documents), BATCH):
        batch = documents[i : i + BATCH]
        result = search_client.merge_or_upload_documents(documents=batch)
        ok = sum(1 for r in result if r.succeeded)
        total_ok += ok
        logger.info("投入 %d/%d（成功 %d/%d）", i + len(batch), len(documents), ok, len(batch))
    return total_ok


# ==============================================================================
# エントリポイント
# ==============================================================================
def main() -> int:
    parser = argparse.ArgumentParser(description="AI Search インデックス構築＋DB投入＋グラフ生成")
    parser.add_argument("--dry-run", action="store_true", help="Azure 非接続。件数・サンプルのみ表示")
    parser.add_argument("--tenant", default=None, help="対象テナント（省略時は全テナント）")
    parser.add_argument("--graph-dir", default=str(DEFAULT_GRAPH_DIR), help="グラフ JSON の保存先")
    parser.add_argument(
        "--graph-only",
        action="store_true",
        help="グラフ JSON のみ生成・保存し、AI Search へは投入しない"
        "（起動時のローカルグラフ再生成用。AI Search インデックスは既存を使う。埋め込み課金なし）",
    )
    args = parser.parse_args()

    from app.db.database import get_sessionmaker

    session = get_sessionmaker()()
    try:
        tenants = [args.tenant] if args.tenant else all_tenant_ids(session)
        if not tenants:
            logger.error("テナントが見つかりません（seed 済みですか？）。")
            return 1

        all_docs: list[dict] = []
        graph_dir = Path(args.graph_dir)
        for tid in tenants:
            docs = load_documents(session, tid)
            all_docs.extend(docs)
            # グラフ JSON を生成・保存（§4）。
            nodes, edges = build_graph_records(session, tid)
            path = save_graph_records(tid, nodes, edges, graph_dir)
            logger.info(
                "テナント %s: docs=%d, graph(nodes=%d, edges=%d) → %s",
                tid, len(docs), len(nodes), len(edges), path,
            )
    finally:
        session.close()

    logger.info("ドキュメント総数: %d", len(all_docs))

    if args.graph_only:
        # グラフ JSON はループ内で保存済み。AI Search 投入（埋め込み・アップロード）はスキップする。
        logger.info("--graph-only: グラフ JSON のみ生成しました（AI Search 投入はスキップ）。")
        return 0

    if args.dry_run:
        logger.info("--dry-run: Azure へは投入しません。サンプル1件を表示します。")
        if all_docs:
            sample = {k: v for k, v in all_docs[0].items() if k != "content_vector"}
            print(json.dumps(sample, ensure_ascii=False, indent=2))
        return 0

    settings = get_settings()
    if not settings.azure_search_endpoint or not settings.azure_search_api_key:
        logger.error("AZURE_SEARCH_ENDPOINT / AZURE_SEARCH_API_KEY が未設定です。")
        return 1
    if not settings.azure_openai_endpoint or not settings.azure_openai_api_key:
        logger.error("AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY が未設定です。")
        return 1

    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient
    from azure.search.documents.indexes import SearchIndexClient

    credential = AzureKeyCredential(settings.azure_search_api_key)
    index_client = SearchIndexClient(endpoint=settings.azure_search_endpoint, credential=credential)
    search_client = SearchClient(
        endpoint=settings.azure_search_endpoint,
        index_name=settings.azure_search_index_name,
        credential=credential,
    )

    schema = build_index_schema()
    create_or_update_index(index_client, schema)

    # 論理ID → AI Search キー（Base64）＋ doc_id 保持へ変換してから投入する。
    documents = embed_documents(to_search_documents(all_docs))
    ok = upload_documents(search_client, documents)
    logger.info("完了。投入成功 %d/%d 件。", ok, len(documents))
    return 0


if __name__ == "__main__":
    sys.exit(main())
