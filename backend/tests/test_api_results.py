"""test_api_results.py — 結果記録 API（FR-11/12/13）と BR-10 書込→読取ループのテスト。"""

from __future__ import annotations

from app.db import models as m


def test_list_reasons(api) -> None:
    """変動理由マスタ（RC-01〜10）を direction 付きで返す。"""
    res = api.client.get("/api/reasons", headers=api.headers())
    assert res.status_code == 200
    tags = res.json()
    assert len(tags) == 10
    codes = {t["code"] for t in tags}
    assert "RC-01" in codes and "RC-10" in codes
    assert all(t["direction"] in ("up", "down", "both") for t in tags)


def test_save_result_computes_and_completes(api) -> None:
    """結果保存: 見積比・目標達成度をサーバー算出し、案件を完了に遷移する。"""
    payload = {
        "settledPrice": 602,
        "deliveryTiming": "2026/07〜09 月2回",
        "paymentTerms": "月末締め翌月末払い",
        "reasonCodes": ["RC-03", "RC-04"],
        "staffMemo": "数量コミットで着地付近に収めた。",
        "handoverNote": "次回は数量カードを早めに切る。",
    }
    res = api.client.post("/api/cases/No.123456-a/result", headers=api.headers(), json=payload)
    assert res.status_code == 201
    body = res.json()
    # 見積比 = (602-620)/620*100 = -2.9%（見積620より安く決着）
    assert body["quoteDiffPct"] == -2.9
    # 目標達成度 = (615-602)/(615-585)*100 = 43%
    assert body["achievementPct"] == 43.0
    assert body["settledPrice"] == 602
    assert body["reasonCodes"] == ["RC-03", "RC-04"]
    assert body["company"] == "丸紅畜産"

    # 案件が完了に遷移
    detail = api.client.get("/api/cases/No.123456-a", headers=api.headers()).json()
    assert detail["status"] == "done"


def test_get_result_roundtrip(api) -> None:
    """保存 → 取得で同じ内容が返る。未保存案件は null。"""
    # 未保存（No.123456-a は seed で結果なし）
    before = api.client.get("/api/cases/No.123456-a/result", headers=api.headers())
    assert before.status_code == 200 and before.json() is None

    api.client.post(
        "/api/cases/No.123456-a/result",
        headers=api.headers(),
        json={"settledPrice": 600, "deliveryTiming": "T", "paymentTerms": "P", "reasonCodes": ["RC-01"], "staffMemo": "n"},
    )
    got = api.client.get("/api/cases/No.123456-a/result", headers=api.headers()).json()
    assert got is not None
    assert got["settledPrice"] == 600 and got["staffMemo"] == "n"


def test_memo_handover_separated(api) -> None:
    """所感→staff_memo、申し送り→handover_note に別々に保存され、再取得で別々に復元される（issue #6）。"""
    payload = {
        "settledPrice": 600,
        "deliveryTiming": "",
        "paymentTerms": "",
        "reasonCodes": ["RC-01"],
        "staffMemo": "今回の所感メモ",
        "handoverNote": "次回への申し送りメモ",
    }
    saved = api.client.post(
        "/api/cases/No.123456-a/result", headers=api.headers(), json=payload
    ).json()
    assert saved["staffMemo"] == "今回の所感メモ"
    assert saved["handoverNote"] == "次回への申し送りメモ"

    # 再取得（GET）でも両者が別々に復元される。
    got = api.client.get("/api/cases/No.123456-a/result", headers=api.headers()).json()
    assert got["staffMemo"] == "今回の所感メモ"
    assert got["handoverNote"] == "次回への申し送りメモ"

    # DB カラムにも別々に永続化されている。
    with api.new_session() as s:
        row = [r for r in s.query(m.NegotiationResult).all() if r.case_no == "No.123456-a"][0]
        assert row.staff_memo == "今回の所感メモ"
        assert row.handover_note == "次回への申し送りメモ"


def test_handover_note_defaults_empty(api) -> None:
    """申し送り未入力（省略）でも保存でき、空文字で復元される（後方互換）。"""
    payload = {
        "settledPrice": 600,
        "deliveryTiming": "",
        "paymentTerms": "",
        "reasonCodes": ["RC-01"],
        "staffMemo": "所感のみ",
    }
    saved = api.client.post(
        "/api/cases/No.123456-a/result", headers=api.headers(), json=payload
    ).json()
    assert saved["staffMemo"] == "所感のみ"
    assert saved["handoverNote"] == ""


def test_reason_code_validation(api) -> None:
    """RC マスタにない理由コードは 422。"""
    res = api.client.post(
        "/api/cases/No.123456-a/result",
        headers=api.headers(),
        json={"settledPrice": 600, "deliveryTiming": "", "paymentTerms": "", "reasonCodes": ["RC-99"], "staffMemo": ""},
    )
    assert res.status_code == 422
    assert res.headers["content-type"] == "application/problem+json"


def test_result_idempotent(api) -> None:
    """同一 Idempotency-Key の再送は二重記録しない。"""
    headers = {**api.headers(), "Idempotency-Key": "res-1"}
    payload = {"settledPrice": 601, "deliveryTiming": "", "paymentTerms": "", "reasonCodes": ["RC-02"], "staffMemo": ""}
    r1 = api.client.post("/api/cases/No.123456-a/result", headers=headers, json=payload)
    r2 = api.client.post("/api/cases/No.123456-a/result", headers=headers, json=payload)
    assert r1.json() == r2.json()
    with api.new_session() as s:
        n = len([r for r in s.query(m.NegotiationResult).all() if r.case_no == "No.123456-a"])
    assert n == 1


def test_result_404(api) -> None:
    res = api.client.post(
        "/api/cases/No.NOPE/result",
        headers=api.headers(),
        json={"settledPrice": 1, "deliveryTiming": "", "paymentTerms": "", "reasonCodes": [], "staffMemo": ""},
    )
    assert res.status_code == 404


def test_br10_write_read_loop(api) -> None:
    """BR-10 実証: 記録した結果が同一商材の新規案件の過去経緯（DB 由来経路）に現れる。"""
    # ① 案件Aを作成（新商材キー）
    case_a = api.client.post(
        "/api/cases",
        headers=api.headers(),
        json={"supplierId": 1, "product": "国産豚ロース", "quotedPrice": 900, "targetPeriod": "2026Q3"},
    ).json()["caseNo"]
    # ⑤ 案件Aに結果を記録（決着 880）
    api.client.post(
        f"/api/cases/{case_a}/result",
        headers=api.headers(),
        json={"settledPrice": 880, "deliveryTiming": "2026/07", "paymentTerms": "月末", "reasonCodes": ["RC-05"], "staffMemo": "数量拡大で減額", "handoverNote": "数量カードは有効"},
    )
    # ① 同一商材で案件Bを作成（A と同じ spec を共有）
    case_b = api.client.post(
        "/api/cases",
        headers=api.headers(),
        json={"supplierId": 1, "product": "国産豚ロース", "quotedPrice": 910, "targetPeriod": "2026Q4"},
    ).json()["caseNo"]
    # ② 案件Bの過去経緯に A の決着が現れる（DB 由来経路・即時反映）
    past = api.client.get(f"/api/cases/{case_b}/past-cases", headers=api.headers()).json()
    assert past["state"] == "ready"
    hit = [p for p in past["items"] if p["caseNo"] == case_a]
    assert hit, "記録した結果が新規案件の過去経緯に現れない（BR-10 ループ未成立）"
    assert hit[0]["settledPrice"] == 880
    assert hit[0]["relation"] is None  # 同一スペック=直接一致
