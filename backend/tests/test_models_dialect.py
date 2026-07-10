"""test_models_dialect.py — 方言中立モデルの sqlite/mysql 両対応を担保する。

- sqlite: 実際に create_all → autoincrement 採番 → JSON 往復を検証。
- mysql : ライブ接続なしで DDL コンパイルが成功し BIGINT/JSON/AUTO_INCREMENT を出力することを検証。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from app.db import models as m


def test_sqlite_autoincrement(db_session: Session) -> None:
    """複合ユニーク＋単独PKの代理キーが SQLite で自動採番されること。"""
    tenant_id = str(uuid.uuid4())
    db_session.add(m.Tenant(tenant_id=tenant_id, tenant_name="T"))
    db_session.flush()
    s1 = m.Supplier(tenant_id=tenant_id, supplier_name="A")
    s2 = m.Supplier(tenant_id=tenant_id, supplier_name="B")
    db_session.add_all([s1, s2])
    db_session.flush()
    assert s1.supplier_id is not None
    assert s2.supplier_id == s1.supplier_id + 1  # 連番で採番される


def test_json_roundtrip(db_session: Session) -> None:
    """JSON 列（claimed_reasons）がリストとして往復すること。"""
    tenant_id = str(uuid.uuid4())
    db_session.add(m.Tenant(tenant_id=tenant_id, tenant_name="T"))
    db_session.add(m.InfomartCategory(infomart_code="113501", label="x"))
    db_session.add(m.Supplier(supplier_id=1, tenant_id=tenant_id, supplier_name="A"))
    db_session.add(m.Product(product_id=1, tenant_id=tenant_id, product_name="P"))
    db_session.flush()
    db_session.add(m.ProductSpec(spec_id=1, tenant_id=tenant_id, product_id=1, infomart_code="113501"))
    db_session.flush()
    db_session.add(
        m.NegotiationCase(
            tenant_id=tenant_id, case_no="No.500001-a", supplier_id=1, spec_id=1,
            claimed_reasons=["RC-03", "RC-05"],
        )
    )
    db_session.commit()
    got = db_session.execute(
        select(m.NegotiationCase).where(m.NegotiationCase.case_no == "No.500001-a")
    ).scalar_one()
    assert got.claimed_reasons == ["RC-03", "RC-05"]


def test_mysql_ddl_compiles() -> None:
    """MySQL 方言で全テーブルの DDL がコンパイルでき、想定の型が出力されること。"""
    dialect = mysql.dialect()
    ddl_by_table = {
        t.name: str(CreateTable(t).compile(dialect=dialect)) for t in m.Base.metadata.sorted_tables
    }
    # 代理キーは BIGINT + AUTO_INCREMENT（MySQL）
    assert "BIGINT" in ddl_by_table["suppliers"]
    assert "AUTO_INCREMENT" in ddl_by_table["suppliers"]
    # JSON 列は JSON 型
    assert "JSON" in ddl_by_table["negotiation_cases"]
    # 複合主キー（tenant_id, case_no）
    assert "PRIMARY KEY (tenant_id, case_no)" in ddl_by_table["negotiation_cases"]
    # 全13テーブルが生成対象
    assert len(ddl_by_table) == 13
