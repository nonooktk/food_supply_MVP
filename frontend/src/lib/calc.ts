// 3ライン算出ロジック（純粋関数）
// 要件 F-05: 相場・計画・過去価格から目標/着地/撤退を計算式で機械的に算出（AI不使用）。
//
// 本ファイルの式は算出正本 CALC_RULE_V1（backend/app/db/seams.py L78-107）と一致させている。
//   目標(target)   = max(相場, 0.95 × 過去最安)
//   着地(landing)  = clamp(0.5×過去平均 + 0.3×計画単価 + 0.2×相場, 目標, 撤退)
//   撤退(walkaway) = min(許容上限, 現行 × (1 + max(0, 相場前年比) + 2pt)) ※下落局面は0扱い
//   欠損時はフォールバック（過去情報が無い場合は相場・現行で代替）。
// モック段階ではこの式でフロント側算出するが、実 API 接続時はバックエンドが
// 同一の CALC_RULE_V1 で算出した結果を返す（lib/api.ts の RealApi で置換）。

import type {
  AnnualImpact,
  CompanyPlan,
  PastCase,
  RateInfo,
  ThreeLine,
  ThreeLineResult,
} from "@/lib/types";

/** CALC_RULE_V1 のパラメータ（seams.py CALC_RULE_V1.params と一致） */
const LANDING_WEIGHTS = { pastAvg: 0.5, planPrice: 0.3, marketRate: 0.2 } as const;
const WALKAWAY_MARGIN_PT = 0.02; // 撤退マージン +2pt
const TARGET_PAST_MIN_RATIO = 0.95; // 目標 = max(相場, 0.95×過去最安)

/** 計画が算出に足るだけ入力されているか（デザインガイド §3.3 エラー状態） */
export function isPlanReady(plan: CompanyPlan): boolean {
  return plan.planPrice > 0 && plan.monthlyVolume > 0 && plan.ceilingPrice > 0;
}

/** x を [lo, hi] に収める（seams.py の clamp 相当）。lo>hi の異常入力時は hi を返す。 */
function clamp(x: number, lo: number, hi: number): number {
  return Math.min(Math.max(x, lo), hi);
}

/**
 * 算出に用いる「過去価格」を取り出す。
 * backend（services/pricing.past_settled_prices）を正とし、**直接一致（relation なし＝同一 spec）**の
 * 決着単価のみを過去最安・過去平均に用いる。グラフ補完（relation 付き＝同一取引先の別商材等）は
 * 数値算出に使わない。直接一致が無ければ空配列を返し、呼び出し側で相場フォールバックする
 * （backend も同一スペックの決着が無ければ相場で代替するため、front/back を一致させる）。
 */
function pastPrices(pastCases: PastCase[]): number[] {
  return pastCases.filter((c) => !c.relation).map((c) => c.settledPrice);
}

/**
 * 3本のライン（自動算出値）を CALC_RULE_V1 で計算する。
 * 欠損（過去価格なし）時は相場を過去最安・過去平均の代替に用いる。
 */
export function calcAutoLines(
  rate: RateInfo,
  plan: CompanyPlan,
  pastCases: PastCase[],
): { target: number; landing: number; walkaway: number } {
  // 未登録（latestPrice=null）・未算出（yoyRate=null）は 0 として扱う。
  // 未登録時は 3ライン算出へ進めない（rateReady=false）が、防御的に 0 フォールバックする。
  const market = rate.latestPrice ?? 0;
  const current = rate.currentPrice > 0 ? rate.currentPrice : market;
  const yoy = rate.yoyRate ?? 0;

  const prices = pastPrices(pastCases);
  const pastMin = prices.length > 0 ? Math.min(...prices) : market;
  const pastAvg =
    prices.length > 0 ? prices.reduce((a, b) => a + b, 0) / prices.length : market;

  // 目標 = max(相場, 0.95×過去最安)
  const target = Math.round(Math.max(market, TARGET_PAST_MIN_RATIO * pastMin));
  // 撤退 = min(許容上限, 現行×(1 + max(0, 相場前年比) + 2pt))
  // 下落局面（前年比<0）は 0 扱い＝撤退は常に「現行+2pt」を保つ（CALC_RULE_V1 の確定解釈）。
  const walkaway = Math.round(
    Math.min(plan.ceilingPrice, current * (1 + Math.max(0, yoy) + WALKAWAY_MARGIN_PT)),
  );
  // 着地 = clamp(0.5×過去平均 + 0.3×計画単価 + 0.2×相場, 目標, 撤退)
  const landingRaw =
    LANDING_WEIGHTS.pastAvg * pastAvg +
    LANDING_WEIGHTS.planPrice * plan.planPrice +
    LANDING_WEIGHTS.marketRate * market;
  const landing = Math.round(clamp(landingRaw, target, walkaway));

  return { target, landing, walkaway };
}

/**
 * 年間影響額の試算（対計画）。
 * 影響額 = (計画仕入単価 − ライン単価) × 年間発注量(= 月次 × 12)。
 * 計画より安く決着できるほどプラス、計画より高いとマイナス（相場上昇局面）。
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
