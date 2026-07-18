"""test_api_three_lines.py — 3ライン算出・手修正保存エンドポイントのテスト。"""

from __future__ import annotations


def _by_type(lines: list[dict]) -> dict[str, dict]:
    return {ln["type"]: ln for ln in lines}


def test_get_reproduces_rfp_demo(api) -> None:
    """seed の作戦シートを重ね、目標585 / 着地600(手修正) / 撤退615 を返す。"""
    res = api.client.get("/api/cases/No.123456-a/three-lines", headers=api.headers())
    assert res.status_code == 200
    body = res.json()
    assert body["ready"] is True
    lines = _by_type(body["lines"])
    assert lines["target"]["value"] == 585 and lines["target"]["isEdited"] is False
    assert lines["landing"]["value"] == 600 and lines["landing"]["isEdited"] is True
    assert lines["landing"]["autoValue"] == 599  # 自動算出値（四捨五入で 598.5→599）
    assert lines["walkaway"]["value"] == 615 and lines["walkaway"]["isEdited"] is False
    # 影響額（対計画）
    assert body["impact"]["targetYen"] == (595 - 585) * 216000


def test_put_manual_edit_persists(api) -> None:
    """手修正（着地を610・理由付き）を保存すると再取得で反映される。"""
    payload = {
        "lines": [
            {"type": "target", "value": 585, "autoValue": 585, "isEdited": False},
            {"type": "landing", "value": 610, "autoValue": 598, "isEdited": True, "editReason": "供給逼迫"},
            {"type": "walkaway", "value": 615, "autoValue": 615, "isEdited": False},
        ]
    }
    res = api.client.put("/api/cases/No.123456-a/three-lines", headers=api.headers(), json=payload)
    assert res.status_code == 200
    lines = _by_type(res.json()["lines"])
    assert lines["landing"]["value"] == 610 and lines["landing"]["isEdited"] is True
    assert "供給逼迫" in (lines["landing"]["editReason"] or "")

    # 再取得でも保持される
    again = _by_type(api.client.get("/api/cases/No.123456-a/three-lines", headers=api.headers()).json()["lines"])
    assert again["landing"]["value"] == 610


def test_put_reset_to_auto(api) -> None:
    """全ライン未修正で保存すると自動算出値へ戻る（凍結しない）。"""
    payload = {
        "lines": [
            {"type": "target", "value": 585, "autoValue": 585, "isEdited": False},
            {"type": "landing", "value": 598, "autoValue": 598, "isEdited": False},
            {"type": "walkaway", "value": 615, "autoValue": 615, "isEdited": False},
        ]
    }
    api.client.put("/api/cases/No.123456-a/three-lines", headers=api.headers(), json=payload)
    lines = _by_type(api.client.get("/api/cases/No.123456-a/three-lines", headers=api.headers()).json()["lines"])
    assert all(ln["isEdited"] is False for ln in lines.values())
    assert lines["landing"]["value"] == lines["landing"]["autoValue"]


def test_not_ready_without_plan(api) -> None:
    """自社計画が無い（新規作成した）案件は ready=false。"""
    created = api.client.post(
        "/api/cases",
        headers=api.headers(),
        json={"supplierId": 1, "product": "冷凍イカ", "quotedPrice": 800, "targetPeriod": "2026Q4"},
    ).json()
    res = api.client.get(f"/api/cases/{created['caseNo']}/three-lines", headers=api.headers())
    assert res.status_code == 200
    assert res.json()["ready"] is False
    assert res.json()["lines"] == []
