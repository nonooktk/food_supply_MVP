// ドメイン型定義
// 要件定義書 v3 §2（F-01/02/04/05）・デザインガイド §3〜§4 に対応。
// バックエンド API（ポリゴン並行実装中）と形を合わせるための共通の型置き場。

/** 案件ステータス（デザインガイド §4.6 StatusBadge） */
export type CaseStatus = "before" | "negotiating" | "done";

/** 案件ワークスペースのステップ（デザインガイド §2.2） */
export type WorkspaceStep = "collect" | "lines" | "strategy" | "result";

/** 認証済みユーザー（モック認証。Entra は Sprint 2） */
export interface AuthUser {
  tenantId: string;
  userId: string;
  displayName: string;
  role: "member" | "admin";
}

/** 案件一覧の1行（デザインガイド §3.1 DataTable） */
export interface CaseSummary {
  caseNo: string; // 例: "No.500001"
  company: string; // 取引先企業
  product: string; // 商材（規格含む表示名）
  status: CaseStatus;
  updatedAt: string; // "07/09" などの表示用
  assignee: string; // 担当者名
}

/** 案件作成フォームの入力（デザインガイド §3.1 作成モーダル / FR-01） */
export interface CaseCreateInput {
  supplierId: number;
  product: string;
  quotedPrice: number; // 提出見積（円/kg）
  targetPeriod: string; // 交渉時期
}

/** 案件作成時に選択する取引先マスタ。 */
export interface Supplier {
  supplierId: number;
  supplierName: string;
  supplierCategory: string | null;
  supplierMemo: string | null;
}

/** 案件詳細（ワークスペースのヘッダー表示に使用） */
export interface CaseDetail extends CaseSummary {
  quotedPrice: number;
  targetPeriod: string;
  currentStep: WorkspaceStep; // 最後にいたステップ
}

/** 相場情報（デザインガイド §3.2 相場情報パネル / F-02）
 *  latestPrice・currentPrice・yoyRate は 3ライン算出式 CALC_RULE_V1
 *  （backend/app/db/seams.py）の入力（market_rate / current_price / yoy_rate）に対応する。 */
export interface RateInfo {
  registered: boolean; // 相場が登録済みか（false=未登録。価格0と区別する。issue #3）
  latestPrice: number | null; // 直近相場 market_rate（円/kg。未登録時 null）
  currentPrice: number; // 現行仕入単価 current_price（円/kg。撤退ライン算出に使用）
  yoyRate: number | null; // 相場前年同月比 yoy_rate（小数。例: 0.03 = +3%。未算出時 null）
  yearMonth?: string | null; // 対象年月 'YYYY-MM'（issue #7）
  source?: string | null; // 出典（issue #7・登録済み時のみ）
  inputMethod?: string | null; // 入力方法（手入力/CSV。issue #7 Want）
  updatedAt?: string | null; // 登録/更新日時（ISO8601。issue #7 Want）
  unit: string; // "円/kg"
  normalizedCount: number; // CSV取込で正規化した件数
  note: string; // 補足（表記ゆれ補正など）
}

/** 手入力する相場情報（FR-02）。出典は将来の根拠表示・AI 連携用に保存する。 */
export interface RateManualInput {
  yearMonth: string; // YYYY-MM
  priceYenKg: number;
  source?: string;
}

/** 過去経緯の引用元（デザインガイド §4.4 CitationBadge / KRE RetrieveResult.citations 相当） */
export interface Citation {
  caseNo: string;
  company: string;
  product: string;
  snippet: string; // 該当箇所の要約
}

/** 過去案件1件（デザインガイド §3.2 PastCaseList / F-03・KRE スタブ相当） */
export interface PastCase {
  caseNo: string;
  company: string;
  product: string;
  period: string; // "2026Q1" など
  settledPrice: number; // 決着単価（円/kg）
  citations: Citation[];
  relation?: "same_supplier" | "same_reason"; // グラフ補完の種別（§5.4）
}

/** 過去経緯パネルの状態（部分エラー・空対応。デザインガイド §3.2） */
export interface PastCaseResult {
  state: "ready" | "empty" | "error";
  items: PastCase[];
}

/** 自社計画（デザインガイド §3.2 CompanyPlanForm / F-04） */
export interface CompanyPlan {
  targetCostRate: number; // 目標原価率（%）
  planPrice: number; // 計画仕入単価（円/kg）
  monthlyVolume: number; // 月次発注量（kg）
  ceilingPrice: number; // 許容上限（円/kg）
}

/** 3ラインの種別（デザインガイド §4.3 ThreeLineCard） */
export type LineType = "target" | "landing" | "walkaway";

/** 3ラインの1本 */
export interface ThreeLine {
  type: LineType;
  value: number; // 円/kg
  autoValue: number; // 自動算出値（手修正前の値。差分表示・リセット用）
  isEdited: boolean; // 手修正済みか
  editReason?: string; // 手修正時は必須（デザインガイド §3.3）
}

/** 年間影響額試算（デザインガイド §3.3 AnnualImpactSummary） */
export interface AnnualImpact {
  targetYen: number; // 目標達成時の対計画・年間影響額（円）
  landingYen: number; // 着地時の対計画・年間影響額（円）
}

/** 3ライン算出結果 */
export interface ThreeLineResult {
  lines: ThreeLine[];
  impact: AnnualImpact;
  ready: boolean; // 算出に必要な入力（②自社計画等）が揃っているか
}

// ---- 画面④ 作戦シート（デザインガイド §3.4 / FR-07・FR-08） ----

/** 型帳票（定型フォーマット）に流し込む案件サマリ（§3.4 StrategySheetPreview） */
export interface PastSummaryItem {
  caseNo: string;
  company: string;
  product: string;
  period: string;
  settledPrice: number;
}

export interface StrategySheet {
  caseNo: string;
  company: string;
  product: string;
  quotedPrice: number;
  targetPeriod: string;
  lines: ThreeLine[]; // 3ライン（③の結果）
  impact: AnnualImpact; // 年間影響額
  pastSummary: PastSummaryItem[]; // 過去経緯サマリ
}

/** AI 生成の交渉ポイント1件（引用元を必ず併設。§4.4） */
export interface StrategyPoint {
  text: string;
  citations: Citation[];
}

/** AI 下書き（交渉ポイント＋編集可能なシナリオ文。§3.4） */
export interface StrategyDraft {
  points: StrategyPoint[];
  scenario: string;
}

// ---- 画面⑤ 結果記録（デザインガイド §3.5 / FR-11・FR-12・FR-13） ----

/** 変動理由タグの向き（↑上げ要因 / ↓下げ要因 / ±両方向。色ではなく矢印で示す・§3.5） */
export type ReasonDirection = "up" | "down" | "both";

/** 変動理由マスタ（RC-01〜10。§3.5 ReasonTagSelector） */
export interface ReasonTag {
  code: string;
  label: string;
  direction: ReasonDirection;
}

/** 結果記録の入力（§3.5 ResultForm） */
export interface ResultInput {
  settledPrice: number; // 決着単価（円/kg）
  deliveryTiming: string; // 納入時期
  paymentTerms: string; // 支払条件
  reasonCodes: string[]; // 決着理由タグ（複数選択・必須）
  note: string; // 所感・申し送り
}

/** 自動計算値（§3.5 AutoCalcField） */
export interface ResultCalc {
  quoteDiffPct: number; // 見積比（%。マイナスは見積より安く決着）
  achievementPct: number; // 目標達成度（%）
}

/** 保存済みの結果記録 */
export interface ResultRecord extends ResultInput, ResultCalc {
  caseNo: string;
  company: string;
  product: string;
  period: string; // 交渉時期（判断継承で過去経緯として参照される）
  savedAt: string;
}
