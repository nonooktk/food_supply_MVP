"""models.py — SQLAlchemy 2.0 方言中立モデル（設計 v3 §2 準拠）。

xlsx の9テーブルを正とし、設計 v3 §2 の3拡張（tenant_id / raw_imports / model_versions）を加える。
DDL 正本は MySQL 8.4 だが、モデルは方言中立に保ち ``DB_BACKEND``（sqlite/mysql/postgresql）で
切替する。主な方言差はこの層で吸収する（設計 v3 §2 の方言中立モデル方針）。

方言中立化の要点:
- ``CHAR(36)`` → ``String(36)``（UUID はアプリ生成 ``default=uuid.uuid4``）
- ``BIGINT AUTO_INCREMENT`` → ``BigInteger().with_variant(Integer, "sqlite")``
  （SQLite は ``INTEGER PRIMARY KEY`` のみ rowid 別名で自動採番するため、SQLite 方言では
  ``INTEGER`` を出力して autoincrement を有効化する）
- ``numeric(p,s)`` → ``Numeric(p,s)`` / ``jsonb``・``text[]`` → ``JSON`` / ``timestamptz`` → ``DateTime``（UTC 格納）
- ``boolean`` → ``Boolean``

複合主キー + AUTO_INCREMENT の扱い [決定・実装差分]:
  設計 DDL は ``PRIMARY KEY (tenant_id, xxx_id)`` かつ ``xxx_id`` を AUTO_INCREMENT とするが、
  この構成は SQLite で自動採番できない（SQLite の自動採番は単一 INTEGER 主キー限定）。
  そこで **代理キー ``xxx_id`` を単独 PK（autoincrement）とし、``UNIQUE(tenant_id, xxx_id)`` を併記**して
  複合外部キー ``(tenant_id, 親id)`` の参照先を維持する。カラムの削除・改名はせず、テナントスコープ FK の
  整合性（他テナントへの越境参照を型レベルで防ぐ）も保つ。MySQL でも AUTO_INCREMENT 列が PK 先頭になり
  InnoDB 制約を満たす。``negotiation_cases`` は ``case_no`` が自動採番でないため複合 PK のまま。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# ---- 方言中立の型エイリアス ----------------------------------------------------
# SQLite では INTEGER（rowid 別名で自動採番）、それ以外は BIGINT を出力する。
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


def _utcnow() -> datetime:
    """UTC の現在時刻（tz 付き）。全テーブルの監査列は UTC 格納で統一する。"""
    return datetime.now(timezone.utc)


def _uuid_str() -> str:
    """CHAR(36) 用の UUID 文字列を生成する。"""
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    """全モデルの基底。"""


class TimestampMixin:
    """共通監査列（created_at / updated_at・UTC 格納。設計 v3 §2.0）。"""

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


# ==============================================================================
# 2.1 共通マスタ（テナント横断・参照層）
# ==============================================================================
class Tenant(Base):
    """テナント（本設計で追加する管理テーブル）。"""

    __tablename__ = "tenants"

    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    tenant_name: Mapped[str] = mapped_column(Text, nullable=False)
    case_no_prefix: Mapped[str | None] = mapped_column(String(8))  # 案件番号の接頭辞（2.7）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class InfomartCategory(Base):
    """インフォマート小分類マスタ（共有参照。設計 v3 §2.1）。"""

    __tablename__ = "infomart_categories"

    infomart_code: Mapped[str] = mapped_column(String(6), primary_key=True)  # 6桁・ゼロ埋め保持
    category_l1: Mapped[str | None] = mapped_column(Text)
    category_l2: Mapped[str | None] = mapped_column(Text)
    category_l3: Mapped[str | None] = mapped_column(Text)
    category_l4: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(Text)


class RateChangeReason(Base):
    """変動理由マスタ（RC-01〜10・共有参照。設計 v3 §2.1）。"""

    __tablename__ = "rate_change_reasons"

    reason_id: Mapped[str] = mapped_column(String(8), primary_key=True)  # 'RC-01' 等
    reason_name: Mapped[str] = mapped_column(Text, nullable=False)
    impact_direction: Mapped[str | None] = mapped_column(String(2))  # '↑' / '↓' / '±'
    description: Mapped[str | None] = mapped_column(Text)


# ==============================================================================
# 2.2 商材・取引先マスタ（テナント別）
# ==============================================================================
class Supplier(Base, TimestampMixin):
    """取引先（xlsx: suppliers）。"""

    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("tenant_id", "supplier_id", name="uq_suppliers_tenant_id"),)

    supplier_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    # tenant_id 単独索引は不要。UNIQUE(tenant_id, supplier_id) の先頭プレフィックスで代替される。
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    supplier_name: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_category: Mapped[str | None] = mapped_column(Text)
    supplier_memo: Mapped[str | None] = mapped_column(Text)  # 関係性・注意点メモ（長文）


class Product(Base, TimestampMixin):
    """商材（xlsx: products）。"""

    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("tenant_id", "product_id", name="uq_products_tenant_id"),)

    product_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    # tenant_id 単独索引は不要。UNIQUE(tenant_id, product_id) の先頭プレフィックスで代替される。
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    product_name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)  # 食肉/卵 等
    unit: Mapped[str | None] = mapped_column(Text)  # 単位=価格の分母


class ProductSpec(Base, TimestampMixin):
    """商材スペック（xlsx: product_specs）。価格比較は必ず spec 単位。"""

    __tablename__ = "product_specs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "spec_id", name="uq_product_specs_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.product_id"],
            name="fk_product_specs_product",
        ),
        ForeignKeyConstraint(
            ["infomart_code"], ["infomart_categories.infomart_code"], name="fk_product_specs_infomart"
        ),
    )

    spec_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    # tenant_id 単独索引は不要。UNIQUE(tenant_id, spec_id) の先頭プレフィックスで代替される。
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    origin: Mapped[str | None] = mapped_column(Text)  # 産地
    part: Mapped[str | None] = mapped_column(Text)  # 部位
    grade: Mapped[str | None] = mapped_column(Text)  # グレード（自由記述・確認4）
    storage_type: Mapped[str | None] = mapped_column(Text)  # 温度帯
    pack: Mapped[str | None] = mapped_column(Text)  # 荷姿
    infomart_code: Mapped[str | None] = mapped_column(String(6))
    spec_memo: Mapped[str | None] = mapped_column(Text)


# ==============================================================================
# 2.3 相場・自社計画
# ==============================================================================
class MarketRate(Base, TimestampMixin):
    """相場情報（xlsx: market_rates）。"""

    __tablename__ = "market_rates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "spec_id"],
            ["product_specs.tenant_id", "product_specs.spec_id"],
            name="fk_market_rates_spec",
        ),
    )

    rate_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    spec_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    year_month: Mapped[str] = mapped_column(String(7), nullable=False)  # 'YYYY-MM'
    price_yen_kg: Mapped[float | None] = mapped_column(Numeric(10, 2))
    yoy_change: Mapped[float | None] = mapped_column(Numeric(6, 2))  # 前年同月比（数値）
    source: Mapped[str | None] = mapped_column(Text)  # 出典（FR-02）
    input_method: Mapped[str | None] = mapped_column(Text)  # 手入力/CSV
    import_batch_id: Mapped[str | None] = mapped_column(String(36))  # raw_imports へ遡及


class CompanyPlan(Base, TimestampMixin):
    """自社計画（xlsx: company_plans）。"""

    __tablename__ = "company_plans"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "spec_id"],
            ["product_specs.tenant_id", "product_specs.spec_id"],
            name="fk_company_plans_spec",
        ),
    )

    plan_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    spec_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    period: Mapped[str | None] = mapped_column(Text)  # 例 '2026Q3'
    target_cost_rate: Mapped[float | None] = mapped_column(Numeric(5, 2))  # 目標原価率
    planned_price: Mapped[float | None] = mapped_column(Numeric(10, 2))  # 計画仕入単価
    volume_kg_month: Mapped[int | None] = mapped_column(Integer)  # 発注量 kg/月
    annual_volume_kg: Mapped[int | None] = mapped_column(Integer)  # 年間使用量 kg
    max_acceptable_price: Mapped[float | None] = mapped_column(Numeric(10, 2))  # 許容上限
    note: Mapped[str | None] = mapped_column(Text)


# ==============================================================================
# 2.4 交渉案件・作戦シート・結果
# ==============================================================================
class NegotiationCase(Base, TimestampMixin):
    """交渉案件（xlsx: negotiation_cases）。案件番号がキー。"""

    __tablename__ = "negotiation_cases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["suppliers.tenant_id", "suppliers.supplier_id"],
            name="fk_cases_supplier",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "spec_id"],
            ["product_specs.tenant_id", "product_specs.spec_id"],
            name="fk_cases_spec",
        ),
    )

    # case_no は自動採番でないため (tenant_id, case_no) 複合 PK を維持（設計どおり）。
    # 複合 PK が tenant_id を先頭に含むため、tenant_id 単独索引は付けない（重複回避）。
    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_no: Mapped[str] = mapped_column(String(20), primary_key=True)  # 採番は 2.7 / numbering.py
    supplier_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    spec_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    period: Mapped[str | None] = mapped_column(Text)
    case_type: Mapped[str | None] = mapped_column(Text)  # 見積/値上げ要請/契約更新（seams.CaseType）
    status: Mapped[str | None] = mapped_column(Text)  # 交渉中/完了
    current_price: Mapped[float | None] = mapped_column(Numeric(10, 2))
    proposed_price: Mapped[float | None] = mapped_column(Numeric(10, 2))
    volume_kg_month: Mapped[int | None] = mapped_column(Integer)
    annual_volume_kg: Mapped[int | None] = mapped_column(Integer)
    proposed_conditions: Mapped[str | None] = mapped_column(Text)
    claimed_reasons: Mapped[list | None] = mapped_column(JSON)  # RC-xx の JSON 配列
    valid_until: Mapped[Date | None] = mapped_column(Date)
    created_by: Mapped[str | None] = mapped_column(Text)
    data_origin: Mapped[str | None] = mapped_column(Text)  # 初期データ/アプリ登録


class StrategySheet(Base, TimestampMixin):
    """作戦シート（xlsx: strategy_sheets）。case_no で 1:1 に紐づく。"""

    __tablename__ = "strategy_sheets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sheet_id", name="uq_strategy_sheets_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "case_no"],
            ["negotiation_cases.tenant_id", "negotiation_cases.case_no"],
            name="fk_strategy_case",
        ),
    )

    sheet_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    # tenant_id 単独索引は不要。UNIQUE(tenant_id, sheet_id) の先頭プレフィックスで代替される。
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    case_no: Mapped[str] = mapped_column(String(20), nullable=False)
    price_diff: Mapped[float | None] = mapped_column(Numeric(10, 2))  # 提示−現行
    annual_impact: Mapped[int | None] = mapped_column(BigInteger)  # 年間影響額 ¥
    calc_version: Mapped[str | None] = mapped_column(String(20))  # model_versions.version_label と論理FK
    target_auto: Mapped[float | None] = mapped_column(Numeric(10, 2))
    target_final: Mapped[float | None] = mapped_column(Numeric(10, 2))
    landing_auto: Mapped[float | None] = mapped_column(Numeric(10, 2))
    landing_final: Mapped[float | None] = mapped_column(Numeric(10, 2))
    walkaway_auto: Mapped[float | None] = mapped_column(Numeric(10, 2))
    walkaway_final: Mapped[float | None] = mapped_column(Numeric(10, 2))
    line_edit_reason: Mapped[str | None] = mapped_column(Text)  # 修正理由（FR-06）
    impact_target: Mapped[int | None] = mapped_column(BigInteger)
    impact_landing: Mapped[int | None] = mapped_column(BigInteger)
    impact_walkaway: Mapped[int | None] = mapped_column(BigInteger)
    ai_points: Mapped[str | None] = mapped_column(Text)  # AI生成（FR-08）
    ai_scenario: Mapped[str | None] = mapped_column(Text)  # AI生成（FR-08）
    saved_at: Mapped[datetime | None] = mapped_column(DateTime)  # 保存日時（FR-09・UTC）
    data_origin: Mapped[str | None] = mapped_column(Text)


class NegotiationResult(Base, TimestampMixin):
    """交渉結果（xlsx: negotiation_results）。case_no で 1:1 に紐づく。"""

    __tablename__ = "negotiation_results"
    __table_args__ = (
        UniqueConstraint("tenant_id", "result_id", name="uq_negotiation_results_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "case_no"],
            ["negotiation_cases.tenant_id", "negotiation_cases.case_no"],
            name="fk_results_case",
        ),
    )

    result_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    # tenant_id 単独索引は不要。UNIQUE(tenant_id, result_id) の先頭プレフィックスで代替される。
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    case_no: Mapped[str] = mapped_column(String(20), nullable=False)
    result_date: Mapped[Date | None] = mapped_column(Date)
    final_price: Mapped[float | None] = mapped_column(Numeric(10, 2))  # 決着単価（FR-11）
    delivery_term: Mapped[str | None] = mapped_column(Text)
    payment_site: Mapped[str | None] = mapped_column(Text)
    vs_quote: Mapped[float | None] = mapped_column(Numeric(10, 2))
    vs_landing: Mapped[float | None] = mapped_column(Numeric(10, 2))
    achievement: Mapped[float | None] = mapped_column(Numeric(5, 2))  # 目標達成度 %
    result_tags: Mapped[list | None] = mapped_column(JSON)  # 決着理由タグ（FR-12）
    accepted_reasons: Mapped[list | None] = mapped_column(JSON)  # 認めた変動理由（RC-xx）
    staff_memo: Mapped[str | None] = mapped_column(Text)
    handover_note: Mapped[str | None] = mapped_column(Text)
    prep_hours: Mapped[float | None] = mapped_column(Numeric(5, 2))
    data_origin: Mapped[str | None] = mapped_column(Text)


# ==============================================================================
# 2.5 生データ着地層
# ==============================================================================
class RawImport(Base):
    """生データ着地層（raw_imports。設計 v3 §2.5）。

    外部データを無加工で着地させ、``import_batch_id`` で正規化層から逆引きできる。
    ライフサイクル列（received_at / normalized_at）が監査列を兼ねる。
    """

    __tablename__ = "raw_imports"

    import_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    import_batch_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)  # maff_csv/infomart/manual/pdf
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False)  # 元フォーマットのまま
    normalize_status: Mapped[str] = mapped_column(String(16), nullable=False, default="received")
    normalize_error: Mapped[str | None] = mapped_column(Text)
    target_table: Mapped[str | None] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    normalized_at: Mapped[datetime | None] = mapped_column(DateTime)


# ==============================================================================
# 2.6 精度向上用（model_versions）
# ==============================================================================
class ModelVersion(Base):
    """算出式・AIプロンプト・（将来）推定モデルの版管理（設計 v3 §2.6）。

    tenant_id が NULL のときは全テナント共通の既定モデル。
    """

    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "model_type", "version_label", name="uq_model_versions_key"
        ),
    )

    model_version_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36))  # NULL=全テナント共通
    model_type: Mapped[str] = mapped_column(String(16), nullable=False)  # calc_rule/ai_prompt/estimation
    version_label: Mapped[str] = mapped_column(String(20), nullable=False)  # 'ルールv1.0' 等
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)  # 算出式パラメータ or プロンプト
    change_reason: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


# 業務テーブル（テナントスコープ Repository の対象）の一覧。
# 共有マスタ（tenants / infomart_categories / rate_change_reasons）と model_versions は対象外。
TENANT_SCOPED_MODELS = (
    Supplier,
    Product,
    ProductSpec,
    MarketRate,
    CompanyPlan,
    NegotiationCase,
    StrategySheet,
    NegotiationResult,
)
