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
import type { CaseSummary, CompanyPlan, ThreeLine } from "@/lib/types";

const KEY = "freeradicals.mockstore.v1";

interface StoreShape {
  cases: CaseSummary[];
  caseExtra: Record<string, { quotedPrice: number; targetPeriod: string }>;
  plans: Record<string, CompanyPlan>;
  lines: Record<string, ThreeLine[]>; // 手修正を含む確定ライン
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
  s.lines[caseNo] = lines;
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
