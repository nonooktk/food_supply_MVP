"""test_tenant_repository.py — テナントスコープ Repository の越境ゼロ検証（設計 v3 §2.8）。

要件 N-02「テナント越境ゼロ」を担保する必須ゲート。テナント A の Repository から
テナント B の行を read / update / delete しても必ずゼロ件になることを検証する。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.repository import TenantIsolationError, TenantScopedRepository


def _make_tenant(session: Session, name: str) -> str:
    tid = str(uuid.uuid4())
    session.add(m.Tenant(tenant_id=tid, tenant_name=name))
    session.flush()
    return tid


def test_list_excludes_other_tenant(db_session: Session) -> None:
    """list は自テナント行のみを返す（他テナントは不可視）。"""
    a = _make_tenant(db_session, "A")
    b = _make_tenant(db_session, "B")
    repo_a = TenantScopedRepository(db_session, a)
    repo_b = TenantScopedRepository(db_session, b)
    repo_a.add(m.Supplier(supplier_name="A社取引先"))
    repo_b.add(m.Supplier(supplier_name="B社取引先"))
    db_session.flush()

    a_rows = repo_a.list(m.Supplier)
    assert len(a_rows) == 1
    assert a_rows[0].supplier_name == "A社取引先"
    assert all(r.tenant_id == a for r in a_rows)


def test_add_forces_tenant_id(db_session: Session) -> None:
    """add はリクエスト由来の tenant_id を無視し、スコープの値を強制付与する。"""
    a = _make_tenant(db_session, "A")
    b = _make_tenant(db_session, "B")
    repo_a = TenantScopedRepository(db_session, a)
    # 悪意ある tenant_id=B を差し込んでも A に矯正される
    obj = m.Supplier(tenant_id=b, supplier_name="なりすまし")
    repo_a.add(obj)
    db_session.flush()
    assert obj.tenant_id == a


def test_get_cannot_reach_other_tenant(db_session: Session) -> None:
    """他テナントの行を主キー指定で取得してもゼロ件になる。"""
    a = _make_tenant(db_session, "A")
    b = _make_tenant(db_session, "B")
    repo_b = TenantScopedRepository(db_session, b)
    sup_b = repo_b.add(m.Supplier(supplier_name="B社"))
    db_session.flush()

    repo_a = TenantScopedRepository(db_session, a)
    # A のスコープで B の supplier_id を引いても None
    assert repo_a.get(m.Supplier, supplier_id=sup_b.supplier_id) is None


def test_update_delete_other_tenant_is_zero(db_session: Session) -> None:
    """他テナント行への update / delete は影響ゼロ件。"""
    a = _make_tenant(db_session, "A")
    b = _make_tenant(db_session, "B")
    repo_b = TenantScopedRepository(db_session, b)
    sup_b = repo_b.add(m.Supplier(supplier_name="B社"))
    db_session.flush()

    repo_a = TenantScopedRepository(db_session, a)
    updated = repo_a.update_where(
        m.Supplier, {"supplier_name": "改ざん"}, m.Supplier.supplier_id == sup_b.supplier_id
    )
    deleted = repo_a.delete_where(m.Supplier, m.Supplier.supplier_id == sup_b.supplier_id)
    assert updated == 0
    assert deleted == 0

    # B の行は無傷
    db_session.refresh(sup_b)
    assert sup_b.supplier_name == "B社"


def test_empty_tenant_id_rejected(db_session: Session) -> None:
    """tenant_id 未指定（未認証）は Deny by Default で拒否する。"""
    with pytest.raises(TenantIsolationError):
        TenantScopedRepository(db_session, "")


def test_shared_master_rejected(db_session: Session) -> None:
    """tenant_id を持たない共有マスタへのスコープ操作は機構的に失敗する。"""
    a = _make_tenant(db_session, "A")
    repo_a = TenantScopedRepository(db_session, a)
    with pytest.raises(TenantIsolationError):
        repo_a.list(m.RateChangeReason)


def test_model_versions_reads_common_and_own(db_session: Session) -> None:
    """model_versions は自テナント行＋共通(NULL)を参照し、他テナント専用行は見えない。"""
    a = _make_tenant(db_session, "A")
    b = _make_tenant(db_session, "B")
    db_session.add(m.ModelVersion(tenant_id=None, model_type="calc_rule", version_label="共通v1", definition={}))
    db_session.add(m.ModelVersion(tenant_id=a, model_type="calc_rule", version_label="A専用", definition={}))
    db_session.add(m.ModelVersion(tenant_id=b, model_type="calc_rule", version_label="B専用", definition={}))
    db_session.flush()

    labels = {mv.version_label for mv in TenantScopedRepository(db_session, a).list_model_versions("calc_rule")}
    assert labels == {"共通v1", "A専用"}  # B専用は不可視
