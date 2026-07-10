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

/** ④ 型帳票に流し込む案件サマリを組み立てる（既存 api の読み取りを再利用）。 */
export async function getStrategySheet(caseNo: string): Promise<StrategySheet> {
  assertMock("作戦シート");
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

/** 保存済みの作戦シート下書き。 */
export async function getStrategyDraft(caseNo: string): Promise<StrategyDraft | null> {
  assertMock("作戦シート");
  await delay(150);
  return store.getStrategy(caseNo);
}

/**
 * FR-08 交渉ポイント・シナリオの AI 生成（モックのシミュレーション）。
 * 実 AI 未接続のため、過去経緯・3ラインから現実的な下書きを組み立てて返す。
 * 段階的な進捗表示は呼び出し側（AiGenerationPanel）が担うため、ここは生成本体のみ。
 */
export async function generateStrategy(caseNo: string): Promise<StrategyDraft> {
  assertMock("作戦シート");
  // 検索→文脈構築→生成の処理実態に合わせて少し待つ（体感の生成時間）。
  await delay(900);

  const [detail, lines, past] = await Promise.all([
    api.getCase(caseNo),
    api.getThreeLines(caseNo),
    api.getPastCases(caseNo),
  ]);

  const target = lines.lines.find((l) => l.type === "target")?.value ?? detail.quotedPrice;
  const walkaway = lines.lines.find((l) => l.type === "walkaway")?.value ?? detail.quotedPrice;
  const pastItems = past.state === "ready" ? past.items : [];
  const direct = pastItems.find((p) => !p.relation);
  const neighbor = pastItems.find((p) => p.relation === "same_supplier");

  const points: StrategyDraft["points"] = [];

  // ポイント1: 相場・為替を踏まえた根拠提示（直近相場が提出見積を裏付ける）
  points.push({
    text: `為替・相場動向を根拠に提示見積の妥当性を確認し、目標 ¥${target.toLocaleString(
      "ja-JP",
    )}/kg を起点に交渉する。撤退 ¥${walkaway.toLocaleString("ja-JP")}/kg を超える提示には応じない。`,
    citations: direct ? direct.citations : [],
  });

  // ポイント2: 過去決着の実績を引き合いに出す（直接一致の過去案件があれば引用）
  if (direct) {
    points.push({
      text: `前回（${direct.caseNo}）は ¥${direct.settledPrice.toLocaleString(
        "ja-JP",
      )}/kg で決着。同水準を基準に、急な値上げには前回条件との整合を求める。`,
      citations: direct.citations,
    });
  }

  // ポイント3: 数量メリット／長期契約の訴求（同一取引先の別商材の実績があれば補強）
  points.push({
    text: `年間発注量を背景に数量メリット・長期契約を訴求する。${
      neighbor
        ? `同一取引先の別商材（${neighbor.caseNo}・¥${neighbor.settledPrice.toLocaleString(
            "ja-JP",
          )}/kg）でも数量拡大で単価を抑えた実績がある。`
        : ""
    }`,
    citations: neighbor ? neighbor.citations : [],
  });

  const scenario =
    `${detail.company}との${detail.product}交渉。まず相場・為替を根拠に提示見積の水準を確認し、` +
    `目標 ¥${target.toLocaleString("ja-JP")}/kg を提示する。相手の値上げ要求には前回決着` +
    `${direct ? `（${direct.caseNo}・¥${direct.settledPrice.toLocaleString("ja-JP")}/kg）` : ""}` +
    `との整合を求めつつ、年間数量・長期契約を条件に単価抑制を交渉する。` +
    `撤退ライン ¥${walkaway.toLocaleString("ja-JP")}/kg を超える場合は持ち帰り再検討とする。`;

  return { points, scenario };
}

/** 作戦シート下書きを保存する。 */
export async function saveStrategyDraft(caseNo: string, draft: StrategyDraft): Promise<void> {
  assertMock("作戦シート");
  await delay(300);
  store.setStrategy(caseNo, draft);
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
