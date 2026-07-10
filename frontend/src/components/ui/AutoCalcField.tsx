// AutoCalcField（デザインガイド §3.5）
// 見積比・目標達成度などの自動計算値を表示する読み取り専用フィールド。
// 達成度・見積比は閾値で emerald/amber/red に着色する（色に加え数値も表示するため色のみ依存にはならない）。

/** 達成度(%) を閾値着色したセル（≥90 emerald / ≥60 amber / else red）。 */
export function AchievementField({ label, pct }: { label: string; pct: number }) {
  const cls = pct >= 90 ? "text-emerald-700" : pct >= 60 ? "text-amber-700" : "text-red-700";
  return (
    <div className="rounded-md bg-slate-50 px-4 py-3">
      <p className="text-sm text-slate-500">{label}</p>
      <p className={`num text-xl font-bold ${cls}`}>{pct}%</p>
    </div>
  );
}

/** 見積比(%) を表示するセル（マイナス＝安く決着＝emerald、プラス＝高い＝red）。 */
export function QuoteDiffField({ label, pct }: { label: string; pct: number }) {
  const cls = pct <= 0 ? "text-emerald-700" : "text-red-700";
  const sign = pct > 0 ? "+" : "";
  return (
    <div className="rounded-md bg-slate-50 px-4 py-3">
      <p className="text-sm text-slate-500">{label}</p>
      <p className={`num text-xl font-bold ${cls}`}>
        {sign}
        {pct}%
      </p>
    </div>
  );
}
