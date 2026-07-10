// モック用の簡易ストア
// 案件・自社計画・3ラインの手修正など、セッション中に変化する状態を保持する。
// localStorage をバックにしてリロードをまたいで永続化する（ブラウザ内のみ・デモ用）。
// 実 API 接続時（NEXT_PUBLIC_USE_MOCK=false）は使用しない。

import {
  EMPTY_PLAN,
  MOCK_CASES,
  MOCK_CASE_DETAILS,
  MOCK_PLANS,
} from "@/lib/mock/data";
import type {
  CaseStatus,
  CaseSummary,
  CompanyPlan,
  ResultRecord,
  StrategyDraft,
  ThreeLine,
  WorkspaceStep,
} from "@/lib/types";

// スキーマ拡張のため v2 にバージョンを上げる（旧 v1 の破損/欠損キーを避ける）。
const KEY = "freeradicals.mockstore.v2";

interface StoreShape {
  cases: CaseSummary[];
  caseExtra: Record<string, { quotedPrice: number; targetPeriod: string }>;
  plans: Record<string, CompanyPlan>;
  lines: Record<string, ThreeLine[]>; // 手修正を含む確定ライン
  strategies: Record<string, StrategyDraft>; // ④作戦シートの保存済み下書き
  results: Record<string, ResultRecord>; // ⑤結果記録
  lastStep: Record<string, WorkspaceStep>; // 案件ごとの最後にいたステップ（m-2）
}

function seed(): StoreShape {
  const caseExtra: StoreShape["caseExtra"] = {};
  for (const [caseNo, d] of Object.entries(MOCK_CASE_DETAILS)) {
    caseExtra[caseNo] = { quotedPrice: d.quotedPrice, targetPeriod: d.targetPeriod };
  }
  return {
    cases: [...MOCK_CASES],
    caseExtra,
    plans: { ...MOCK_PLANS },
    lines: {},
    strategies: {},
    results: {},
    lastStep: {},
  };
}

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

export function loadStore(): StoreShape {
  if (!isBrowser()) return seed();
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) {
      const s = seed();
      window.localStorage.setItem(KEY, JSON.stringify(s));
      return s;
    }
    return JSON.parse(raw) as StoreShape;
  } catch {
    return seed();
  }
}

export function saveStore(s: StoreShape): void {
  if (!isBrowser()) return;
  window.localStorage.setItem(KEY, JSON.stringify(s));
}

export function getPlan(caseNo: string): CompanyPlan {
  const s = loadStore();
  return s.plans[caseNo] ?? { ...EMPTY_PLAN };
}

export function setPlan(caseNo: string, plan: CompanyPlan): void {
  const s = loadStore();
  s.plans[caseNo] = plan;
  saveStore(s);
}

export function getLines(caseNo: string): ThreeLine[] | null {
  const s = loadStore();
  return s.lines[caseNo] ?? null;
}

export function setLines(caseNo: string, lines: ThreeLine[]): void {
  const s = loadStore();
  // 手修正済み（isEdited=true）のラインのみ永続化する。未修正ラインは保存せず、
  // 取得時に毎回そのときの相場・計画から再算出させる（3本まとめて凍結しない）。
  const edited = lines.filter((l) => l.isEdited);
  if (edited.length > 0) {
    s.lines[caseNo] = edited;
  } else {
    delete s.lines[caseNo];
  }
  saveStore(s);
}

export function getCases(): CaseSummary[] {
  return loadStore().cases;
}

export function getCaseExtra(caseNo: string): { quotedPrice: number; targetPeriod: string } {
  const s = loadStore();
  return s.caseExtra[caseNo] ?? { quotedPrice: 0, targetPeriod: "" };
}

export function addCase(summary: CaseSummary, quotedPrice: number, targetPeriod: string): void {
  const s = loadStore();
  s.cases = [summary, ...s.cases];
  s.caseExtra[summary.caseNo] = { quotedPrice, targetPeriod };
  saveStore(s);
}

/** 次の案件番号を採番する（"No.500001" → "No.500002"）。デモ用の単純採番。 */
export function nextCaseNo(): string {
  const s = loadStore();
  const nums = s.cases
    .map((c) => parseInt(c.caseNo.replace(/[^0-9]/g, ""), 10))
    .filter((n) => !Number.isNaN(n));
  const max = nums.length > 0 ? Math.max(...nums) : 500000;
  return `No.${max + 1}`;
}

// ---- ④ 作戦シート ----

export function getStrategy(caseNo: string): StrategyDraft | null {
  const s = loadStore();
  return s.strategies?.[caseNo] ?? null;
}

export function setStrategy(caseNo: string, draft: StrategyDraft): void {
  const s = loadStore();
  s.strategies = { ...(s.strategies ?? {}), [caseNo]: draft };
  saveStore(s);
}

// ---- ⑤ 結果記録 ----

export function getResult(caseNo: string): ResultRecord | null {
  const s = loadStore();
  return s.results?.[caseNo] ?? null;
}

export function setResult(caseNo: string, record: ResultRecord): void {
  const s = loadStore();
  s.results = { ...(s.results ?? {}), [caseNo]: record };
  saveStore(s);
}

/** 案件ステータスを更新する（結果保存時に "done" 化する）。 */
export function setCaseStatus(caseNo: string, status: CaseStatus): void {
  const s = loadStore();
  s.cases = s.cases.map((c) => (c.caseNo === caseNo ? { ...c, status } : c));
  saveStore(s);
}

/**
 * 判断継承（BR-10）: 同一商材×取引先で決着済みの結果を過去経緯候補として返す。
 * 自分自身の案件は除外する。②情報収集の過去経緯にこの結果が現れる。
 */
export function getPastResults(
  company: string,
  product: string,
  excludeCaseNo: string,
): ResultRecord[] {
  const s = loadStore();
  return Object.values(s.results ?? {}).filter(
    (r) => r.company === company && r.product === product && r.caseNo !== excludeCaseNo,
  );
}

// ---- 進捗（最後にいたステップ・m-2） ----

export function getLastStep(caseNo: string): WorkspaceStep {
  const s = loadStore();
  return s.lastStep?.[caseNo] ?? "collect";
}

export function setLastStep(caseNo: string, step: WorkspaceStep): void {
  const s = loadStore();
  if ((s.lastStep?.[caseNo] ?? "collect") === step) return; // 変化なしなら書かない
  s.lastStep = { ...(s.lastStep ?? {}), [caseNo]: step };
  saveStore(s);
}
