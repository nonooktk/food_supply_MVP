"use client";

// モーダル（デザインガイド §1.5: Esc で閉じる。フォーカスリング）
import { useEffect } from "react";
import type { ReactNode } from "react";

export function Modal({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* 背景オーバーレイ */}
      <div
        className="absolute inset-0 bg-slate-900/40"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="relative z-10 w-full max-w-lg rounded-lg bg-white shadow-xl"
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="閉じる"
            className="flex h-9 w-9 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          >
            ✕
          </button>
        </div>
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>
  );
}
