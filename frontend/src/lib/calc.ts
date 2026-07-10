// 3ライン算出ロジック（純粋関数）
// 要件 F-05: 相場・計画・過去価格から目標/着地/撤退を計算式で自動算出（AI不使用・単純計算式）。
// 算出式はサーバー側処理だが、モック段階ではフロントで同等の式を実装する。
// 実 API 接続時はこの結果をバックエンドが返す（lib/api.ts の real 実装で置換）。

import type {
  AnnualImpact,
  CompanyPlan,
  PastCase,
  RateInfo,
  ThreeLine,
  ThreeLineResult,
} from "@/lib/types";

/** 計画が算出に足るだけ入力されているか（デザインガイド §3.3 エラー状態） */
export function isPlanReady(plan: CompanyPlan): boolean {
  return plan.planPrice > 0 && plan.monthlyVolume > 0 && plan.ceilingPrice > 0;
}

/**
 * 3本のライン（自動算出値）を計算する。
 * - 目標(target)   = min(計画仕入単価, 直近の過去決着) の 3% 引き（安全に進めてよい水準）
 * - 着地(landing)  = 過去決着 0.7 + 相場 0.3 の加重平均（現実的な落とし所）
 * - 撤退(walkaway) = 許容上限（これ以上譲れない境界）
 * ※ 過去決着が無い場合は相場を代替に用いる。
 */
export function calcAutoLines(
  rate: RateInfo,
  plan: CompanyPlan,
  pastCases: PastCase[],
): { target: number; landing: number; walkaway: number } {
  const market = rate.latestPrice;
  const latestPast = pastCases.length > 0 ? pastCases[0].settledPrice : market;

  const target = Math.round(Math.min(plan.planPrice, latestPast) * 0.97);
  const landing = Math.round(latestPast * 0.7 + market * 0.3);
  const walkaway = plan.ceilingPrice;

  return { target, landing, walkaway };
}

/**
 * 年間影響額の試算（対計画）。
 * 影響額 = (計画仕入単価 − ライン単価) × 年間発注量(= 月次 × 12)。
 * 計画より安く決着できるほどプラス。
 */
export function calcAnnualImpact(
  plan: CompanyPlan,
  target: number,
  landing: number,
): AnnualImpact {
  const annualVolume = plan.monthlyVolume * 12;
  return {
    targetYen: (plan.planPrice - target) * annualVolume,
    landingYen: (plan.planPrice - landing) * annualVolume,
  };
}

/** 自動算出値から ThreeLineResult を組み立てる（手修正は未反映の初期状態） */
export function buildThreeLineResult(
  rate: RateInfo,
  plan: CompanyPlan,
  pastCases: PastCase[],
): ThreeLineResult {
  if (!isPlanReady(plan)) {
    return { lines: [], impact: { targetYen: 0, landingYen: 0 }, ready: false };
  }

  const auto = calcAutoLines(rate, plan, pastCases);
  const lines: ThreeLine[] = [
    { type: "target", value: auto.target, autoValue: auto.target, isEdited: false },
    { type: "landing", value: auto.landing, autoValue: auto.landing, isEdited: false },
    { type: "walkaway", value: auto.walkaway, autoValue: auto.walkaway, isEdited: false },
  ];
  const impact = calcAnnualImpact(plan, auto.target, auto.landing);
  return { lines, impact, ready: true };
}

/** 万円表示（年間影響額サマリ用）。四捨五入して "+123" のような符号付き文字列を返す。 */
export function toManYen(yen: number): string {
  const man = Math.round(yen / 10000);
  const sign = man > 0 ? "+" : "";
  return `${sign}${man.toLocaleString("ja-JP")}`;
}
