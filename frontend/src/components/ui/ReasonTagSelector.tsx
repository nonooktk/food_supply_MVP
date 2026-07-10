"use client";

// ReasonTagSelector（デザインガイド §3.5）
// 変動理由マスタ（RC-01〜10）を複数選択するチップ群。
// 方向は色ではなく矢印記号（↑上げ要因 / ↓下げ要因 / ±両方向）で示す（色覚多様性配慮）。
// クリック領域は最小 44px（§1.5）。
import type { ReasonDirection, ReasonTag } from "@/lib/types";

const ARROW: Record<ReasonDirection, string> = { up: "↑", down: "↓", both: "±" };

export function ReasonTagSelector({
  tags,
  selected,
  onChange,
  error,
}: {
  tags: ReasonTag[];
  selected: string[];
  onChange: (codes: string[]) => void;
  error?: string;
}) {
  function toggle(code: string) {
    if (selected.includes(code)) {
      onChange(selected.filter((c) => c !== code));
    } else {
      onChange([...selected, code]);
    }
  }

  return (
    <div>
      <div role="group" aria-label="決着理由タグ" className="flex flex-wrap gap-2">
        {tags.map((t) => {
          const on = selected.includes(t.code);
          return (
            <button
              key={t.code}
              type="button"
              aria-pressed={on}
              onClick={() => toggle(t.code)}
              className={`inline-flex min-h-[44px] items-center gap-1.5 rounded-full border px-3 text-sm transition-colors
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1
                ${
                  on
                    ? "border-blue-600 bg-blue-50 font-medium text-blue-700"
                    : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                }`}
            >
              <span aria-hidden="true" className="text-slate-500">
                {ARROW[t.direction]}
              </span>
              {t.label}
            </button>
          );
        })}
      </div>
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  );
}
