"""conftest.py — テスト共通フィクスチャ。

実 DB（freeradicals.db）に触れず、テストごとにインメモリ SQLite を新規生成する。
外部キー制約を有効化し、テナントスコープ FK が実際に効くことを検証できるようにする。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import models as m
from app.db.models import Base


def _memory_engine():
    """FK 有効・インメモリ SQLite エンジン（StaticPool で単一接続を共有）。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def db_session() -> Session:
    """FK 有効・インメモリ SQLite の新規セッションを返す（テストごとに独立）。"""
    engine = _memory_engine()
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


@dataclass
class ApiHarness:
    """API テスト用のクライアント一式（seed 済みインメモリ DB へ接続）。"""

    client: object  # fastapi.testclient.TestClient
    tenant_id: str
    sessionmaker: object

    def headers(self, *, tenant_id: str | None = None, user_id: str = "tanaka") -> dict:
        return {"X-Tenant-Id": tenant_id or self.tenant_id, "X-User-Id": user_id}

    def new_session(self) -> Session:
        return self.sessionmaker()


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch) -> ApiHarness:
    """seed 済みインメモリ DB に接続した TestClient を返す。

    アプリの get_session 依存をテスト用エンジンに差し替える。KRE は既定のスタブ（DI）を使う。
    認証は既定を mock に固定する（.env が AUTH_MODE=google でもテストを安定させる。
    google モードを検証するテストは自身で auth_mode を上書きする）。
    """
    from fastapi.testclient import TestClient

    from app.api import deps
    from app.config import get_settings
    from app.ingest.seed import seed_all
    from app.main import create_app

    # 認証モードのテスト既定（.env 値に依存させない）。
    _settings = get_settings()
    monkeypatch.setattr(_settings, "auth_mode", "mock")
    monkeypatch.setattr(_settings, "google_client_id", "")

    engine = _memory_engine()
    SM = sessionmaker(bind=engine, future=True)
    seed_session = SM()
    counts = seed_all(seed_session)
    tenant_id = counts["tenant_id"]
    seed_session.close()

    app = create_app()

    def _override_session():
        db = SM()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[deps.get_session] = _override_session
    client = TestClient(app)
    try:
        yield ApiHarness(client=client, tenant_id=tenant_id, sessionmaker=SM)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
