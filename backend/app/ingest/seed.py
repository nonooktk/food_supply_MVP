"""seed.py — マスタ・サンプルデータの取込（設計 v3 §2.5 の多層構造）。

取込の全体像:
1. 共有マスタ: インフォマート分類（CSV・2,492件）/ 変動理由（ダミーJSON・10件）
2. テナント別ダミー: 取引先 / 商材 / スペック / 自社計画 / 案件 / 作戦シート / 交渉結果
3. 相場データ: サンプルCSV（`Jul-25` 等の生フォーマット）を **raw_imports へ着地 → N-06 正規化 →
   market_rates へ upsert** する多層経路で取り込む（要件 N-01/N-06）。
4. model_versions: 3ライン算出式 v1.0（＋履歴 v0.9）を共通モデルとして投入。

データ源はリポジトリ同梱の `app/ingest/data/`（xlsx を CSV/JSON へ事前変換したもの。
ランタイムに openpyxl 依存を持ち込まないための措置）。
"""

from __future__ import annotations

import csv
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import models as m
from app.db.seams import (
    CALC_RULE_V1,
    CALC_RULE_V1_LABEL,
    CALC_RULE_V09,
    CALC_RULE_V09_LABEL,
)
from app.ingest.normalize import (
    NormalizeError,
    normalize_percent,
    normalize_year_month,
    to_halfwidth,
    zero_pad_code,
)

DATA_DIR = Path(__file__).resolve().parent / "data"
DEMO_TENANT_NAME = "ふりぃらじかるず デモ商店"


# ==============================================================================
# 値コアーション（xlsx 由来の表記ゆれを吸収）
# ==============================================================================
def _to_decimal(value) -> Decimal | None:
    """`+11` / `-5,184,000` / `30.0%` / 595 等を Decimal に変換する。"""
    if value in (None, "", "-"):
        return None
    s = to_halfwidth(str(value)).strip().replace(",", "").replace("+", "").replace("%", "")
    if s == "":
        return None
    return Decimal(s)


def _to_int(value) -> int | None:
    d = _to_decimal(value)
    return int(d) if d is not None else None


def _to_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()


def _to_datetime(value) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"日時を解釈できません: {value!r}")


def _split_csv_field(value) -> list[str]:
    """カンマ区切りの複数値フィールドをトリム済みリストにする。"""
    if value in (None, ""):
        return []
    return [t.strip() for t in str(value).split(",") if t.strip()]


def _map_reason_ids(names: list[str], name2id: dict[str, str]) -> list[str]:
    """変動理由名のリストを reason_id へ変換する（完全一致は id、非一致は原文を保持）。"""
    out: list[str] = []
    for name in names:
        out.append(name2id.get(name, name))  # 一致すれば RC-xx、しなければ原文（注記等）
    return out


def _load_json(name: str) -> dict:
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


# ==============================================================================
# 1. 共有マスタ
# ==============================================================================
def load_infomart_categories(session: Session) -> int:
    """インフォマート分類 CSV を infomart_categories へ投入する。"""
    rows: list[dict] = []
    with open(DATA_DIR / "infomart_categories.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(
                {
                    "infomart_code": zero_pad_code(r["infomart_code"]),
                    "category_l1": r["category_l1"] or None,
                    "category_l2": r["category_l2"] or None,
                    "category_l3": r["category_l3"] or None,
                    "category_l4": r["category_l4"] or None,
                    "label": r["label"] or None,
                }
            )
    session.bulk_insert_mappings(m.InfomartCategory, rows)
    return len(rows)


def load_rate_change_reasons(session: Session, dummy: dict) -> tuple[int, dict[str, str]]:
    """変動理由マスタを投入し、name→id マップを返す。"""
    name2id: dict[str, str] = {}
    count = 0
    for r in dummy["rate_change_reasons"]:
        reason = m.RateChangeReason(
            reason_id=str(r["reason_id"]).strip(),
            reason_name=str(r["reason_name"]).strip(),
            impact_direction=(r.get("impact_direction") or None),
            description=(r.get("description") or None),
        )
        session.add(reason)
        name2id[reason.reason_name] = reason.reason_id
        count += 1
    return count, name2id


# ==============================================================================
# 2. テナント別ダミー
# ==============================================================================
def _create_tenant(session: Session) -> str:
    tenant = m.Tenant(tenant_id=str(uuid.uuid4()), tenant_name=DEMO_TENANT_NAME, case_no_prefix="")
    session.add(tenant)
    session.flush()
    return tenant.tenant_id


def _load_business_masters(session: Session, tenant_id: str, dummy: dict) -> dict[str, int]:
    counts: dict[str, int] = {}

    # 親→子の順で確定させるため、グループごとに flush する（FK 参照先を先に永続化）。
    for r in dummy["suppliers"]:
        session.add(
            m.Supplier(
                supplier_id=_to_int(r["supplier_id"]),
                tenant_id=tenant_id,
                supplier_name=r["supplier_name"],
                supplier_category=r.get("supplier_category"),
                supplier_memo=r.get("supplier_memo"),
            )
        )
    counts["suppliers"] = len(dummy["suppliers"])

    for r in dummy["products"]:
        session.add(
            m.Product(
                product_id=_to_int(r["product_id"]),
                tenant_id=tenant_id,
                product_name=r["product_name"],
                category=r.get("category"),
                unit=r.get("unit"),
            )
        )
    counts["products"] = len(dummy["products"])
    session.flush()  # suppliers / products を先に確定

    for r in dummy["product_specs"]:
        session.add(
            m.ProductSpec(
                spec_id=_to_int(r["spec_id"]),
                tenant_id=tenant_id,
                product_id=_to_int(r["product_id"]),
                origin=r.get("origin"),
                part=r.get("part"),
                grade=(r.get("grade") or None),
                storage_type=r.get("storage_type"),
                pack=r.get("pack"),
                infomart_code=zero_pad_code(r.get("infomart_code")),
                spec_memo=r.get("spec_memo"),
            )
        )
    counts["product_specs"] = len(dummy["product_specs"])
    session.flush()  # product_specs を先に確定（company_plans / cases の FK 参照先）

    for r in dummy["company_plans"]:
        session.add(
            m.CompanyPlan(
                plan_id=_to_int(r["plan_id"]),
                tenant_id=tenant_id,
                spec_id=_to_int(r["spec_id"]),
                period=r.get("period"),
                target_cost_rate=_to_decimal(r.get("target_cost_rate")),
                planned_price=_to_decimal(r.get("planned_price")),
                volume_kg_month=_to_int(r.get("volume_kg_month")),
                annual_volume_kg=_to_int(r.get("annual_volume_kg")),
                max_acceptable_price=_to_decimal(r.get("max_acceptable_price")),
                note=(r.get("note") or None),
            )
        )
    counts["company_plans"] = len(dummy["company_plans"])
    session.flush()
    return counts


def _load_cases_and_children(
    session: Session, tenant_id: str, dummy: dict, name2id: dict[str, str]
) -> dict[str, int]:
    counts: dict[str, int] = {}

    for r in dummy["negotiation_cases"]:
        session.add(
            m.NegotiationCase(
                tenant_id=tenant_id,
                case_no=str(r["case_no"]).strip(),
                supplier_id=_to_int(r["supplier_id"]),
                spec_id=_to_int(r["spec_id"]),
                period=r.get("period"),
                case_type=r.get("case_type"),
                status=r.get("status"),
                current_price=_to_decimal(r.get("current_price")),
                proposed_price=_to_decimal(r.get("proposed_price")),
                volume_kg_month=_to_int(r.get("volume_kg_month")),
                annual_volume_kg=_to_int(r.get("annual_volume_kg")),
                proposed_conditions=r.get("proposed_conditions"),
                claimed_reasons=_map_reason_ids(_split_csv_field(r.get("claimed_reasons")), name2id),
                valid_until=_to_date(r.get("valid_until")),
                created_by=r.get("created_by"),
                data_origin=r.get("data_origin"),
            )
        )
    counts["negotiation_cases"] = len(dummy["negotiation_cases"])
    session.flush()

    for r in dummy["strategy_sheets"]:
        session.add(
            m.StrategySheet(
                sheet_id=_to_int(r["sheet_id"]),
                tenant_id=tenant_id,
                case_no=str(r["case_no"]).strip(),
                price_diff=_to_decimal(r.get("price_diff")),
                annual_impact=_to_int(r.get("annual_impact")),
                calc_version=r.get("calc_version"),
                target_auto=_to_decimal(r.get("target_auto")),
                target_final=_to_decimal(r.get("target_final")),
                landing_auto=_to_decimal(r.get("landing_auto")),
                landing_final=_to_decimal(r.get("landing_final")),
                walkaway_auto=_to_decimal(r.get("walkaway_auto")),
                walkaway_final=_to_decimal(r.get("walkaway_final")),
                line_edit_reason=r.get("line_edit_reason"),
                impact_target=_to_int(r.get("impact_target")),
                impact_landing=_to_int(r.get("impact_landing")),
                impact_walkaway=_to_int(r.get("impact_walkaway")),
                ai_points=r.get("ai_points"),
                ai_scenario=r.get("ai_scenario"),
                saved_at=_to_datetime(r.get("saved_at")),
                data_origin=r.get("data_origin"),
            )
        )
    counts["strategy_sheets"] = len(dummy["strategy_sheets"])

    for r in dummy["negotiation_results"]:
        session.add(
            m.NegotiationResult(
                tenant_id=tenant_id,
                case_no=str(r["case_no"]).strip(),
                result_date=_to_date(r.get("result_date")),
                final_price=_to_decimal(r.get("final_price")),
                delivery_term=r.get("delivery_term"),
                payment_site=r.get("payment_site"),
                vs_quote=_to_decimal(r.get("vs_quote")),
                vs_landing=_to_decimal(r.get("vs_landing")),
                achievement=normalize_percent(r.get("achievement")),
                result_tags=_split_csv_field(r.get("result_tags")),
                accepted_reasons=_map_reason_ids(_split_csv_field(r.get("accepted_reasons")), name2id),
                staff_memo=r.get("staff_memo"),
                handover_note=r.get("handover_note"),
                prep_hours=_to_decimal(r.get("prep_hours")),
                data_origin=r.get("data_origin"),
            )
        )
    counts["negotiation_results"] = len(dummy["negotiation_results"])
    session.flush()
    return counts


# ==============================================================================
# 3. 相場データ（raw_imports 着地 → N-06 正規化 → market_rates）
# ==============================================================================
def ingest_market_rates_csv(session: Session, tenant_id: str) -> dict[str, int]:
    """サンプル相場CSVを生データ着地層経由で取り込む。

    返り値: {"raw": 着地件数, "normalized": 正規化成功件数, "rejected": 失敗件数}
    """
    batch_id = str(uuid.uuid4())
    # spec 解決用: (infomart_code) → spec_id（当該テナント）
    specs = session.query(m.ProductSpec).filter(m.ProductSpec.tenant_id == tenant_id).all()
    code2spec = {s.infomart_code: s.spec_id for s in specs if s.infomart_code}

    raw = normalized = rejected = 0
    with open(DATA_DIR / "market_rates_sample.csv", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            raw += 1
            # (a) 無加工で raw_imports へ着地
            raw_rec = m.RawImport(
                tenant_id=tenant_id,
                import_batch_id=batch_id,
                source_type="maff_csv",
                raw_payload=row,
                normalize_status="received",
                target_table="market_rates",
            )
            session.add(raw_rec)
            session.flush()

            # (b) N-06 正規化
            try:
                year_month = normalize_year_month(row["year_month"])
                yoy = normalize_percent(row["yoy_change"])
                code = zero_pad_code(row["infomart_code"])
                spec_id = code2spec.get(code)
                if spec_id is None:
                    raise NormalizeError(f"infomart_code {code} に対応する spec が見つかりません。")
                price = _to_decimal(row["price_yen_kg"])
            except NormalizeError as exc:
                raw_rec.normalize_status = "rejected"
                raw_rec.normalize_error = str(exc)
                rejected += 1
                continue

            # (c) 正規化層 market_rates へ投入
            session.add(
                m.MarketRate(
                    tenant_id=tenant_id,
                    spec_id=spec_id,
                    year_month=year_month,
                    price_yen_kg=price,
                    yoy_change=yoy,
                    source=row.get("source"),
                    input_method="CSV",
                    import_batch_id=batch_id,
                )
            )
            raw_rec.normalize_status = "normalized"
            raw_rec.normalized_at = datetime.now(timezone.utc)
            normalized += 1

    session.flush()
    return {"raw": raw, "normalized": normalized, "rejected": rejected}


# ==============================================================================
# 4. model_versions（算出式 v1.0 ＋ 履歴 v0.9）
# ==============================================================================
def seed_model_versions(session: Session) -> int:
    """3ライン算出式の版を共通モデル（tenant_id=NULL）として投入する。"""
    session.add(
        m.ModelVersion(
            tenant_id=None,
            model_type="calc_rule",
            version_label=CALC_RULE_V1_LABEL,
            definition=CALC_RULE_V1,
            change_reason="3ライン算出モデル初版（FR-05）。",
            is_active=True,
        )
    )
    session.add(
        m.ModelVersion(
            tenant_id=None,
            model_type="calc_rule",
            version_label=CALC_RULE_V09_LABEL,
            definition=CALC_RULE_V09,
            change_reason="v1.0 以前の暫定式（過去シート参照用の履歴版）。",
            is_active=False,
        )
    )
    return 2


# ==============================================================================
# オーケストレータ
# ==============================================================================
def seed_all(session: Session) -> dict:
    """全マスタ・サンプルデータを取り込み、件数サマリを返す。

    前提: マイグレーション済みの空 DB。1テナント分のデモデータを投入する。
    """
    dummy = _load_json("dummy_master.json")

    counts: dict = {}
    counts["infomart_categories"] = load_infomart_categories(session)
    reasons_n, name2id = load_rate_change_reasons(session, dummy)
    counts["rate_change_reasons"] = reasons_n

    tenant_id = _create_tenant(session)
    counts["tenant_id"] = tenant_id

    counts.update(_load_business_masters(session, tenant_id, dummy))
    counts.update(_load_cases_and_children(session, tenant_id, dummy, name2id))
    counts["market_rates_import"] = ingest_market_rates_csv(session, tenant_id)
    counts["market_rates"] = counts["market_rates_import"]["normalized"]
    counts["model_versions"] = seed_model_versions(session)

    session.commit()
    return counts


def _main() -> None:
    """CLI エントリ: 実 DB（DB_BACKEND シーム）へシードを投入し件数を表示する。

    実行例（backend/ から。事前に `alembic -c app/alembic.ini upgrade head` 済みであること）:
        python -m app.ingest.seed
    """
    from app.db.database import get_sessionmaker

    session = get_sessionmaker()()
    try:
        counts = seed_all(session)
    finally:
        session.close()
    print("シード取込 完了:")
    for key, value in counts.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    _main()
