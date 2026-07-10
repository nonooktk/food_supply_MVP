"""test_numbering.py — 案件番号採番サービス（調整シーム #3）のテスト。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import models as m
from app.db.numbering import SequentialNumberingService


def _add_case(session: Session, tenant_id: str, spec_id: int, supplier_id: int, case_no: str) -> None:
    session.add(
        m.NegotiationCase(
            tenant_id=tenant_id, case_no=case_no, supplier_id=supplier_id, spec_id=spec_id,
            data_origin="アプリ登録",
        )
    )
    session.flush()


def test_first_case_no_is_500001(db_session: Session, minimal_graph) -> None:
    """案件が無いテナントの初回採番は No.500001-a。"""
    tenant_id, supplier_id, spec_id = minimal_graph
    svc = SequentialNumberingService()
    assert svc.next_case_no(db_session, tenant_id) == "No.500001-a"


def test_initial_data_below_500001_ignored(db_session: Session, minimal_graph) -> None:
    """初期データ No.1234xx は採番領域外のため、次番は 500001 から始まる。"""
    tenant_id, supplier_id, spec_id = minimal_graph
    _add_case(db_session, tenant_id, spec_id, supplier_id, "No.123456-a")
    svc = SequentialNumberingService()
    assert svc.next_case_no(db_session, tenant_id) == "No.500001-a"


def test_sequential_increment(db_session: Session, minimal_graph) -> None:
    """アプリ登録済み No.500001 の次は No.500002。"""
    tenant_id, supplier_id, spec_id = minimal_graph
    _add_case(db_session, tenant_id, spec_id, supplier_id, "No.500001-a")
    svc = SequentialNumberingService()
    assert svc.next_case_no(db_session, tenant_id) == "No.500002-a"


def test_next_branch(db_session: Session, minimal_graph) -> None:
    """既存 -a に対し、再交渉の枝番は -b を返す。"""
    tenant_id, supplier_id, spec_id = minimal_graph
    _add_case(db_session, tenant_id, spec_id, supplier_id, "No.500001-a")
    svc = SequentialNumberingService()
    assert svc.next_branch(db_session, tenant_id, "No.500001-a") == "No.500001-b"


def test_prefix_applied(db_session: Session) -> None:
    """tenants.case_no_prefix が採番に付与される。"""
    import uuid

    tid = str(uuid.uuid4())
    db_session.add(m.Tenant(tenant_id=tid, tenant_name="T", case_no_prefix="FR-"))
    db_session.flush()
    svc = SequentialNumberingService()
    assert svc.next_case_no(db_session, tid) == "FR-No.500001-a"
