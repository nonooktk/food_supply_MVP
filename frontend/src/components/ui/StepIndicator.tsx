"use client";

// ステップインジケーター（デザインガイド §2.2 案件ワークスペース共通ヘッダー）
// 完了=emerald 塗り○ / 現在地=blue 太枠 / 未着手=slate 灰。色＋アイコンの両方で状態を示す。
// 未到達ステップはクリック不可＋グレーアウト＋ツールチップ。
import { useRouter } from "next/navigation";
import type { WorkspaceStep } from "@/lib/types";

interface StepDef {
  step: WorkspaceStep;
  label: string;
}

const STEPS: StepDef[] = [
  { step: "collect", label: "情報収集" },
  { step: "lines", label: "3ライン算出" },
  { step: "strategy", label: "作戦シート" },
  { step: "result", label: "結果記録" },
];

// MVP（Task #6）で実装済みのステップ。未実装は遷移不可にする。
const IMPLEMENTED: WorkspaceStep[] = ["collect", "lines"];

type StepStatus = "done" | "current" | "todo";

export function StepIndicator({
  caseNo,
  current,
  reached,
}: {
  caseNo: string;
  current: WorkspaceStep;
  /** ここまで到達済み（クリックで戻れる）ステップ */
  reached: WorkspaceStep[];
}) {
  const router = useRouter();
  const currentIdx = STEPS.findIndex((s) => s.step === current);

  function statusOf(step: WorkspaceStep, idx: number): StepStatus {
    if (step === current) return "current";
    if (idx < currentIdx) return "done";
    return "todo";
  }

  function canNavigate(step: WorkspaceStep): boolean {
    return IMPLEMENTED.includes(step) && (reached.includes(step) || step === current);
  }

  function go(step: WorkspaceStep) {
    if (!canNavigate(step) || step === current) return;
    router.push(`/cases/${encodeURIComponent(caseNo)}/${step}`);
  }

  return (
    <nav aria-label="ワークスペースのステップ" className="flex items-center gap-2 overflow-x-auto">
      {STEPS.map((s, i) => {
        const st = statusOf(s.step, i);
        const nav = canNavigate(s.step);
        const notImplemented = !IMPLEMENTED.includes(s.step);
        return (
          <div key={s.step} className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => go(s.step)}
              disabled={!nav || s.step === current}
              title={
                notImplemented
                  ? "この画面は今スプリントでは未実装です"
                  : !nav
                    ? "先に前のステップを完了してください"
                    : undefined
              }
              aria-current={st === "current" ? "step" : undefined}
              className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 py-1.5 text-sm transition-colors
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1
                ${
                  st === "current"
                    ? "border-2 border-blue-600 font-semibold text-blue-700"
                    : st === "done"
                      ? "text-emerald-700 hover:bg-emerald-50"
                      : "text-slate-400"
                }
                ${!nav || s.step === current ? "cursor-default" : "cursor-pointer"}`}
            >
              <span
                aria-hidden="true"
                className={`flex h-5 w-5 items-center justify-center rounded-full text-xs
                  ${
                    st === "done"
                      ? "bg-emerald-600 text-white"
                      : st === "current"
                        ? "bg-blue-600 text-white"
                        : "bg-slate-200 text-slate-500"
                  }`}
              >
                {st === "done" ? "✓" : st === "current" ? "●" : "○"}
              </span>
              {s.label}
            </button>
            {i < STEPS.length - 1 && (
              <span className="text-slate-300" aria-hidden="true">
                ────
              </span>
            )}
          </div>
        );
      })}
    </nav>
  );
}
