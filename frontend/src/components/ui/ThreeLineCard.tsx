"use client";

// ThreeLineCard（デザインガイド §4.3）— 本アプリの顔
// 目標=emerald / 着地=amber / 撤退=red を type に 1:1 対応で固定（担当者は変更不可）。
// 金額は text-3xl font-bold tabular-nums。手修正時は金額入力＋「修正理由」必須テキストエリアを展開。
import { useState } from "react";
import type { LineType, ThreeLine } from "@/lib/types";
import { Button } from "./Button";

const META: Record<
  LineType,
  { label: string; token: "emerald" | "amber" | "red"; dot: string; text: string; ring: string; border: string }
> = {
  target: {
    label: "目標",
    token: "emerald",
    dot: "bg-emerald-600",
    text: "text-emerald-700",
    ring: "focus-visible:ring-emerald-500",
    border: "border-emerald-200",
  },
  landing: {
    label: "着地",
    token: "amber",
    dot: "bg-amber-600",
    text: "text-amber-700",
    ring: "focus-visible:ring-amber-500",
    border: "border-amber-200",
  },
  walkaway: {
    label: "撤退",
    token: "red",
    dot: "bg-red-600",
    text: "text-red-700",
    ring: "focus-visible:ring-red-500",
    border: "border-red-200",
  },
};

interface Props {
  line: ThreeLine;
  onEdit: (value: number, reason: string) => void;
  onReset: () => void;
}

export function ThreeLineCard({ line, onEdit, onReset }: Props) {
  const m = META[line.type];
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(String(line.value));
  const [reason, setReason] = useState(line.editReason ?? "");
  const [reasonError, setReasonError] = useState(false);

  function startEdit() {
    setValue(String(line.value));
    setReason(line.editReason ?? "");
    setReasonError(false);
    setEditing(true);
  }

  function save() {
    if (reason.trim() === "") {
      // 修正理由が未入力ならテキストエリアを赤枠にしフォーカス（§3.3 バリデーション）
      setReasonError(true);
      return;
    }
    const num = Number(value);
    if (Number.isNaN(num) || num <= 0) return;
    onEdit(num, reason.trim());
    setEditing(false);
  }

  return (
    <div className={`relative flex flex-col rounded-lg border bg-white p-5 ${m.border}`}>
      {/* 手修正済みバッジ（§4.3） */}
      {line.isEdited && (
        <span
          className="absolute right-3 top-3 inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600"
          title={line.editReason ? `修正理由: ${line.editReason}` : undefined}
        >
          ✎ 修正済み
        </span>
      )}

      <div className="flex items-center gap-2">
        <span className={`h-2.5 w-2.5 rounded-full ${m.dot}`} aria-hidden="true" />
        <span className={`text-lg font-semibold ${m.text}`}>{m.label}</span>
      </div>

      <div className={`mt-4 num text-3xl font-bold ${m.text}`}>
        ¥{line.value.toLocaleString("ja-JP")}
        <span className="ml-1 text-base font-normal text-slate-500">/kg</span>
      </div>

      <div className="mt-1 text-sm text-slate-500">
        {line.isEdited ? (
          <span className="num">
            自動算出値 ¥{line.autoValue.toLocaleString("ja-JP")}/kg から修正
          </span>
        ) : (
          "自動算出値"
        )}
      </div>

      {!editing ? (
        <div className="mt-4 flex gap-2">
          <Button variant="secondary" size="sm" onClick={startEdit}>
            ✎ 手修正する
          </Button>
          {line.isEdited && (
            <Button variant="ghost" size="sm" onClick={onReset}>
              自動値に戻す
            </Button>
          )}
        </div>
      ) : (
        <div className="mt-4 space-y-3">
          <div>
            <label
              htmlFor={`edit-value-${line.type}`}
              className="block text-sm font-medium text-slate-700"
            >
              修正後の単価（円/kg）
            </label>
            <input
              id={`edit-value-${line.type}`}
              type="number"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className={`mt-1 w-full rounded-md border border-slate-300 px-3 py-2 num text-sm
                focus-visible:outline-none focus-visible:ring-2 ${m.ring} focus-visible:ring-offset-1`}
            />
          </div>
          <div>
            <label
              htmlFor={`edit-reason-${line.type}`}
              className="block text-sm font-medium text-slate-700"
            >
              修正理由 <span className="text-red-600">*</span>
            </label>
            <textarea
              id={`edit-reason-${line.type}`}
              value={reason}
              aria-required="true"
              aria-invalid={reasonError}
              onChange={(e) => {
                setReason(e.target.value);
                if (e.target.value.trim() !== "") setReasonError(false);
              }}
              rows={2}
              className={`mt-1 w-full rounded-md border px-3 py-2 text-sm
                focus-visible:outline-none focus-visible:ring-2 ${m.ring} focus-visible:ring-offset-1
                ${reasonError ? "border-red-500" : "border-slate-300"}`}
              placeholder="例: 為替が円安に振れたため上限を引き上げ"
            />
            {reasonError && (
              <p className="mt-1 text-xs text-red-600">修正理由を入力してください。</p>
            )}
          </div>
          <div className="flex gap-2">
            <Button size="sm" onClick={save}>
              保存
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
              キャンセル
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
