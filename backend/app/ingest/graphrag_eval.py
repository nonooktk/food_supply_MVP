"""graphrag_eval.py — GraphRAG(KRE)評価用ダミーデータ30案件の取込。

データ源: `app/ingest/data/graphrag_eval_v1.json`
（`04_GraphRAG_解定義_評価用ダミーデータ_v1.xlsx` を事前変換したもの。seed.py と同じく
ランタイムに openpyxl 依存を持ち込まない）。

取込の設計:
1. 取引先・商材は **名前で名寄せ**（既存マスタに一致すれば再利用、無ければ新規採番）。
2. スペックは V13_品質規格 `産地/部位/等級/保存` を分解し、完全一致で名寄せ。
3. 各案件 GR-xxx は「交渉前」の値上げ要請案件として登録。
4. **過去決着1〜4 は「完了」した過去案件（GR-xxx-P1〜P4）＋決着記録として登録**する。
   これにより本体 API の過去経緯（/past-cases・repo.related_past_results）に自動で現れ、
   GraphRAG の評価入力（関連事実の収集・提示）が実データで再現できる。
5. 相場は (spec, 相場年月) 単位で1件投入（重複時は先勝ち）。
6. **期待解（正解表）は DB に入れない**（アプリへの正解混入を防ぐ。JSON 内 `expected` に保管）。

再実行可能（冪等）: data_origin / import_batch_id / note のマーカーで自分が投入した行だけを
削除してから入れ直す。名寄せで再利用した既存マスタには触れない。

実行例（backend/ から）:
    python -m app.ingest.graphrag_eval
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import models as m
from app.ingest.seed import _to_decimal, _to_int

DATA_PATH = Path(__file__).resolve().parent / "data" / "graphrag_eval_v1.json"

# 自分が投入した行を見分けるマーカー（冪等な再実行のため）
ORIGIN = "GraphRAG評価v1"
BATCH_ID = "graphrag-eval-v1"

# 過去決着1〜4 を割り当てる過去の四半期と決着日（古い順）
PAST_PERIODS = [
    ("2025Q1", date(2025, 2, 15)),
    ("2025Q2", date(2025, 5, 15)),
    ("2025Q3", date(2025, 8, 15)),
    ("2025Q4", date(2025, 11, 15)),
]


def _pct(value) -> Decimal | None:
    """`0.3` / `0.035` のような小数率を既存データの流儀（30 / 3.5 のパーセント値）へ揃える。"""
    d = _to_decimal(value)
    if d is None:
        return None
    return d * 100 if abs(d) < 1 else d


def _quarter(ym: str) -> str:
    """`2026-01` → `2026Q1`"""
    y, mo = ym.split("-")
    return f"{y}Q{(int(mo) - 1) // 3 + 1}"


def _split_spec(spec_str: str) -> tuple[str | None, str | None, str | None, str | None]:
    """`ブラジル産/もも/標準/冷凍` → (origin, part, grade, storage_type)"""
    parts = [p.strip() or None for p in str(spec_str).split("/")]
    parts += [None] * (4 - len(parts))
    return parts[0], parts[1], parts[2], parts[3]


def _cleanup(session: Session, tenant_id: str) -> None:
    """過去の投入分（マーカー付きの行）だけを削除する。名寄せ済みマスタは残す。"""
    case_nos = session.scalars(
        select(m.NegotiationCase.case_no).where(
            m.NegotiationCase.tenant_id == tenant_id,
            m.NegotiationCase.data_origin == ORIGIN,
        )
    ).all()
    if case_nos:
        session.execute(
            delete(m.NegotiationResult).where(
                m.NegotiationResult.tenant_id == tenant_id,
                m.NegotiationResult.case_no.in_(case_nos),
            )
        )
        session.execute(
            delete(m.NegotiationCase).where(
                m.NegotiationCase.tenant_id == tenant_id,
                m.NegotiationCase.case_no.in_(case_nos),
            )
        )
    session.execute(
        delete(m.MarketRate).where(
            m.MarketRate.tenant_id == tenant_id, m.MarketRate.import_batch_id == BATCH_ID
        )
    )
    session.execute(
        delete(m.CompanyPlan).where(
            m.CompanyPlan.tenant_id == tenant_id, m.CompanyPlan.note == ORIGIN
        )
    )
    session.flush()


def _next_id(session: Session, model, id_col) -> int:
    """テナント横断の最大ID+1（デモ用途の単純採番）。"""
    current = session.scalar(select(id_col).order_by(id_col.desc()).limit(1))
    return (current or 0) + 1


def import_all(session: Session) -> dict:
    """JSON を読み、評価用30案件＋過去決着120件＋関連マスタを投入する。"""
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    inputs: list[dict] = payload["inputs"]

    tenant_id = session.scalar(select(m.Tenant.tenant_id).order_by(m.Tenant.created_at))
    if tenant_id is None:
        raise RuntimeError("テナントが存在しません。先に `python -m app.ingest.seed` を実行してください。")

    _cleanup(session, tenant_id)

    # 変動理由の名寄せマップ（理由名 → RC-xx。非一致は原文のまま）
    name2id = {
        r.reason_name: r.reason_id for r in session.scalars(select(m.RateChangeReason)).all()
    }

    counts = {"suppliers_new": 0, "products_new": 0, "specs_new": 0, "plans": 0,
              "market_rates": 0, "cases": 0, "past_cases": 0, "results": 0}

    # ---- 1. 取引先・商材の名寄せ ----
    suppliers = {s.supplier_name: s for s in session.scalars(
        select(m.Supplier).where(m.Supplier.tenant_id == tenant_id)).all()}
    products = {p.product_name: p for p in session.scalars(
        select(m.Product).where(m.Product.tenant_id == tenant_id)).all()}

    def ensure_supplier(name: str) -> m.Supplier:
        if name not in suppliers:
            obj = m.Supplier(
                supplier_id=_next_id(session, m.Supplier, m.Supplier.supplier_id),
                tenant_id=tenant_id, supplier_name=name, supplier_memo=ORIGIN,
            )
            session.add(obj)
            session.flush()
            suppliers[name] = obj
            counts["suppliers_new"] += 1
        return suppliers[name]

    def ensure_product(name: str) -> m.Product:
        if name not in products:
            obj = m.Product(
                product_id=_next_id(session, m.Product, m.Product.product_id),
                tenant_id=tenant_id, product_name=name,
                category="卵" if "卵" in name else "食肉", unit="kg",
            )
            session.add(obj)
            session.flush()
            products[name] = obj
            counts["products_new"] += 1
        return products[name]

    # ---- 2. スペックの名寄せ ----
    specs: dict[tuple, m.ProductSpec] = {}
    for sp in session.scalars(select(m.ProductSpec).where(m.ProductSpec.tenant_id == tenant_id)).all():
        specs[(sp.product_id, sp.origin or None, sp.part or None, sp.grade or None,
               sp.storage_type or None)] = sp

    def ensure_spec(product: m.Product, spec_str: str) -> m.ProductSpec:
        origin, part, grade, storage = _split_spec(spec_str)
        key = (product.product_id, origin, part, grade, storage)
        if key not in specs:
            obj = m.ProductSpec(
                spec_id=_next_id(session, m.ProductSpec, m.ProductSpec.spec_id),
                tenant_id=tenant_id, product_id=product.product_id,
                origin=origin, part=part, grade=grade, storage_type=storage,
                spec_memo=ORIGIN,
            )
            session.add(obj)
            session.flush()
            specs[key] = obj
            counts["specs_new"] += 1
        return specs[key]

    # ---- 3. 案件・計画・相場・過去決着 ----
    seen_plan: set[tuple[int, str]] = set()
    seen_rate: set[tuple[int, str]] = set()

    for row in inputs:
        case_no = row["case_id"]
        supplier = ensure_supplier(row["取引先"])
        product = ensure_product(row["商材"])
        spec = ensure_spec(product, row["V13_品質規格"] or row["spec"])
        ym = row["相場年月"]                      # 例: 2026-01
        period = _quarter(ym)                     # 例: 2026Q1
        annual = _to_int(row["V11_年間数量kg"])
        monthly = round(annual / 12) if annual else None
        reason = (row["V3_主張理由"] or "").strip()

        # 自社計画（spec × period で1件）
        if (spec.spec_id, period) not in seen_plan:
            session.add(m.CompanyPlan(
                plan_id=_next_id(session, m.CompanyPlan, m.CompanyPlan.plan_id),
                tenant_id=tenant_id, spec_id=spec.spec_id, period=period,
                target_cost_rate=_pct(row["V9_目標原価率"]),
                planned_price=_to_decimal(row["V8_計画単価"]),
                volume_kg_month=monthly, annual_volume_kg=annual,
                max_acceptable_price=_to_decimal(row["V10_許容上限"]),
                note=ORIGIN,
            ))
            session.flush()
            seen_plan.add((spec.spec_id, period))
            counts["plans"] += 1

        # 相場（spec × 年月 で1件・先勝ち）
        if (spec.spec_id, ym) not in seen_rate:
            session.add(m.MarketRate(
                tenant_id=tenant_id, spec_id=spec.spec_id, year_month=ym,
                price_yen_kg=_to_decimal(row["V5_相場"]),
                yoy_change=_pct(row["相場前年比"]),
                source=row["相場出典"], input_method="手入力",
                import_batch_id=BATCH_ID,
            ))
            seen_rate.add((spec.spec_id, ym))
            counts["market_rates"] += 1

        # 本体案件（交渉前・値上げ要請）
        session.add(m.NegotiationCase(
            tenant_id=tenant_id, case_no=case_no,
            supplier_id=supplier.supplier_id, spec_id=spec.spec_id,
            period=period, case_type="値上げ要請", status="交渉前",
            current_price=_to_decimal(row["V2_現行単価"]),
            proposed_price=_to_decimal(row["V1_提示価格"]),
            volume_kg_month=monthly, annual_volume_kg=annual,
            proposed_conditions=row["V4_提示条件"],
            claimed_reasons=[name2id.get(reason, reason)] if reason else [],
            created_by="田中", data_origin=ORIGIN,
        ))
        counts["cases"] += 1

        # 過去決着1〜4 → 完了済み過去案件＋決着記録（古い順）
        for i, (p_period, p_date) in enumerate(PAST_PERIODS, start=1):
            price = _to_decimal(row.get(f"過去決着{i}"))
            if price is None:
                continue
            p_case_no = f"{case_no}-P{i}"
            session.add(m.NegotiationCase(
                tenant_id=tenant_id, case_no=p_case_no,
                supplier_id=supplier.supplier_id, spec_id=spec.spec_id,
                period=p_period, case_type="値上げ要請", status="完了",
                volume_kg_month=monthly, annual_volume_kg=annual,
                created_by="田中", data_origin=ORIGIN,
            ))
            memo = None
            if i == len(PAST_PERIODS) and row.get("V7_過去に効いた材料"):
                memo = f"{row['V7_過去に効いた材料']}が有効だった"
            session.add(m.NegotiationResult(
                tenant_id=tenant_id, case_no=p_case_no,
                result_date=p_date, final_price=price,
                staff_memo=memo, data_origin=ORIGIN,
            ))
            counts["past_cases"] += 1
            counts["results"] += 1
        session.flush()

    session.commit()
    counts["tenant_id"] = tenant_id
    return counts


def _main() -> None:
    from app.db.database import get_sessionmaker

    session = get_sessionmaker()()
    try:
        counts = import_all(session)
    finally:
        session.close()
    print("GraphRAG評価データ取込 完了:")
    for key, value in counts.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    _main()
