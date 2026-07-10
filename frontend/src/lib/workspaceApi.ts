// 画面④作戦シート・⑤結果記録 の操作層（モック先行）
//
// lib/api.ts の Api インターフェースは変更しない方針（RealApi はポリゴンが並行調整中）。
// ④⑤ 固有の操作はこの独立モジュールに置き、当面はモック実装で動かす。
// 読み取り（案件・3ライン・過去経緯）は既存の `api` を再利用し、永続化は `store` を使う。
// 実 API 接続時（NEXT_PUBLIC_USE_MOCK=false）は、ここのモック関数を Api 側へ統合する
// （その際もこのモジュールの関数シグネチャを保てば画面側は無改修で済む）。

import { api } from "@/lib/api";
import type {
  ReasonTag,
  ResultInput,
  ResultRecord,
  StrategyDraft,
  StrategySheet,
} from "@/lib/types";

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

/** 変動理由マスタ（RC-01〜10）。実装は api 側（Real=バックエンドの /reasons / Mock=RC マスタ）。 */
export async function getReasonTags(): Promise<ReasonTag[]> {
  return api.getReasonTags();
}

/** 保存済みの結果記録（実/モック両対応）。 */
export async function getResult(caseNo: string): Promise<ResultRecord | null> {
  return api.getResult(caseNo);
}

/** 見積比（%）: (決着 − 見積) / 見積 × 100。マイナスは見積より安く決着。画面のライブ計算用。 */
export function calcQuoteDiffPct(settled: number, quoted: number): number {
  if (quoted <= 0) return 0;
  return Math.round(((settled - quoted) / quoted) * 1000) / 10; // 小数第1位
}

/** 目標達成度（%）: 撤退で0%、目標で100%（目標より安ければ100%上限）。画面のライブ計算用。 */
export function calcAchievementPct(settled: number, target: number, walkaway: number): number {
  if (walkaway <= target) return settled <= target ? 100 : 0; // 帯が潰れている場合の保護
  const pct = ((walkaway - settled) / (walkaway - target)) * 100;
  return Math.max(0, Math.min(100, Math.round(pct)));
}

/**
 * 結果を保存し、案件ステータスを「完了」にする（実/モック両対応）。
 * 見積比・目標達成度はサーバー側（Real）で算出される。保存結果は判断継承（BR-10）で
 * 同一スペックの新案件の過去経緯に現れる。
 */
export async function saveResult(caseNo: string, input: ResultInput): Promise<ResultRecord> {
  return api.saveResult(caseNo, input);
}
