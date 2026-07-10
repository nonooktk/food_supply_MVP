// 空・ローディング・エラーの共通表示（デザインガイド §3.1 のパターンを全画面で統一）
import type { ReactNode } from "react";
import { Button } from "./Button";

/** スケルトン行（テーブルのローディング表示） */
export function SkeletonRows({ rows = 6, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, r) => (
        <tr key={r} className="border-b border-slate-100">
          {Array.from({ length: cols }).map((__, c) => (
            <td key={c} className="px-4 py-3">
              <div className="h-4 w-full animate-pulse rounded bg-slate-200" />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

/** スケルトンカード（②過去経緯などのローディング表示） */
export function SkeletonCard() {
  return (
    <div className="rounded-md border border-slate-200 bg-white p-3">
      <div className="h-4 w-2/3 animate-pulse rounded bg-slate-200" />
      <div className="mt-2 h-3 w-1/2 animate-pulse rounded bg-slate-200" />
      <div className="mt-3 h-3 w-full animate-pulse rounded bg-slate-200" />
    </div>
  );
}

/** 空状態（中央寄せのメッセージ＋任意のアクション） */
export function EmptyState({
  title,
  description,
  action,
  icon = "📭",
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  icon?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center">
      <div className="text-4xl" aria-hidden="true">
        {icon}
      </div>
      <p className="text-base font-medium text-slate-700">{title}</p>
      {description && <p className="max-w-md text-sm text-slate-500">{description}</p>}
      {action}
    </div>
  );
}

/** エラーバナー（赤枠＋再読み込み） */
export function ErrorBanner({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-3 rounded-md border border-red-300 bg-red-50 p-4 text-sm text-red-700 sm:flex-row sm:items-center sm:justify-between"
    >
      <span>{message}</span>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          再読み込み
        </Button>
      )}
    </div>
  );
}
