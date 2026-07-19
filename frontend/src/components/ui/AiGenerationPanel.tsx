"use client";

// AiGenerationPanel（デザインガイド §4.5 / 画面④ FR-08）
// 交渉ポイント・シナリオの AI 生成フロー本体。
// 状態遷移: idle → searching → building_context → generating → done / error
// - role="status" aria-live="polite" で進捗をスクリーンリーダーへ通知。
// - タイムアウト（目安30秒）で error へ遷移し「時間がかかっています」を出す。
// - 生成結果には常に「🤖 AI下書き・要確認」バッジ＋各ポイントに CitationBadge を併設。
// - 生成後はシナリオ文を編集可能にし、[🔁再生成][この内容で保存] を出す。
import { useCallback, useEffect, useState } from "react";
import type { StrategyDraft } from "@/lib/types";
import { Button } from "./Button";
import { CitationBadge } from "./CitationBadge";

type GenState = "idle" | "searching" | "building_context" | "generating" | "done" | "error";

const STEP_LABEL: Record<"searching" | "building_context" | "generating", string> = {
  searching: "過去事例を検索中…",
  building_context: "関連する交渉の文脈を構築中…",
  generating: "交渉シナリオを生成中…",
};
const STEP_ORDER: ("searching" | "building_context" | "generating")[] = [
  "searching",
  "building_context",
  "generating",
];

const TIMEOUT_MS = 30000;

interface Props {
  onGenerate: () => Promise<StrategyDraft>;
  onSave: (draft: StrategyDraft) => Promise<void>;
  /** 既に保存済みの下書きがあれば done 状態で復元する。 */
  initial?: StrategyDraft | null;
}

export function AiGenerationPanel({ onGenerate, onSave, initial }: Props) {
  const [state, setState] = useState<GenState>(initial ? "done" : "idle");
  const [draft, setDraft] = useState<StrategyDraft | null>(initial ?? null);
  const [scenario, setScenario] = useState(initial?.scenario ?? "");
  const [timedOut, setTimedOut] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedMsg, setSavedMsg] = useState(false);

  // 保存済み下書きが後から届いた場合の復元（外部データからの初期同期のための意図的な setState）
  useEffect(() => {
    if (initial) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setDraft(initial);
      setScenario(initial.scenario);
      setState("done");
    }
  }, [initial]);

  const run = useCallback(async () => {
    setSavedMsg(false);
    setTimedOut(false);
    try {
      // 体感短縮: 実生成（4〜5秒）を段階演出の「前」に直列で待たず、クリック直後に即時開始し
      // 段階表示アニメーション（各700ms）と並行させる。これで演出ぶん（約1.4秒）の純増待ちを
      // 実処理に重ねられる。生成ロジック・数値捏造ガードは onGenerate 側のままで一切変更しない。
      const timeout = new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error("timeout")), TIMEOUT_MS),
      );
      const genPromise = Promise.race([onGenerate(), timeout]);
      // 未処理拒否の警告を避けるため、await するまでの間だけ握っておく（後段で必ず await する）。
      genPromise.catch(() => undefined);

      setState("searching");
      await new Promise((r) => setTimeout(r, 700));
      setState("building_context");
      await new Promise((r) => setTimeout(r, 700));
      setState("generating");

      const gen = await genPromise;
      setDraft(gen);
      setScenario(gen.scenario);
      setState("done");
    } catch (e) {
      setTimedOut(e instanceof Error && e.message === "timeout");
      setState("error");
    }
  }, [onGenerate]);

  async function save() {
    if (!draft) return;
    setSaving(true);
    setSavedMsg(false);
    try {
      await onSave({ ...draft, scenario });
      setSavedMsg(true);
    } finally {
      setSaving(false);
    }
  }

  const generating =
    state === "searching" || state === "building_context" || state === "generating";

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-lg font-semibold text-slate-900">交渉ポイント・シナリオ（AI生成）</h3>
        <span className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">
          🤖 AI下書き・要確認
        </span>
      </div>

      {state === "idle" && <Button onClick={run}>AIで交渉ポイントを生成する</Button>}

      {generating && (
        <div role="status" aria-live="polite" className="space-y-2">
          {STEP_ORDER.map((s) => {
            const idx = STEP_ORDER.indexOf(s);
            const curIdx = STEP_ORDER.indexOf(state as (typeof STEP_ORDER)[number]);
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
                {STEP_LABEL[s]}
              </div>
            );
          })}
        </div>
      )}

      {state === "error" && (
        <div className="space-y-3" role="status" aria-live="polite">
          <p className="text-sm text-red-600">
            {timedOut
              ? "時間がかかっています。もう一度お試しいただくか、後で確認してください。"
              : "生成に失敗しました。もう一度お試しください。"}
          </p>
          <Button variant="secondary" size="sm" onClick={run}>
            再試行
          </Button>
        </div>
      )}

      {state === "done" && draft && (
        <div className="space-y-4">
          <ul className="space-y-3">
            {draft.points.map((p, i) => (
              <li key={i} className="rounded-md border border-slate-100 bg-slate-50 p-3">
                <p className="text-sm text-slate-700">・{p.text}</p>
                <div className="mt-2">
                  <CitationBadge citations={p.citations} />
                </div>
              </li>
            ))}
          </ul>

          <div>
            <label
              htmlFor="scenario"
              className="block text-sm font-medium text-slate-700"
            >
              交渉シナリオ（編集可）
            </label>
            <textarea
              id="scenario"
              value={scenario}
              onChange={(e) => {
                setScenario(e.target.value);
                setSavedMsg(false);
              }}
              rows={4}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1"
            />
          </div>

          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={run}>
              🔁 再生成
            </Button>
            <Button size="sm" onClick={save} loading={saving}>
              この内容で保存
            </Button>
            {savedMsg && <span className="text-sm text-emerald-600">保存しました</span>}
          </div>
        </div>
      )}
    </section>
  );
}
