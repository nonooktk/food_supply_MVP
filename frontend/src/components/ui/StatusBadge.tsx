// StatusBadge（デザインガイド §4.6）
// 交渉前=slate（○）/ 交渉中=blue（●）/ 完了=emerald（✓）。色＋記号を必ず併記（色覚多様性配慮）。
import type { CaseStatus } from "@/lib/types";

const MAP: Record<CaseStatus, { label: string; symbol: string; cls: string }> = {
  before: { label: "交渉前", symbol: "○", cls: "bg-slate-100 text-slate-700" },
  negotiating: { label: "交渉中", symbol: "●", cls: "bg-blue-100 text-blue-700" },
  done: { label: "完了", symbol: "✓", cls: "bg-emerald-100 text-emerald-700" },
};

export function StatusBadge({ status }: { status: CaseStatus }) {
  const s = MAP[status];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${s.cls}`}
    >
      <span aria-hidden="true">{s.symbol}</span>
      {s.label}
    </span>
  );
}
