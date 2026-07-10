"""conftest.py — テスト共通フィクスチャ。

実 DB（freeradicals.db）に触れず、テストごとにインメモリ SQLite を新規生成する。
外部キー制約を有効化し、テナントスコープ FK が実際に効くことを検証できるようにする。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import models as m
from app.db.models import Base


@pytest.fixture()
def db_session() -> Session:
    """FK 有効・インメモリ SQLite の新規セッションを返す（テストごとに独立）。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # 単一接続を共有し、インメモリDBを保持する
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def minimal_graph(db_session: Session):
    """案件を作れる最小の親グラフ（tenant / supplier / product / spec）を用意する。

    返り値: (tenant_id, supplier_id, spec_id)
    """
    tenant_id = str(uuid.uuid4())
    db_session.add(m.Tenant(tenant_id=tenant_id, tenant_name="テスト商店", case_no_prefix=""))
    db_session.add(m.InfomartCategory(infomart_code="113501", label="鶏肉F/もも"))
    db_session.add(m.Supplier(supplier_id=1, tenant_id=tenant_id, supplier_name="テスト取引先"))
    db_session.add(m.Product(product_id=1, tenant_id=tenant_id, product_name="鶏もも肉", unit="kg"))
    db_session.flush()
    db_session.add(
        m.ProductSpec(spec_id=1, tenant_id=tenant_id, product_id=1, infomart_code="113501")
    )
    db_session.flush()
    return tenant_id, 1, 1
