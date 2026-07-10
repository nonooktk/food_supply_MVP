"""rates.py — 相場情報（画面②の相場パネル・F-02）。

- GET /cases/{case_no}/rate … 当該案件のスペックの最新相場・現行単価・前年比を返す。

前年比は DB では百分率（例 3.20）で保持するため、フロント契約の小数（0.032）へ変換して返す。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_repo
from app.db.repository import TenantScopedRepository
from app.errors import ApiProblem
from app.schemas import RateInfo
from app.services.case_view import load_case
from app.services.pricing import latest_market_rate, market_rate_count

router = APIRouter(tags=["rates"])

_NOTE_WITH_DATA = "日付・%表記ゆれを自動補正済み（Jul-25→2025-07 等）"
_NOTE_NO_DATA = "相場データ未登録です。手入力または CSV 取込で登録してください。"


@router.get("/cases/{case_no}/rate", response_model=RateInfo)
def get_rate(
    case_no: str,
    repo: TenantScopedRepository = Depends(get_repo),
) -> RateInfo:
    """案件のスペックの相場情報を返す。"""
    case = load_case(repo, case_no)
    if case is None:
        raise ApiProblem(404, "案件が見つかりません", detail=f"{case_no} は存在しません。")

    latest = latest_market_rate(repo, case.spec_id)
    count = market_rate_count(repo, case.spec_id)
    current_price = float(case.current_price) if case.current_price is not None else 0.0

    if latest is None:
        return RateInfo(
            latest_price=0.0,
            current_price=current_price,
            yoy_rate=0.0,
            unit="円/kg",
            normalized_count=0,
            note=_NOTE_NO_DATA,
        )

    # DB の yoy_change は百分率（3.20 = +3.2%）。フロント契約は小数（0.032）。
    yoy_rate = float(latest.yoy_change) / 100.0 if latest.yoy_change is not None else 0.0
    return RateInfo(
        latest_price=float(latest.price_yen_kg) if latest.price_yen_kg is not None else 0.0,
        current_price=current_price,
        yoy_rate=yoy_rate,
        unit="円/kg",
        normalized_count=count,
        note=_NOTE_WITH_DATA,
    )
