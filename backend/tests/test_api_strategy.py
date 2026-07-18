"""test_api_strategy.py — 作戦シート AI 生成（FR-08）のテスト（AI 呼び出しはモック）。

Azure OpenAI クライアントを差し替え、実課金なしで生成→保存→取得→編集を検証する。
KRE は既定のスタブ（DI）。引用元は DB の過去決着から解決される。
"""

from __future__ import annotations

import json

import pytest


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def create(self, *, model, messages, response_format, temperature):  # noqa: ANN001
        system = messages[0]["content"]
        if '"scenario"' in system:
            return _FakeResponse(json.dumps({"scenario": "まず相場を根拠に目標¥585を提示し、着地¥600へ寄せる。"}))
        # points
        payload = {
            "points": [
                {"text": "直近相場¥585を根拠に目標¥585を起点に交渉する。", "citation_case_nos": ["No.123455-a"]},
                {"text": "前回決着を基準に急な値上げには整合を求める。", "citation_case_nos": ["No.123454-a"]},
                {"text": "年間数量を背景に長期契約で単価抑制を訴求する。", "citation_case_nos": []},
            ]
        }
        return _FakeResponse(json.dumps(payload, ensure_ascii=False))


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()


class _FakeClient:
    def __init__(self) -> None:
        self.chat = _FakeChat()


@pytest.fixture()
def fake_ai(monkeypatch: pytest.MonkeyPatch):
    """strategy_generator の AzureOpenAI クライアントをフェイクに差し替える。"""
    monkeypatch.setattr("app.llm.strategy_generator._get_client", lambda: _FakeClient())


def test_generate_strategy(api, fake_ai) -> None:
    """生成: ポイント3件＋シナリオ、引用元が DB の過去案件に解決される。"""
    res = api.client.post("/api/cases/No.123456-a/strategy/generate", headers=api.headers())
    assert res.status_code == 200
    body = res.json()
    assert len(body["points"]) == 3
    assert body["scenario"]
    # 1件目は No.123455-a（seed の完了案件）を引用
    cites = body["points"][0]["citations"]
    assert cites and cites[0]["caseNo"] == "No.123455-a"
    assert cites[0]["company"] == "丸紅畜産"


def test_strategy_citation_includes_handover_note(api, fake_ai) -> None:
    """作戦シートの引用スニペットにも次回への申し送りが「申し送り: …」で現れる（issue #6 Want）。"""
    res = api.client.post("/api/cases/No.123456-a/strategy/generate", headers=api.headers())
    assert res.status_code == 200
    # 1件目は No.123455-a を引用。seed の同案件は handover_note「次回は前倒しで数量提示を」を持つ。
    snippet = res.json()["points"][0]["citations"][0]["snippet"]
    assert "申し送り: 次回は前倒しで数量提示を" in snippet


def test_generate_then_get(api, fake_ai) -> None:
    """生成後、GET で保存済み下書きが取得できる。"""
    api.client.post("/api/cases/No.123456-a/strategy/generate", headers=api.headers())
    got = api.client.get("/api/cases/No.123456-a/strategy", headers=api.headers())
    assert got.status_code == 200
    body = got.json()
    assert body is not None
    assert len(body["points"]) == 3 and body["scenario"]


def test_get_before_generate_is_null(api) -> None:
    """未生成の（新規作成した）案件は null を返す。"""
    created = api.client.post(
        "/api/cases",
        headers=api.headers(),
        json={"supplierId": 1, "product": "冷凍エビ", "quotedPrice": 900, "targetPeriod": "2026Q4"},
    ).json()
    res = api.client.get(f"/api/cases/{created['caseNo']}/strategy", headers=api.headers())
    assert res.status_code == 200
    assert res.json() is None


def test_put_saves_edited_scenario(api, fake_ai) -> None:
    """編集した下書き（シナリオ）を保存できる。"""
    api.client.post("/api/cases/No.123456-a/strategy/generate", headers=api.headers())
    edited = {
        "points": [{"text": "編集後ポイント", "citations": []}],
        "scenario": "担当者が手直ししたシナリオ。",
    }
    res = api.client.put("/api/cases/No.123456-a/strategy", headers=api.headers(), json=edited)
    assert res.status_code == 200
    got = api.client.get("/api/cases/No.123456-a/strategy", headers=api.headers()).json()
    assert got["scenario"] == "担当者が手直ししたシナリオ。"
    assert len(got["points"]) == 1


def test_generate_404_for_unknown_case(api, fake_ai) -> None:
    res = api.client.post("/api/cases/No.NOPE/strategy/generate", headers=api.headers())
    assert res.status_code == 404
