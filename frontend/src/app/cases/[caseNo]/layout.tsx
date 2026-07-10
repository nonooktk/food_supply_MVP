"use client";

// 案件ワークスペース共通レイアウト（デザインガイド §2.2）
// 共通ヘッダー（← 一覧へ／案件番号・企業・商材）＋ ステップインジケーターを常設し、
// ②〜⑤ はこの中身として描画する。今スプリントの中身は ②情報収集・③3ライン算出。
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { AuthGuard } from "@/components/AppChrome";
import { StepIndicator } from "@/components/ui/StepIndicator";
import { Spinner } from "@/components/ui/Spinner";
import { api } from "@/lib/api";
import type { CaseDetail, WorkspaceStep } from "@/lib/types";

function stepFromPath(pathname: string): WorkspaceStep {
  if (pathname.endsWith("/lines")) return "lines";
  if (pathname.endsWith("/strategy")) return "strategy";
  if (pathname.endsWith("/result")) return "result";
  return "collect";
}

export default function WorkspaceLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard>
      <WorkspaceShell>{children}</WorkspaceShell>
    </AuthGuard>
  );
}

function WorkspaceShell({ children }: { children: ReactNode }) {
  const params = useParams<{ caseNo: string }>();
  const pathname = usePathname();
  const caseNo = decodeURIComponent(params.caseNo);
  const current = stepFromPath(pathname);

  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .getCase(caseNo)
      .then((d) => alive && setDetail(d))
      .catch(() => alive && setError(true));
    return () => {
      alive = false;
    };
  }, [caseNo]);

  return (
    <div className="min-h-screen">
      {/* 共通ヘッダー */}
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-7xl px-6 py-3">
          <div className="flex items-center gap-3">
            <Link
              href="/cases"
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-sm text-slate-600 hover:bg-slate-100
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            >
              ← 一覧へ
            </Link>
            {detail ? (
              <div className="flex items-baseline gap-2">
                <span className="num font-semibold text-slate-900">{detail.caseNo}</span>
                <span className="text-slate-300">/</span>
                <span className="text-slate-700">
                  {detail.company} / {detail.product}
                </span>
              </div>
            ) : error ? (
              <span className="text-sm text-red-600">案件情報の取得に失敗しました</span>
            ) : (
              <Spinner className="h-4 w-4 text-slate-400" />
            )}
          </div>

          <div className="mt-3">
            <StepIndicator caseNo={caseNo} current={current} reached={["collect", "lines"]} />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-6">{children}</main>
    </div>
  );
}
