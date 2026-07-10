"use client";

// DataTable（デザインガイド §4.1）
// 用途: ①案件一覧・マスタ管理・②過去経緯の簡易一覧。
// state: 'empty' | 'loading' | 'error' | 'ready' を props で持ち、状態表示を共通化する（§4.1）。
import type { ReactNode } from "react";
import { SkeletonRows } from "./states";

export interface Column<T> {
  key: string;
  header: string;
  /** 数値列は右寄せ＋tabular-nums */
  numeric?: boolean;
  render: (row: T) => ReactNode;
  width?: string;
}

export type TableState = "empty" | "loading" | "error" | "ready";

interface Props<T> {
  columns: Column<T>[];
  rows: T[];
  state: TableState;
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  /** 空・エラー時に表示する内容（画面ごとに差し替え） */
  emptySlot?: ReactNode;
  errorSlot?: ReactNode;
}

export function DataTable<T>({
  columns,
  rows,
  state,
  rowKey,
  onRowClick,
  emptySlot,
  errorSlot,
}: Props<T>) {
  const colCount = columns.length;

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-300 bg-white">
      <table className="w-full border-collapse text-sm leading-tight">
        <thead>
          <tr className="border-b border-slate-200 bg-slate-50 text-left text-slate-600">
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={`px-4 py-2.5 font-medium ${c.numeric ? "text-right" : ""}`}
                style={c.width ? { width: c.width } : undefined}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {state === "loading" && <SkeletonRows rows={6} cols={colCount} />}

          {state === "error" && (
            <tr>
              <td colSpan={colCount} className="px-4 py-8">
                {errorSlot}
              </td>
            </tr>
          )}

          {state === "empty" && (
            <tr>
              <td colSpan={colCount} className="px-4 py-8">
                {emptySlot}
              </td>
            </tr>
          )}

          {state === "ready" &&
            rows.map((row) => (
              <tr
                key={rowKey(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                tabIndex={onRowClick ? 0 : undefined}
                onKeyDown={
                  onRowClick
                    ? (e) => {
                        if (e.key === "Enter") onRowClick(row);
                      }
                    : undefined
                }
                className={`border-b border-slate-100 last:border-0 ${
                  onRowClick
                    ? "cursor-pointer hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500"
                    : ""
                }`}
              >
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={`px-4 py-2.5 ${c.numeric ? "text-right num" : ""}`}
                  >
                    {c.render(row)}
                  </td>
                ))}
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}
