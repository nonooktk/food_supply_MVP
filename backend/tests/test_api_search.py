"""test_api_search.py — 過去経緯（KRE スタブ DI + DB 由来）のテスト。"""

from __future__ import annotations

from app.api import deps
from kre.contract import EngineHealth, RetrieveRequest, RetrieveResult


class _SpyEngine:
    """retrieve の呼び出しを記録するスパイ（KRE DI の検証用）。"""

    def __init__(self) -> None:
        self.calls: list[RetrieveRequest] = []

    def retrieve(self, req: RetrieveRequest) -> RetrieveResult:
        self.calls.append(req)
        return RetrieveResult(config_version="test")

    def index_upsert(self, ev) -> None:  # noqa: ANN001
        pass

    def health(self) -> EngineHealth:
        return EngineHealth(index_ready=True, graph_ready=True)


def test_past_cases_from_db(api) -> None:
    """同一スペックの過去4決着を実データ（決着単価）で返す。"""
    res = api.client.get("/api/cases/No.123456-a/past-cases", headers=api.headers())
    assert res.status_code == 200
    body = res.json()
    assert body["state"] == "ready"
    # spec 1 の完了案件4件（No.123452〜123455）
    assert len(body["items"]) == 4
    prices = sorted(it["settledPrice"] for it in body["items"])
    assert prices == [598, 605, 609, 612]
    # 同一スペックは直接一致（relation なし）
    assert all(it["relation"] is None for it in body["items"])
    # 引用元スニペットが付く
    assert all(it["citations"] for it in body["items"])


def test_kre_engine_is_called(api) -> None:
    """KRE エンジンが DI で呼ばれ、テナント/スペックが渡ること（契約経由）。"""
    spy = _SpyEngine()
    api.client.app.dependency_overrides[deps.get_retrieval_engine] = lambda: spy
    try:
        res = api.client.get("/api/cases/No.123456-a/past-cases", headers=api.headers())
        assert res.status_code == 200
    finally:
        del api.client.app.dependency_overrides[deps.get_retrieval_engine]

    assert len(spy.calls) == 1
    req = spy.calls[0]
    assert req.tenant_id == api.tenant_id
    assert req.query.spec_id == 1  # 鶏もも肉ブラジル産のスペック


def test_kre_failure_degrades_gracefully(api) -> None:
    """KRE が落ちても DB 由来の過去経緯は返る（部分エラー耐性）。"""

    class _Broken:
        def retrieve(self, req):  # noqa: ANN001
            raise RuntimeError("KRE down")

        def index_upsert(self, ev):  # noqa: ANN001
            pass

        def health(self):
            raise RuntimeError

    api.client.app.dependency_overrides[deps.get_retrieval_engine] = lambda: _Broken()
    try:
        res = api.client.get("/api/cases/No.123456-a/past-cases", headers=api.headers())
    finally:
        del api.client.app.dependency_overrides[deps.get_retrieval_engine]
    assert res.status_code == 200
    assert res.json()["state"] == "ready"
    assert len(res.json()["items"]) == 4


def test_past_cases_empty_for_new_case(api) -> None:
    """過去のない新規案件は empty 状態。"""
    created = api.client.post(
        "/api/cases",
        headers=api.headers(),
        json={"company": "初取引社", "product": "冷凍ホタテ", "quotedPrice": 1200, "targetPeriod": "2026Q4"},
    ).json()
    res = api.client.get(f"/api/cases/{created['caseNo']}/past-cases", headers=api.headers())
    assert res.status_code == 200
    assert res.json()["state"] == "empty"
