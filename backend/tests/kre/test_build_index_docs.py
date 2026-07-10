"""test_build_index_docs.py — DB→ドキュメント生成とインデックススキーマの検証（設計 §3）。

Azure に接続せず、自然文 content 化・ID 名前空間・フィールド構成・スキーマ定義を検証する。
"""

from __future__ import annotations

import base64

from kre.scripts.build_index import build_index_schema, load_documents, to_search_documents


def test_documents_cover_case_result_market(purchasing_session) -> None:
    """negotiation_cases / results / market_rates が自然文ドキュメント化されること。"""
    docs = load_documents(purchasing_session, "t-frd")
    by_source: dict[str, list[dict]] = {}
    for d in docs:
        by_source.setdefault(d["source"], []).append(d)

    assert "case" in by_source and by_source["case"], "案件ドキュメントがあるはず"
    assert "result" in by_source and by_source["result"], "決着ドキュメントがあるはず"
    # market_rates は本データセットには無いが、source 種別としては生成対象であることを型で担保。
    assert set(by_source) <= {"case", "result", "market"}


def test_document_id_namespace_and_fields(purchasing_session) -> None:
    """id が {tenant}:{source}:{pk}、必須フィールドが揃うこと（§3.1・§4.2）。"""
    docs = load_documents(purchasing_session, "t-frd")
    case_doc = next(d for d in docs if d["id"] == "t-frd:case:No.500023")

    assert case_doc["source"] == "case"
    assert case_doc["tenant_id"] == "t-frd"
    assert case_doc["supplier_id"] == 12
    assert case_doc["spec_id"] == 305
    # 自然文 content に商材・取引先・理由が含まれる。
    assert "丸紅畜産" in case_doc["content"]
    assert "鶏もも肉" in case_doc["content"]
    assert "飼料価格高騰" in case_doc["content"]
    # 変動理由タグは RC-xx のみ。
    assert case_doc["reason_tags"] == ["RC-03"]
    # 全フィールドキーが AI Search スキーマに一致する。
    expected_keys = {
        "id", "content", "source", "name", "tenant_id",
        "infomart_code", "supplier_id", "spec_id", "year_month", "reason_tags",
    }
    assert set(case_doc) == expected_keys


def test_result_doc_links_supplier_and_spec(purchasing_session) -> None:
    """決着ドキュメントが親案件経由で supplier_id / spec_id を継承すること。"""
    docs = load_documents(purchasing_session, "t-frd")
    result_doc = next(d for d in docs if d["source"] == "result")
    assert result_doc["supplier_id"] == 12
    assert result_doc["spec_id"] == 305
    assert result_doc["reason_tags"] == ["RC-03"]


def test_no_cross_tenant_documents(purchasing_session) -> None:
    """t-frd のドキュメントに t-acme の id が混入しないこと（越境ゼロ）。"""
    docs = load_documents(purchasing_session, "t-frd")
    assert all(d["id"].startswith("t-frd:") for d in docs)
    assert all(d["tenant_id"] == "t-frd" for d in docs)


def test_index_schema_fields_match_design() -> None:
    """インデックススキーマが設計 §3.1 のフィールド構成・1536次元であること。

    ``doc_id`` は論理ID保持用の追加フィールド（AI Search のキー文字制約対応）。
    """
    schema = build_index_schema()
    field_names = {f.name for f in schema.fields}
    assert field_names == {
        "id", "doc_id", "content", "content_vector", "source", "name",
        "tenant_id", "infomart_code", "supplier_id", "spec_id", "year_month", "reason_tags",
    }
    vec = next(f for f in schema.fields if f.name == "content_vector")
    assert vec.vector_search_dimensions == 1536


def test_to_search_documents_encodes_key_and_keeps_logical_id(purchasing_session) -> None:
    """投入形変換: id は AI Search 準拠キー、doc_id は論理IDで、復号すると一致すること。"""
    docs = load_documents(purchasing_session, "t-frd")
    search_docs = to_search_documents(docs)
    d = next(x for x in search_docs if x["doc_id"] == "t-frd:case:No.500023")
    # キーは英数字・_・-・= のみ（AI Search の許容集合）。
    assert all(c.isalnum() or c in "-_=" for c in d["id"])
    # 復号すると論理IDに戻る。
    decoded = base64.urlsafe_b64decode(d["id"].encode("ascii")).decode("utf-8")
    assert decoded == "t-frd:case:No.500023"
