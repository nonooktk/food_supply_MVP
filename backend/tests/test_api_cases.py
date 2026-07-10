"""test_api_cases.py — 案件 CRUD・検索・状態管理・テナント分離のテスト。"""

from __future__ import annotations

import uuid

from app.db import models as m


def test_list_cases(api) -> None:
    """seed の5案件が一覧に出る（camelCase・表示名整形）。"""
    res = api.client.get("/api/cases", headers=api.headers())
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 5
    first = body["items"][0]
    assert set(first.keys()) >= {"caseNo", "company", "product", "status", "updatedAt", "assignee", "quotedPrice"}
    assert first["company"] == "丸紅畜産"


def test_filter_by_status(api) -> None:
    """status=done で完了案件のみに絞られる。"""
    res = api.client.get("/api/cases", headers=api.headers(), params={"status": "done"})
    items = res.json()["items"]
    assert items and all(it["status"] == "done" for it in items)


def test_keyword_search(api) -> None:
    """keyword で案件番号・取引先・商材・担当を横断検索する。"""
    res = api.client.get("/api/cases", headers=api.headers(), params={"keyword": "123456"})
    items = res.json()["items"]
    assert len(items) == 1 and items[0]["caseNo"] == "No.123456-a"


def test_get_case_detail(api) -> None:
    res = api.client.get("/api/cases/No.123456-a", headers=api.headers())
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "negotiating"
    assert body["quotedPrice"] == 620


def test_get_case_404(api) -> None:
    res = api.client.get("/api/cases/No.NOPE", headers=api.headers())
    assert res.status_code == 404
    assert res.headers["content-type"] == "application/problem+json"


def test_create_case_and_numbering(api) -> None:
    """作成すると NumberingService で No.500001〜 が採番される。"""
    res = api.client.post(
        "/api/cases",
        headers=api.headers(),
        json={"company": "新規商社", "product": "冷凍エビ", "quotedPrice": 900, "targetPeriod": "2026Q4"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["caseNo"] == "No.500001-a"
    assert body["status"] == "before"
    assert body["company"] == "新規商社"


def test_create_is_idempotent(api) -> None:
    """同一 Idempotency-Key の再送は同じ案件を返し、二重作成しない。"""
    headers = {**api.headers(), "Idempotency-Key": "abc-123"}
    payload = {"company": "冪等商事", "product": "鶏ささみ", "quotedPrice": 500, "targetPeriod": "2026Q4"}
    r1 = api.client.post("/api/cases", headers=headers, json=payload)
    r2 = api.client.post("/api/cases", headers=headers, json=payload)
    assert r1.json()["caseNo"] == r2.json()["caseNo"]
    # DB 上でも1件だけ
    with api.new_session() as s:
        n = len([c for c in s.query(m.NegotiationCase).all() if c.created_by == "tanaka"])
    assert n == 1


def test_status_transition(api) -> None:
    res = api.client.patch(
        "/api/cases/No.123456-a/status", headers=api.headers(), json={"status": "done"}
    )
    assert res.status_code == 200 and res.json()["status"] == "done"


def test_tenant_isolation(api) -> None:
    """別テナントを作り、そのヘッダーでは相手の案件が見えない（越境ゼロ）。"""
    other = str(uuid.uuid4())
    with api.new_session() as s:
        s.add(m.Tenant(tenant_id=other, tenant_name="別テナント"))
        s.commit()
    # 別テナントの一覧は空（seed 案件は元テナント所属）
    res = api.client.get("/api/cases", headers=api.headers(tenant_id=other))
    assert res.status_code == 200 and res.json()["total"] == 0
    # 別テナントから元テナントの案件詳細は 404
    res2 = api.client.get("/api/cases/No.123456-a", headers=api.headers(tenant_id=other))
    assert res2.status_code == 404
