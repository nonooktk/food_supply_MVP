"use client";

// AiGenerationPanel（デザインガイド §4.5）— 枠のみ（画面④作戦シート用。本スプリントでは枠を用意）
// 状態遷移: idle → searching → building_context → generating → done / error
// role="status" aria-live="polite" で進捗をスクリーンリーダーへ通知。
// タイムアウト（目安30秒）で error へ。生成結果には「🤖 AI下書き・要確認」バッジ＋CitationBadge を併設。
import { useCallback, useState } from "react";
import type { Citation } from "@/lib/types";
import { Button } from "./Button";
import { CitationBadge } from "./CitationBadge";

type GenState = "idle" | "searching" | "building_context" | "generating" | "done" | "error";

const STEP_LABEL: Record<Exclude<GenState, "idle" | "done" | "error">, string> = {
  searching: "過去事例を検索中…",
  building_context: "関連する交渉の文脈を構築中…",
  generating: "交渉シナリオを生成中…",
};

const STEP_ORDER: GenState[] = ["searching", "building_context", "generating"];

interface Props {
  /** 実際の生成処理（未接続の間はダミー）。resolve で結果を返す。 */
  onGenerate?: () => Promise<{ points: string[]; citations: Citation[] }>;
}

/** 本スプリントは枠のみ。onGenerate 未指定時はデモ用のダミー生成でステップ表示を確認できる。 */
async function dummyGenerate(): Promise<{ points: string[]; citations: Citation[] }> {
  return {
    points: [
      "交渉ポイント1: 為替影響を踏まえた根拠提示",
      "交渉ポイント2: 長期契約による数量メリット訴求",
    ],
    citations: [
      {
        caseNo: "No.499801",
        company: "丸紅畜産",
        product: "鶏もも肉（ブラジル産・冷凍）",
        snippet: "為替影響を根拠に据え置きで決着。",
      },
    ],
  };
}

export function AiGenerationPanel({ onGenerate }: Props) {
  const [state, setState] = useState<GenState>("idle");
  const [result, setResult] = useState<{ points: string[]; citations: Citation[] } | null>(null);

  const run = useCallback(async () => {
    setResult(null);
    // ステップ表示（体感の進捗）。実処理は onGenerate（未接続時は dummy）。
    setState("searching");
    await new Promise((r) => setTimeout(r, 700));
    setState("building_context");
    await new Promise((r) => setTimeout(r, 700));
    setState("generating");
    try {
      const gen = await (onGenerate ?? dummyGenerate)();
      setResult(gen);
      setState("done");
    } catch {
      setState("error");
    }
  }, [onGenerate]);

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-lg font-semibold text-slate-900">交渉ポイント・シナリオ（AI生成）</h3>
        <span className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">
          🤖 AI下書き・要確認
        </span>
      </div>

      {state === "idle" && (
        <Button onClick={run}>AIで交渉ポイントを生成する</Button>
      )}

      {(state === "searching" || state === "building_context" || state === "generating") && (
        <div role="status" aria-live="polite" className="space-y-2">
          {STEP_ORDER.map((s) => {
            const idx = STEP_ORDER.indexOf(s);
            const curIdx = STEP_ORDER.indexOf(state);
            const active = idx === curIdx;
            const done = idx < curIdx;
            return (
              <div
                key={s}
                className={`flex items-center gap-2 text-sm ${
                  active ? "text-indigo-700" : done ? "text-slate-400" : "text-slate-300"
                }`}
              >
                <span
                  className={`h-2 w-2 rounded-full ${
                    active ? "animate-pulse bg-indigo-600" : done ? "bg-slate-300" : "bg-slate-200"
                  }`}
                  aria-hidden="true"
                />
                {STEP_LABEL[s as keyof typeof STEP_LABEL]}
              </div>
            );
          })}
        </div>
      )}

      {state === "error" && (
        <div className="space-y-3">
          <p className="text-sm text-red-600">生成に失敗しました。もう一度お試しください。</p>
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={run}>
              再試行
            </Button>
          </div>
        </div>
      )}

      {state === "done" && result && (
        <div className="space-y-3">
          <ul className="space-y-2">
            {result.points.map((p, i) => (
              <li key={i} className="flex items-start justify-between gap-3 text-sm text-slate-700">
                <span>・{p}</span>
              </li>
            ))}
          </ul>
          <div className="flex items-center gap-2">
            <CitationBadge citations={result.citations} />
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={run}>
              🔁 再生成
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
