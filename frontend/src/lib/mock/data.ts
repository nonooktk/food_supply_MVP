// モックデータ（fixture）
// RFP サンプル（鶏もも肉／丸紅畜産・¥620/kg 等）に合わせて現実的に用意する。
// バックエンド API 未完成のため、当面フロントはこのデータで動く（NEXT_PUBLIC_USE_MOCK=true）。

import type {
  CaseDetail,
  CaseSummary,
  Citation,
  CompanyPlan,
  PastCase,
  RateInfo,
  ReasonTag,
} from "@/lib/types";

/** 案件一覧の初期データ（デザインガイド §3.1 のサンプル行を踏襲） */
export const MOCK_CASES: CaseSummary[] = [
  {
    caseNo: "No.500001",
    company: "丸紅畜産",
    product: "鶏もも肉（ブラジル産・冷凍）",
    status: "negotiating",
    updatedAt: "07/09",
    assignee: "田中",
  },
  {
    caseNo: "No.499998",
    company: "伊藤忠食品",
    product: "豚バラ（デンマーク産・冷凍）",
    status: "before",
    updatedAt: "07/08",
    assignee: "佐藤",
  },
  {
    caseNo: "No.499987",
    company: "日本ハム商事",
    product: "牛肩ロース（豪州産・チルド）",
    status: "done",
    updatedAt: "07/01",
    assignee: "田中",
  },
  {
    // No.500001 の過去経緯で「決着 ¥415/kg」として引用される案件。決着済みのため done。
    caseNo: "No.499960",
    company: "丸紅畜産",
    product: "鶏むね肉（ブラジル産・冷凍）",
    status: "done",
    updatedAt: "06/28",
    assignee: "鈴木",
  },
  {
    caseNo: "No.499921",
    company: "三菱食品",
    product: "冷凍ポテト（オランダ産）",
    status: "done",
    updatedAt: "06/20",
    assignee: "佐藤",
  },
  {
    // No.500001 の過去経緯で「決着 ¥598/kg」として引用される同一商材×取引先の決着済み案件。
    // 引用元をたどると done ステータスの案件に到達する（m-4 整合）。
    caseNo: "No.499801",
    company: "丸紅畜産",
    product: "鶏もも肉（ブラジル産・冷凍）",
    status: "done",
    updatedAt: "02/12",
    assignee: "田中",
  },
];

/** 案件詳細（ワークスペースヘッダー用）。一覧に無い項目を補完する。 */
export const MOCK_CASE_DETAILS: Record<string, Omit<CaseDetail, keyof CaseSummary>> = {
  "No.500001": { quotedPrice: 620, targetPeriod: "2026Q3", currentStep: "collect" },
  "No.499998": { quotedPrice: 780, targetPeriod: "2026Q3", currentStep: "collect" },
  "No.499987": { quotedPrice: 1580, targetPeriod: "2026Q2", currentStep: "result" },
  "No.499960": { quotedPrice: 430, targetPeriod: "2025Q4", currentStep: "result" },
  "No.499921": { quotedPrice: 340, targetPeriod: "2026Q2", currentStep: "result" },
  "No.499801": { quotedPrice: 620, targetPeriod: "2026Q1", currentStep: "result" },
};

/** 相場情報（案件番号 → 相場）。デザインガイド §3.2 のサンプル ¥620/kg。
 *  currentPrice（現行仕入単価）・yoyRate（相場前年比）は CALC_RULE_V1 の撤退ライン算出に使用。 */
export const MOCK_RATES: Record<string, RateInfo> = {
  "No.500001": {
    latestPrice: 620,
    currentPrice: 610, // 現行の仕入単価
    yoyRate: 0.03, // 相場前年比 +3%（上昇局面）
    unit: "円/kg",
    normalizedCount: 12,
    note: "日付・%表記ゆれを自動補正済み（Jul-25→2025-07 等）",
  },
  "No.499998": {
    latestPrice: 780,
    currentPrice: 770,
    yoyRate: 0.04,
    unit: "円/kg",
    normalizedCount: 8,
    note: "日付・%表記ゆれを自動補正済み",
  },
  "No.499960": {
    latestPrice: 430,
    currentPrice: 420,
    yoyRate: 0.02,
    unit: "円/kg",
    normalizedCount: 10,
    note: "日付・%表記ゆれを自動補正済み",
  },
};

/** 過去経緯（案件番号 → 過去案件）。KRE スタブ相当のモック。
 *  同一取引先の別商材（same_supplier）をグラフ補完として含める（要件 §5.4 受け入れ条件3）。 */
export const MOCK_PAST_CASES: Record<string, PastCase[]> = {
  "No.500001": [
    {
      caseNo: "No.499801",
      company: "丸紅畜産",
      product: "鶏もも肉（ブラジル産・冷凍）",
      period: "2026Q1",
      settledPrice: 598,
      relation: undefined,
      citations: [
        {
          caseNo: "No.499801",
          company: "丸紅畜産",
          product: "鶏もも肉（ブラジル産・冷凍）",
          snippet: "為替影響を根拠に据え置きで決着。決着単価 ¥598/kg（見積比 -3.5%）。",
        },
        {
          caseNo: "No.499801",
          company: "丸紅畜産",
          product: "鶏もも肉（ブラジル産・冷凍）",
          snippet: "長期契約（年間96,000kg）を条件に数量メリットを訴求。",
        },
      ],
    },
    {
      caseNo: "No.499960",
      company: "丸紅畜産",
      product: "鶏むね肉（ブラジル産・冷凍）",
      period: "2025Q4",
      settledPrice: 415,
      relation: "same_supplier",
      citations: [
        {
          caseNo: "No.499960",
          company: "丸紅畜産",
          product: "鶏むね肉（ブラジル産・冷凍）",
          snippet: "同一取引先の別商材。需給逼迫下でも数量拡大で ¥415/kg に抑制。",
        },
      ],
    },
  ],
  // No.499998（伊藤忠食品・豚バラ）は過去取引なし → 空状態のデモ
  "No.499998": [],
};

/** 自社計画の初期値（案件番号 → 計画）。②で保存すると③の算出に反映される。 */
export const MOCK_PLANS: Record<string, CompanyPlan> = {
  "No.500001": {
    targetCostRate: 30,
    planPrice: 615,
    monthlyVolume: 8000,
    ceilingPrice: 625,
  },
  "No.499960": {
    targetCostRate: 28,
    planPrice: 425,
    monthlyVolume: 6000,
    ceilingPrice: 440,
  },
};

/** 空の自社計画（未入力状態のデフォルト） */
export const EMPTY_PLAN: CompanyPlan = {
  targetCostRate: 0,
  planPrice: 0,
  monthlyVolume: 0,
  ceilingPrice: 0,
};

/** モック認証で受理する資格情報（デモ用。実認証は Entra・Sprint 2）。 */
export const MOCK_CREDENTIAL = {
  tenant: "freeradicals",
  userId: "tanaka",
  password: "demo1234",
};

/** ログイン成功時に返すユーザー */
export const MOCK_AUTH_USER = {
  tenantId: "freeradicals",
  userId: "tanaka",
  displayName: "田中 太郎",
  role: "member" as const,
};

/** Citation を過去案件から平坦化して取り出すヘルパ */
export function flattenCitations(cases: PastCase[]): Citation[] {
  return cases.flatMap((c) => c.citations);
}

/** 変動理由マスタ（RC-01〜10。デザインガイド §3.5 ReasonTagSelector）。
 *  方向は色ではなく矢印記号（↑上げ要因 / ↓下げ要因 / ±両方向）で示す。 */
export const MOCK_REASON_TAGS: ReasonTag[] = [
  { code: "RC-01", label: "為替変動", direction: "up" },
  { code: "RC-02", label: "需給逼迫", direction: "up" },
  { code: "RC-03", label: "原油・燃料高", direction: "up" },
  { code: "RC-04", label: "長期契約", direction: "down" },
  { code: "RC-05", label: "数量拡大", direction: "down" },
  { code: "RC-06", label: "相見積・競合提示", direction: "down" },
  { code: "RC-07", label: "品質・規格調整", direction: "both" },
  { code: "RC-08", label: "季節・天候要因", direction: "both" },
  { code: "RC-09", label: "在庫・生産調整", direction: "both" },
  { code: "RC-10", label: "為替安定・円高", direction: "down" },
];
