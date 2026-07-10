"use client";

// CitationBadge（デザインガイド §4.4）
// 過去経緯・AI生成に付く引用元バッジ。クリックで展開し引用元一覧を表示。
// 引用元0件は「引用元なし（下書きのみ）」と控えめに表示（隠さない）。
// アクセシビリティ: <button> + aria-expanded。
import { useState } from "react";
import type { Citation } from "@/lib/types";

export function CitationBadge({ citations }: { citations: Citation[] }) {
  const [open, setOpen] = useState(false);
  const count = citations.length;
  const empty = count === 0;

  return (
    <div className="relative inline-block text-left">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className={`inline-flex min-h-[44px] items-center gap-1 rounded-md border px-3 py-1 text-xs font-medium
          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1
          ${
            empty
              ? "border-slate-200 bg-slate-50 text-slate-500"
              : "border-indigo-200 bg-indigo-50 text-indigo-700 hover:bg-indigo-100"
          }`}
      >
        <span aria-hidden="true">📎</span>
        {empty ? "引用元なし（下書きのみ）" : `引用元 (${count}件)`}
      </button>

      {open && !empty && (
        <div
          role="dialog"
          aria-label="引用元一覧"
          className="absolute z-20 mt-1 w-80 rounded-md border border-slate-200 bg-white p-3 shadow-lg"
        >
          <ul className="space-y-2">
            {citations.map((c, i) => (
              <li key={i} className="border-b border-slate-100 pb-2 last:border-0 last:pb-0">
                <div className="flex items-center gap-2 text-xs font-medium text-slate-700">
                  <span className="num">{c.caseNo}</span>
                  <span className="text-slate-400">·</span>
                  <span>{c.company}</span>
                </div>
                <div className="text-xs text-slate-500">{c.product}</div>
                <p className="mt-1 text-xs text-slate-600">{c.snippet}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
