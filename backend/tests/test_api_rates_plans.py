"""test_api_rates_plans.py — 相場・自社計画エンドポイントのテスト。"""

from __future__ import annotations


def test_get_rate(api) -> None:
    """相場: 最新585 / 現行609 / 前年比0.064（3.20%→...→6.40%）/ 正規化12件。"""
    res = api.client.get("/api/cases/No.123456-a/rate", headers=api.headers())
    assert res.status_code == 200
    body = res.json()
    assert body["latestPrice"] == 585
    assert body["currentPrice"] == 609
    assert abs(body["yoyRate"] - 0.064) < 1e-9
    assert body["normalizedCount"] == 12


def test_get_plan(api) -> None:
    """自社計画: 2026Q3 の計画（595/18000/615）を返す。"""
    res = api.client.get("/api/cases/No.123456-a/plan", headers=api.headers())
    assert res.status_code == 200
    body = res.json()
    assert body["planPrice"] == 595
    assert body["monthlyVolume"] == 18000
    assert body["ceilingPrice"] == 615


def test_put_plan_upsert(api) -> None:
    """計画を更新すると次回取得に反映される。"""
    new_plan = {"targetCostRate": 32, "planPrice": 600, "monthlyVolume": 20000, "ceilingPrice": 620}
    res = api.client.put("/api/cases/No.123456-a/plan", headers=api.headers(), json=new_plan)
    assert res.status_code == 200
    got = api.client.get("/api/cases/No.123456-a/plan", headers=api.headers()).json()
    assert got["planPrice"] == 600
    assert got["monthlyVolume"] == 20000
    assert got["ceilingPrice"] == 620


def test_rate_404(api) -> None:
    res = api.client.get("/api/cases/No.NOPE/rate", headers=api.headers())
    assert res.status_code == 404
