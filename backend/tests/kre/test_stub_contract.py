"""test_stub_contract.py — スタブが契約どおり振る舞うことの検証（設計書 §10.5 受け入れ条件）。

- (1) 契約テスト green: スタブ出力が JSON Schema 適合＆ fixture と一致。
- (2) retrieval_config 差し替えで検索挙動が観測可能に変化。
- (3) 代表クエリで『同一取引先の別商材』『同一変動理由の他社事例』がグラフ補完される。
- IndexEvent 発行後に health() の doc_count / last_sync_at が更新される。
"""

from __future__ import annotations

from kre.config.loader import GraphConfig, RetrievalConfig, SearchConfig
from kre.contract import IndexEvent, RetrieveOptions, RetrieveQuery, RetrieveRequest
from kre.stub import StubRetrievalEngine


def _req(tenant_id: str = "t-frd", **options) -> RetrieveRequest:
    return RetrieveRequest(
        tenant_id=tenant_id,
        query=RetrieveQuery(free_text="鶏もも肉 丸紅畜産 値上げ"),
        options=RetrieveOptions(**options),
    )


def test_stub_output_matches_fixture(stub, main_envelope) -> None:
    """受け入れ条件(1): 既定 config でのスタブ出力が fixture の result と完全一致すること。"""
    result = stub.retrieve(_req())
    assert result.model_dump(mode="json") == main_envelope["result"]


def test_stub_output_conforms_to_schema(stub, json_schema_errors, retrieve_result_schema) -> None:
    """受け入れ条件(1): スタブ出力が §10.3 の JSON Schema に適合すること。"""
    result = stub.retrieve(_req())
    errors = json_schema_errors(result.model_dump(mode="json"), retrieve_result_schema)
    assert errors == []


def test_graph_completion_present(stub) -> None:
    """受け入れ条件(3): 同一取引先の別商材・同一変動理由がグラフ補完に現れること。"""
    result = stub.retrieve(_req())
    labels = {n.label for n in result.graph_context.nodes}
    types = {n.type for n in result.graph_context.nodes}
    relations = {e.relation for e in result.graph_context.edges}

    # 同一取引先（丸紅畜産）の別商材（鶏むね肉）がノードにある。
    assert "鶏むね肉／ブラジル／チルド" in labels
    # 変動理由ノード（RC-03 飼料価格高騰）がある＝同一変動理由の展開軸。
    assert "rate_change_reason" in types
    # 『対象商材』『取引先』『主張変動理由』のエッジが展開されている（§4.1）。
    assert {"対象商材", "取引先", "主張変動理由"} <= relations
    # 他社事例は summary_text に要約されている。
    assert "他社" in result.graph_context.summary_text


def test_config_top_k_changes_behavior(main_envelope) -> None:
    """受け入れ条件(2): top_k を絞ると返却ヒット件数が観測可能に減ること。"""
    full = StubRetrievalEngine.from_fixtures().retrieve(_req())
    assert len(full.hits) == 2  # 既定 top_k=10 → fixture の2件そのまま

    narrowed_config = RetrievalConfig(search=SearchConfig(top_k=1))
    narrowed = StubRetrievalEngine.from_fixtures(config=narrowed_config).retrieve(_req())
    assert len(narrowed.hits) == 1  # top_k=1 で1件に制限
    assert narrowed.hits[0].id == full.hits[0].id  # 上位が残る


def test_config_graph_disabled_drops_graph() -> None:
    """受け入れ条件(2): graph.enabled=false でグラフ補完が落ちること。"""
    config = RetrievalConfig(graph=GraphConfig(enabled=False))
    result = StubRetrievalEngine.from_fixtures(config=config).retrieve(_req())
    assert result.graph_context.nodes == []
    assert result.graph_context.edges == []


def test_options_override_config_per_query() -> None:
    """§10.2/§11: options で単発上書き（top_k / include_graph）が効くこと。"""
    engine = StubRetrievalEngine.from_fixtures()
    r1 = engine.retrieve(_req(top_k=1))
    assert len(r1.hits) == 1

    r2 = engine.retrieve(_req(include_graph=False))
    assert r2.graph_context.nodes == []


def test_config_version_reflected_in_result() -> None:
    """§11: config_version が RetrieveResult に反映されること（再現性の担保）。"""
    config = RetrievalConfig(config_version="retrieval-TEST-9999")
    result = StubRetrievalEngine.from_fixtures(config=config).retrieve(_req())
    assert result.config_version == "retrieval-TEST-9999"


def test_index_upsert_updates_health() -> None:
    """§10.5: IndexEvent 発行後に doc_count / last_sync_at が更新されること。"""
    engine = StubRetrievalEngine.from_fixtures()
    before = engine.health()
    assert before.last_sync_at is None

    engine.index_upsert(IndexEvent(tenant_id="t-frd", op="upsert", entity="case", pk="No.500099"))
    after_upsert = engine.health()
    assert after_upsert.doc_count == before.doc_count + 1
    assert after_upsert.last_sync_at is not None

    engine.index_upsert(IndexEvent(tenant_id="t-frd", op="delete", entity="case", pk="No.500099"))
    after_delete = engine.health()
    assert after_delete.doc_count == before.doc_count


def test_unknown_tenant_returns_empty_result() -> None:
    """未登録テナントは空結果（越境より前に、そもそもデータを返さない）。"""
    engine = StubRetrievalEngine.from_fixtures()
    result = engine.retrieve(_req(tenant_id="t-unknown"))
    assert result.hits == []
    assert result.graph_context.nodes == []
    assert result.citations == []
