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


class GoogleAuthRequest(CamelModel):
    """GIS のコールバックが返す credential（ID トークン）を送る。"""

    credential: str


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
    # registered=False は「相場未登録」。価格0（実データ）と区別するため、
    # latest_price / yoy_rate 等は未登録・未算出時に None を返す（issue #3）。
    registered: bool = False  # 相場が登録済みか（未登録なら latest_price は None）
    latest_price: float | None = None  # 直近相場（未登録時 None）
    current_price: float
    yoy_rate: float | None = None  # 前年同月比（小数。例 0.032。手入力等で未算出なら None）
    year_month: str | None = None  # 対象年月 'YYYY-MM'（issue #7）
    source: str | None = None  # 出典（issue #7・登録済み時のみ）
    input_method: str | None = None  # 入力方法（手入力/CSV。issue #7 Want）
    updated_at: str | None = None  # 登録/更新日時（ISO8601。issue #7 Want）
    unit: str = "円/kg"
    normalized_count: int = 0
    note: str = ""


class RateManualInput(CamelModel):
    """手入力する相場情報（FR-02）。"""

    year_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    price_yen_kg: float = Field(gt=0)
    source: str | None = None


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


# ---- 作戦シート（AI 生成・画面④・FR-08） ------------------------------------
class StrategyPoint(CamelModel):
    text: str
    citations: list[Citation] = Field(default_factory=list)


class StrategyDraft(CamelModel):
    points: list[StrategyPoint] = Field(default_factory=list)
    scenario: str = ""


# ---- 結果記録（画面⑤・FR-11/12/13） ----------------------------------------
ReasonDirection = Literal["up", "down", "both"]


class ReasonTag(CamelModel):
    """変動理由マスタ（RC-01〜10・共有参照）。"""

    code: str
    label: str
    direction: ReasonDirection


class ResultInput(CamelModel):
    """結果記録の入力（§3.5 ResultForm）。"""

    settled_price: float
    delivery_timing: str = ""
    payment_terms: str = ""
    reason_codes: list[str] = Field(default_factory=list)  # 決着理由タグ（RC-xx・複数選択）
    note: str = ""


class ResultRecord(CamelModel):
    """保存済みの結果記録（自動計算値＝見積比/目標達成度を含む）。"""

    settled_price: float
    delivery_timing: str
    payment_terms: str
    reason_codes: list[str]
    note: str
    quote_diff_pct: float  # 見積比（%。マイナスは見積より安く決着）
    achievement_pct: float  # 目標達成度（%）
    case_no: str
    company: str
    product: str
    period: str
    saved_at: str
