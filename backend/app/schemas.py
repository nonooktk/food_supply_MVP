"""schemas.py — API 入出力スキーマ（フロント型と1対1・camelCase）。

フロントの `frontend/src/lib/types.ts` と形を合わせる。Python 側は snake_case で定義し、
``alias_generator=to_camel`` で JSON は camelCase（例: case_no → caseNo）を入出力する。
FastAPI は既定で by_alias シリアライズするため、レスポンスは camelCase になる。
"""

from __future__ import annotations

import warnings
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from pydantic.warnings import UnsupportedFieldAttributeWarning

# FastAPI が alias_generator 付きモデルをリクエストボディとして包む際、Pydantic が
# UnsupportedFieldAttributeWarning を出す（良性・既知の相互作用。camelCase の入出力は正常）。
# 意図的に camelCase エイリアスを使うため、この良性警告のみ抑制する。
warnings.filterwarnings("ignore", category=UnsupportedFieldAttributeWarning)


class CamelModel(BaseModel):
    """camelCase エイリアス付きの基底モデル（snake_case 定義 ⇄ camelCase JSON）。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ---- 認証 --------------------------------------------------------------------
class LoginRequest(CamelModel):
    tenant: str
    user_id: str
    password: str


class AuthUser(CamelModel):
    tenant_id: str
    user_id: str
    display_name: str
    role: Literal["member", "admin"] = "member"


# ---- 案件 --------------------------------------------------------------------
CaseStatus = Literal["before", "negotiating", "done"]
WorkspaceStep = Literal["collect", "lines", "strategy", "result"]


class CaseDetail(CamelModel):
    case_no: str
    company: str
    product: str
    status: CaseStatus
    updated_at: str  # 表示用 "MM/DD"
    assignee: str
    quoted_price: float
    target_period: str
    current_step: WorkspaceStep = "collect"


class CaseListResult(CamelModel):
    items: list[CaseDetail]
    total: int


class CaseCreateInput(CamelModel):
    company: str
    product: str
    quoted_price: float
    target_period: str


class CaseStatusUpdate(CamelModel):
    status: CaseStatus


# ---- 相場 --------------------------------------------------------------------
class RateInfo(CamelModel):
    latest_price: float
    current_price: float
    yoy_rate: float  # 小数（例: 0.032 = +3.2%）
    unit: str = "円/kg"
    normalized_count: int = 0
    note: str = ""


# ---- 過去経緯（KRE / DB） ----------------------------------------------------
class Citation(CamelModel):
    case_no: str
    company: str
    product: str
    snippet: str


class PastCase(CamelModel):
    case_no: str
    company: str
    product: str
    period: str
    settled_price: float
    citations: list[Citation] = Field(default_factory=list)
    relation: Optional[Literal["same_supplier", "same_reason"]] = None


class PastCaseResult(CamelModel):
    state: Literal["ready", "empty", "error"]
    items: list[PastCase] = Field(default_factory=list)


# ---- 自社計画 ----------------------------------------------------------------
class CompanyPlan(CamelModel):
    target_cost_rate: float
    plan_price: float
    monthly_volume: float
    ceiling_price: float


# ---- 3ライン -----------------------------------------------------------------
LineType = Literal["target", "landing", "walkaway"]


class ThreeLine(CamelModel):
    type: LineType
    value: float
    auto_value: float
    is_edited: bool = False
    edit_reason: Optional[str] = None


class AnnualImpact(CamelModel):
    target_yen: float
    landing_yen: float


class ThreeLineResult(CamelModel):
    lines: list[ThreeLine] = Field(default_factory=list)
    impact: AnnualImpact
    ready: bool


class ThreeLineSaveInput(CamelModel):
    lines: list[ThreeLine]
