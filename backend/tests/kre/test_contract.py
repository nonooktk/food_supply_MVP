"""test_contract.py — KRE 契約（型・Protocol・JSON Schema）の検証（設計書 §10）。

- RetrievalEngine Protocol を StubRetrievalEngine が満たすこと。
- RetrieveQuery のバリデーション（いずれか1つ以上必須）。
- 最小 JSON Schema バリデータ自体が正しく機能すること（メタテスト）。
- fixture の result が §10.3 の JSON Schema に適合すること。
"""

from __future__ import annotations

import json

import pytest

from kre.contract import (
    RETRIEVE_RESULT_JSON_SCHEMA,
    Citation,
    EngineHealth,
    GraphContext,
    Hit,
    IndexEvent,
    Ref,
    RetrievalEngine,
    RetrieveQuery,
    RetrieveRequest,
    RetrieveResult,
    retrieve_result_json_schema,
)
from kre.stub import StubRetrievalEngine


def test_stub_satisfies_protocol(stub: StubRetrievalEngine) -> None:
    """StubRetrievalEngine が RetrievalEngine Protocol を満たすこと（§10.1・runtime_checkable）。"""
    assert isinstance(stub, RetrievalEngine)


def test_retrieve_query_requires_at_least_one() -> None:
    """空の RetrieveQuery は拒否されること（§10.2 いずれか1つ以上）。"""
    with pytest.raises(ValueError):
        RetrieveQuery()
    # いずれか1つあれば valid。
    assert RetrieveQuery(free_text="鶏もも肉").free_text == "鶏もも肉"
    assert RetrieveQuery(case_no="No.500023").case_no == "No.500023"
    assert RetrieveQuery(spec_id=305).spec_id == 305


def test_retrieve_request_defaults() -> None:
    """filters / options は未指定でも既定インスタンスが入ること。"""
    req = RetrieveRequest(tenant_id="t-frd", query=RetrieveQuery(free_text="x"))
    assert req.filters.infomart_code is None
    assert req.options.top_k is None


def test_json_schema_is_returned_as_copy() -> None:
    """retrieve_result_json_schema() は定数の deep copy を返し、破壊しても定数を汚さないこと。"""
    schema = retrieve_result_json_schema()
    schema["required"].append("__mutated__")
    assert "__mutated__" not in RETRIEVE_RESULT_JSON_SCHEMA["required"]


def test_mini_validator_meta(json_schema_errors, retrieve_result_schema) -> None:
    """最小 JSON Schema バリデータのメタテスト（正常/異常を正しく判定できること）。"""
    valid = RetrieveResult(config_version="c").model_dump(mode="json")
    assert json_schema_errors(valid, retrieve_result_schema) == []

    # 必須欠落（hits 無し）を検知できること。
    broken = valid.copy()
    del broken["hits"]
    errors = json_schema_errors(broken, retrieve_result_schema)
    assert any("hits" in e for e in errors)

    # enum 違反（source が不正）を検知できること。
    bad_enum = {
        "hits": [
            {
                "id": "t:case:1",
                "source": "INVALID",
                "score": 0.5,
                "snippet": "s",
                "ref": {"table": "t", "pk": "1"},
            }
        ],
        "graph_context": {"nodes": [], "edges": [], "summary_text": ""},
        "citations": [],
        "engine_version": "kre-0.1.0",
        "config_version": "c",
    }
    errors = json_schema_errors(bad_enum, retrieve_result_schema)
    assert any("enum" in e for e in errors)

    # score が数値でない（string）を検知できること。
    bad_score = json.loads(json.dumps(bad_enum))
    bad_score["hits"][0]["source"] = "case"
    bad_score["hits"][0]["score"] = "0.5"
    errors = json_schema_errors(bad_score, retrieve_result_schema)
    assert any("score" in e and "number" in e for e in errors)


def test_fixture_result_conforms_to_schema(
    main_envelope, other_envelope, json_schema_errors, retrieve_result_schema
) -> None:
    """両 fixture の result が §10.3 の JSON Schema に適合すること。"""
    for envelope in (main_envelope, other_envelope):
        errors = json_schema_errors(envelope["result"], retrieve_result_schema)
        assert errors == [], f"{envelope['tenant_id']}: {errors}"


def test_index_event_and_health_types() -> None:
    """IndexEvent / EngineHealth の基本構築が通ること（§10.2）。"""
    ev = IndexEvent(tenant_id="t-frd", op="upsert", entity="case", pk="No.500023")
    assert ev.op == "upsert"
    with pytest.raises(ValueError):
        IndexEvent(tenant_id="t-frd", op="invalid", entity="case", pk="x")

    health = EngineHealth(index_ready=True, graph_ready=True, doc_count=3)
    assert health.doc_count == 3
    assert health.last_sync_at is None


def test_contract_models_roundtrip_json() -> None:
    """契約モデルが JSON シリアライズ往復で不変であること（将来 HTTP 分離の前提・§9.4）。"""
    result = RetrieveResult(
        hits=[Hit(id="t-frd:case:1", source="case", score=0.9, snippet="s", ref=Ref(table="t", pk="1"))],
        graph_context=GraphContext(summary_text="x"),
        citations=[Citation(id="t-frd:case:1", label="l", ref=Ref(table="t", pk="1"))],
        config_version="retrieval-2026-07-09",
    )
    dumped = result.model_dump_json()
    restored = RetrieveResult.model_validate_json(dumped)
    assert restored == result
