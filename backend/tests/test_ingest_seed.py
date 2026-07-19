"""test_ingest_seed.py — マスタ・サンプルデータ取込の統合テスト。

インメモリ SQLite に seed_all を流し、件数と N-06 正規化・多層取込を検証する。
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models as m
from app.ingest.seed import seed_all


def _count(session: Session, model) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar()


def test_seed_all_counts(db_session: Session) -> None:
    """全テーブルの取込件数が期待どおりであること。"""
    counts = seed_all(db_session)

    assert _count(db_session, m.InfomartCategory) == 2492
    assert _count(db_session, m.RateChangeReason) == 10
    assert _count(db_session, m.Supplier) == 4
    assert _count(db_session, m.Product) == 4
    assert _count(db_session, m.ProductSpec) == 6
    assert _count(db_session, m.CompanyPlan) == 4
    assert _count(db_session, m.MarketRate) == 12
    assert _count(db_session, m.NegotiationCase) == 8
    assert _count(db_session, m.StrategySheet) == 7
    assert _count(db_session, m.NegotiationResult) == 5
    assert _count(db_session, m.RawImport) == 12
    assert _count(db_session, m.ModelVersion) == 2
    assert counts["market_rates_import"] == {"raw": 12, "normalized": 12, "rejected": 0}


def test_seed_n06_normalization(db_session: Session) -> None:
    """相場CSVが N-06 で正規化されて着地していること（Jul-25→2025-07 / 3.20%→3.20）。"""
    seed_all(db_session)
    rate = db_session.execute(
        select(m.MarketRate).order_by(m.MarketRate.year_month).limit(1)
    ).scalar_one()
    assert rate.year_month == "2025-07"
    assert rate.yoy_change == Decimal("3.20")
    assert rate.price_yen_kg == Decimal("550")
    assert rate.import_batch_id is not None  # raw_imports へ遡及可能


def test_seed_raw_imports_normalized(db_session: Session) -> None:
    """生データ着地層が全件 normalized になっていること（多層取込の成立）。"""
    seed_all(db_session)
    normalized = db_session.execute(
        select(func.count()).select_from(m.RawImport).where(m.RawImport.normalize_status == "normalized")
    ).scalar()
    assert normalized == 12
    # 正規化レコードは元バッチへ遡及できる
    raw = db_session.execute(select(m.RawImport).limit(1)).scalar_one()
    assert raw.source_type == "maff_csv"
    assert raw.target_table == "market_rates"


def test_seed_reason_mapping(db_session: Session) -> None:
    """案件の主張理由が reason_id（RC-xx）へマッピングされていること。"""
    seed_all(db_session)
    case = db_session.execute(
        select(m.NegotiationCase).where(m.NegotiationCase.case_no == "No.123456-a")
    ).scalar_one()
    # 為替影響=RC-03 / 原材料・飼料価格=RC-04 / 物流費・燃料費=RC-05
    assert case.claimed_reasons == ["RC-03", "RC-04", "RC-05"]


def test_seed_model_versions(db_session: Session) -> None:
    """算出式 v1.0 が活性・共通モデルとして投入されること。"""
    seed_all(db_session)
    v1 = db_session.execute(
        select(m.ModelVersion).where(m.ModelVersion.version_label == "ルールv1.0")
    ).scalar_one()
    assert v1.tenant_id is None  # 全テナント共通
    assert v1.is_active is True
    assert v1.model_type == "calc_rule"
    assert "lines" in v1.definition
