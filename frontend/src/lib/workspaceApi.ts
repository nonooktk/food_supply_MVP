// 画面④作戦シート・⑤結果記録 の操作層（モック先行）
//
// lib/api.ts の Api インターフェースは変更しない方針（RealApi はポリゴンが並行調整中）。
// ④⑤ 固有の操作はこの独立モジュールに置き、当面はモック実装で動かす。
// 読み取り（案件・3ライン・過去経緯）は既存の `api` を再利用し、永続化は `store` を使う。
// 実 API 接続時（NEXT_PUBLIC_USE_MOCK=false）は、ここのモック関数を Api 側へ統合する
// （その際もこのモジュールの関数シグネチャを保てば画面側は無改修で済む）。

import { api } from "@/lib/api";
import * as store from "@/lib/store";
import { MOCK_REASON_TAGS } from "@/lib/mock/data";
import type {
  ReasonTag,
  ResultInput,
  ResultRecord,
  StrategyDraft,
  StrategySheet,
} from "@/lib/types";

const USE_MOCK = process.env.NEXT_PUBLIC_USE_MOCK !== "false";

function assertMock(feature: string): void {
  if (!USE_MOCK) {
    // 実 API 未接続時は黙って動かさず、明示的に失敗させる（ポリゴンが RealApi 調整中）。
    throw new Error(`${feature} の実 API は未接続です（NEXT_PUBLIC_USE_MOCK=true で利用可）。`);
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** ④ 型帳票に流し込む案件サマリを組み立てる（既存 api の読み取りを再利用・実/モック両対応）。 */
export async function getStrategySheet(caseNo: string): Promise<StrategySheet> {
  const [detail, lines, past] = await Promise.all([
    api.getCase(caseNo),
    api.getThreeLines(caseNo),
    api.getPastCases(caseNo),
  ]);
  return {
    caseNo: detail.caseNo,
    company: detail.company,
    product: detail.product,
    quotedPrice: detail.quotedPrice,
    targetPeriod: detail.targetPeriod,
    lines: lines.lines,
    impact: lines.impact,
    pastSummary:
      past.state === "ready"
        ? past.items.map((p) => ({
            caseNo: p.caseNo,
            company: p.company,
            product: p.product,
            period: p.period,
            settledPrice: p.settledPrice,
          }))
        : [],
  };
}

/** 保存済みの作戦シート下書き（実/モック両対応。実 API はポリゴンが api.ts に実装）。 */
export async function getStrategyDraft(caseNo: string): Promise<StrategyDraft | null> {
  return api.getStrategyDraft(caseNo);
}

/**
 * FR-08 交渉ポイント・シナリオの AI 生成。
 * 実装は api 側に統合済み（RealApi=バックエンドの実 AI 生成 / MockApi=過去経緯・3ラインからの下書き）。
 * 段階的な進捗表示は呼び出し側（AiGenerationPanel）が担う。
 */
export async function generateStrategy(caseNo: string): Promise<StrategyDraft> {
  return api.generateStrategy(caseNo);
}

/** 作戦シート下書きを保存する（実/モック両対応）。 */
export async function saveStrategyDraft(caseNo: string, draft: StrategyDraft): Promise<void> {
  return api.saveStrategyDraft(caseNo, draft);
}

// ---- ⑤ 結果記録 ----

/** 変動理由マスタ（RC-01〜10）。 */
export async function getReasonTags(): Promise<ReasonTag[]> {
  assertMock("結果記録");
  await delay(100);
  return MOCK_REASON_TAGS;
}

/** 保存済みの結果記録。 */
export async function getResult(caseNo: string): Promise<ResultRecord | null> {
  assertMock("結果記録");
  await delay(150);
  return store.getResult(caseNo);
}

/** 見積比（%）: (決着 − 見積) / 見積 × 100。マイナスは見積より安く決着。 */
export function calcQuoteDiffPct(settled: number, quoted: number): number {
  if (quoted <= 0) return 0;
  return Math.round(((settled - quoted) / quoted) * 1000) / 10; // 小数第1位
}

/** 目標達成度（%）: 撤退で0%、目標で100%（目標より安ければ100%上限）。 */
export function calcAchievementPct(settled: number, target: number, walkaway: number): number {
  if (walkaway <= target) return settled <= target ? 100 : 0; // 帯が潰れている場合の保護
  const pct = ((walkaway - settled) / (walkaway - target)) * 100;
  return Math.max(0, Math.min(100, Math.round(pct)));
}

/**
 * 結果を保存し、案件ステータスを「完了」にする。
 * 保存した結果は判断継承（BR-10）で同一商材×取引先の新案件の過去経緯に現れる。
 */
export async function saveResult(caseNo: string, input: ResultInput): Promise<ResultRecord> {
  assertMock("結果記録");
  await delay(400);

  const [detail, lines] = await Promise.all([api.getCase(caseNo), api.getThreeLines(caseNo)]);
  const target = lines.lines.find((l) => l.type === "target")?.value ?? detail.quotedPrice;
  const walkaway = lines.lines.find((l) => l.type === "walkaway")?.value ?? detail.quotedPrice;

  const record: ResultRecord = {
    ...input,
    caseNo,
    company: detail.company,
    product: detail.product,
    period: detail.targetPeriod,
    quoteDiffPct: calcQuoteDiffPct(input.settledPrice, detail.quotedPrice),
    achievementPct: calcAchievementPct(input.settledPrice, target, walkaway),
    savedAt: new Date().toISOString(),
  };

  store.setResult(caseNo, record);
  store.setCaseStatus(caseNo, "done"); // 案件を完了化（①一覧の StatusBadge が緑✓に）
  return record;
}
