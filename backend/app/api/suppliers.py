"""suppliers.py — 案件作成で選択する取引先マスタ。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_repo
from app.db import models as m
from app.db.repository import TenantScopedRepository
from app.schemas import SupplierInfo

router = APIRouter(tags=["suppliers"])


@router.get("/suppliers", response_model=list[SupplierInfo])
def list_suppliers(repo: TenantScopedRepository = Depends(get_repo)) -> list[SupplierInfo]:
    """自テナントで登録済みの取引先だけを返す。"""
    suppliers = repo.list(m.Supplier)
    suppliers.sort(key=lambda supplier: supplier.supplier_name)
    return [
        SupplierInfo(
            supplier_id=supplier.supplier_id,
            supplier_name=supplier.supplier_name,
            supplier_category=supplier.supplier_category,
            supplier_memo=supplier.supplier_memo,
        )
        for supplier in suppliers
    ]
