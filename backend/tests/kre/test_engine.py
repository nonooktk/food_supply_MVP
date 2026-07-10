"""test_engine.py — AzureRetrievalEngine 本実装の検証（設計 §5・§10・§11）。

Azure（AI Search / OpenAI）を呼ばず、検索関数とグラフ供給を注入して契約準拠・config 反映・
グラフ補完・テナント越境ゼロを検証する。
"""

from __future__ import annotations

from typing import Optional

import pytest

from kre.config.loader import GraphConfig, RetrievalConfig, SearchConfig
from kre.contract import (
    RetrievalEngine,
    RetrieveOptions,
    RetrieveQuery,
    RetrieveRequest,
)
from kre.engine import AzureRetrievalEngine
from kre.graph.graph_search import PurchasingGraph


# ------------------------------------------------------------------------------
# テスト用の注入ダブル
# ------------------------------------------------------------------------------
class _InMemoryGraphProvider:
    """purchasing_session から構築した PurchasingGraph を返す供給者。"""

    def __init__(self, session, tenant_id: str) -> None:
        self._graphs = {tenant_id: PurchasingGraph.from_db(session, tenant_id)}

    def get(self, tenant_id: str):
        return self._graphs.get(tenant_id)


def _fake_search_factory(hits: list[dict]):
    """常に与えられた hits を返す検索関数（tenant_id 引数は受け取るが無視して越境検査に供する）。"""

    def _search(query, n, *, tenant_id: str, filters: Optional[dict] = None,
                hybrid_weight: Optional[float] = None, **_kw) -> list[dict]:
        return list(hits)

    return _search


def _frd_hits_with_poison() -> list[dict]:
    """t-frd の正規ヒット＋t-acme の汚染ヒット（越境検査用）。"""
    return [
        {"id": "t-frd:case:No.500023", "content": "鶏もも肉 丸紅畜産 値上げ", "score": 0.91, "source": "case",
         "name": "鶏もも肉／丸紅畜産", "tenant_id": "t-frd", "supplier_id": 12, "spec_id": 305,
         "infomart_code": None, "year_month": None, "reason_tags": ["RC-03"]},
        {"id": "t-frd:result:9021", "content": "決着 635 円/kg", "score": 0.84, "source": "result",
         "name": "No.500023 決着記録", "tenant_id": "t-frd", "supplier_id": 12, "spec_id": 305,
         "infomart_code": None, "year_month": None, "reason_tags": ["RC-03"]},
        # ↓ 越境の汚染データ（本来 OData で来ないが、二重防御を検査するため注入）。
        {"id": "t-acme:case:No.700088", "content": "他テナント混入", "score": 0.99, "source": "case",
         "name": "豚バラ肉／スターゼン", "tenant_id": "t-acme", "supplier_id": 44, "spec_id": 812,
         "infomart_code": None, "year_month": None, "reason_tags": ["RC-05"]},
    ]


def _engine(session, hits, config=None) -> AzureRetrievalEngine:
    return AzureRetrievalEngine(
        config=config,
        search_fn=_fake_search_factory(hits),
        graph_provider=_InMemoryGraphProvider(session, "t-frd"),
    )


def _req(**options) -> RetrieveRequest:
    return RetrieveRequest(
        tenant_id="t-frd",
        query=RetrieveQuery(free_text="鶏もも肉 丸紅畜産 値上げ"),
        options=RetrieveOptions(**options),
    )


# ------------------------------------------------------------------------------
# テスト
# ------------------------------------------------------------------------------
def test_engine_satisfies_protocol(purchasing_session) -> None:
    """本実装が RetrievalEngine Protocol を満たすこと（§10.1・stub と交換可能）。"""
    engine = _engine(purchasing_session, _frd_hits_with_poison())
    assert isinstance(engine, RetrievalEngine)


def test_result_conforms_to_schema(purchasing_session, json_schema_errors, retrieve_result_schema) -> None:
    """RetrieveResult が §10.3 の JSON Schema に適合すること（stub / 本実装で同一契約）。"""
    engine = _engine(purchasing_session, _frd_hits_with_poison())
    result = engine.retrieve(_req())
    errors = json_schema_errors(result.model_dump(mode="json"), retrieve_result_schema)
    assert errors == []


def test_hits_mapped_and_ref_resolved(purchasing_session) -> None:
    """hit が source→table を解決し、ref.pk が id から抽出されること。"""
    engine = _engine(purchasing_session, _frd_hits_with_poison())
    result = engine.retrieve(_req())
    case_hit = next(h for h in result.hits if h.source == "case")
    assert case_hit.ref.table == "negotiation_cases"
    assert case_hit.ref.pk == "No.500023"
    result_hit = next(h for h in result.hits if h.source == "result")
    assert result_hit.ref.table == "negotiation_results"
    assert result_hit.ref.pk == "9021"


def test_tenant_boundary_strips_foreign_hits(purchasing_session) -> None:
    """受け入れ条件(4): 汚染された t-acme ヒットが返却前に除去されること（二重防御の第2層）。"""
    engine = _engine(purchasing_session, _frd_hits_with_poison())
    result = engine.retrieve(_req())
    all_ids = [h.id for h in result.hits] + [c.id for c in result.citations]
    all_ids += [n.id for n in result.graph_context.nodes]
    assert all(i.startswith("t-frd:") for i in all_ids)
    assert not any("t-acme" in i for i in all_ids)


def test_graph_completion_present(purchasing_session) -> None:
    """受け入れ条件(3): グラフ補完で別商材(鶏むね肉)・他社事例(No.500099)が現れること。"""
    engine = _engine(purchasing_session, _frd_hits_with_poison())
    result = engine.retrieve(_req())
    node_ids = {n.id for n in result.graph_context.nodes}
    assert "t-frd:spec:306" in node_ids  # 同一取引先の別商材
    assert "t-frd:case:No.500099" in node_ids  # 同一変動理由の他社事例
    assert "別商材" in result.graph_context.summary_text


def test_citations_from_case_hits(purchasing_session) -> None:
    """case ヒットが引用元に変換されること（FR-08 の根拠供給）。"""
    engine = _engine(purchasing_session, _frd_hits_with_poison())
    result = engine.retrieve(_req())
    assert result.citations, "case ヒットから引用元が生成されるはず"
    assert all(c.id.startswith("t-frd:case:") for c in result.citations)


def test_config_top_k_limits_hits(purchasing_session) -> None:
    """受け入れ条件(2): top_k を絞ると返却ヒット件数が減ること（config 反映）。"""
    hits = _frd_hits_with_poison()
    full = _engine(purchasing_session, hits, RetrievalConfig(search=SearchConfig(top_k=10))).retrieve(_req())
    narrowed = _engine(purchasing_session, hits, RetrievalConfig(search=SearchConfig(top_k=1))).retrieve(_req())
    # full は t-acme 除去後 2 件、narrowed は top_k=1 で 1 件。
    assert len(full.hits) == 2
    assert len(narrowed.hits) == 1


def test_config_graph_disabled_drops_graph(purchasing_session) -> None:
    """受け入れ条件(2): graph.enabled=false でグラフ補完が落ちること。"""
    config = RetrievalConfig(graph=GraphConfig(enabled=False))
    result = _engine(purchasing_session, _frd_hits_with_poison(), config).retrieve(_req())
    assert result.graph_context.nodes == []
    assert result.graph_context.edges == []


def test_options_override_disables_graph_per_query(purchasing_session) -> None:
    """§10.2/§11: options.include_graph=false の単発上書きが効くこと。"""
    engine = _engine(purchasing_session, _frd_hits_with_poison())
    result = engine.retrieve(_req(include_graph=False))
    assert result.graph_context.nodes == []


def test_config_version_reflected(purchasing_session) -> None:
    """§11: config_version が RetrieveResult に反映されること（再現性）。"""
    config = RetrievalConfig(config_version="retrieval-TEST-42")
    result = _engine(purchasing_session, _frd_hits_with_poison(), config).retrieve(_req())
    assert result.config_version == "retrieval-TEST-42"


def test_unknown_source_hit_is_dropped(purchasing_session) -> None:
    """未知 source のヒットは契約違反混入を避けるため捨てられること。"""
    hits = [
        {"id": "t-frd:mystery:1", "content": "x", "score": 0.5, "source": "mystery",
         "name": "", "tenant_id": "t-frd", "supplier_id": None, "spec_id": None,
         "infomart_code": None, "year_month": None, "reason_tags": []},
        {"id": "t-frd:case:No.500023", "content": "鶏もも肉", "score": 0.9, "source": "case",
         "name": "鶏もも肉／丸紅畜産", "tenant_id": "t-frd", "supplier_id": 12, "spec_id": 305,
         "infomart_code": None, "year_month": None, "reason_tags": ["RC-03"]},
    ]
    engine = _engine(purchasing_session, hits)
    result = engine.retrieve(_req())
    assert all(h.source != "mystery" for h in result.hits)
    assert any(h.source == "case" for h in result.hits)


def test_index_upsert_updates_health(purchasing_session) -> None:
    """§10.5: IndexEvent 発行後に last_sync_at が更新されること（health 契約）。"""
    from kre.contract import IndexEvent

    engine = _engine(purchasing_session, _frd_hits_with_poison())
    assert engine.health().last_sync_at is None
    engine.index_upsert(IndexEvent(tenant_id="t-frd", op="upsert", entity="case", pk="No.500023"))
    assert engine.health().last_sync_at is not None
