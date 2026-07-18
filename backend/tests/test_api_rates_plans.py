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


def test_post_manual_rate_upsert(api) -> None:
    body = {"yearMonth": "2026-07", "priceYenKg": 600, "source": "担当者確認"}
    res = api.client.post("/api/cases/No.123456-a/rate/manual", headers=api.headers(), json=body)
    assert res.status_code == 200
    saved = res.json()
    assert saved["latestPrice"] == 600
    assert saved["normalizedCount"] == 13
    assert saved["note"]

    got = api.client.get("/api/cases/No.123456-a/rate", headers=api.headers()).json()
    assert got["latestPrice"] == 600
    assert got["normalizedCount"] == 13


def test_post_manual_rate_same_month_update(api) -> None:
    body = {"yearMonth": "2026-06", "priceYenKg": 610, "source": "初回"}
    first = api.client.post("/api/cases/No.123456-a/rate/manual", headers=api.headers(), json=body)
    assert first.status_code == 200
    second = api.client.post(
        "/api/cases/No.123456-a/rate/manual",
        headers=api.headers(),
        json={"yearMonth": "2026-06", "priceYenKg": 620, "source": "更新"},
    )
    assert second.status_code == 200
    assert second.json()["latestPrice"] == 620
    assert second.json()["normalizedCount"] == 12


def test_post_manual_rate_validation(api) -> None:
    invalid_month = api.client.post(
        "/api/cases/No.123456-a/rate/manual",
        headers=api.headers(),
        json={"yearMonth": "2025-13", "priceYenKg": 600},
    )
    assert invalid_month.status_code == 422
    invalid_price = api.client.post(
        "/api/cases/No.123456-a/rate/manual",
        headers=api.headers(),
        json={"yearMonth": "2026-01", "priceYenKg": 0},
    )
    assert invalid_price.status_code == 422
    omitted_source = api.client.post(
        "/api/cases/No.123456-a/rate/manual",
        headers=api.headers(),
        json={"yearMonth": "2026-01", "priceYenKg": 600},
    )
    assert omitted_source.status_code == 200


def test_post_manual_rate_404(api) -> None:
    res = api.client.post(
        "/api/cases/No.NOPE/rate/manual",
        headers=api.headers(),
        json={"yearMonth": "2026-01", "priceYenKg": 600},
    )
    assert res.status_code == 404
