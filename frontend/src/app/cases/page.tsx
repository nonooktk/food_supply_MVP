"use client";

// 画面① 案件一覧／案件作成（デザインガイド §3.1 / FR-01・FR-10）
// 検索・状態フィルタ・DataTable・作成モーダルを1画面に集約。
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AuthGuard, TopBar } from "@/components/AppChrome";
import { Button } from "@/components/ui/Button";
import { Column, DataTable, TableState } from "@/components/ui/DataTable";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { EmptyState, ErrorBanner } from "@/components/ui/states";
import { api, CaseListFilter } from "@/lib/api";
import type { CaseDetail, CaseStatus } from "@/lib/types";
import { CreateCaseModal } from "./CreateCaseModal";

const STATUS_OPTIONS: { value: CaseStatus | "all"; label: string }[] = [
  { value: "all", label: "すべて" },
  { value: "before", label: "交渉前" },
  { value: "negotiating", label: "交渉中" },
  { value: "done", label: "完了" },
];

export default function CasesPage() {
  return (
    <AuthGuard>
      <TopBar />
      <CasesInner />
    </AuthGuard>
  );
}

function CasesInner() {
  const router = useRouter();
  const [rows, setRows] = useState<CaseDetail[]>([]);
  const [total, setTotal] = useState(0);
  const [state, setState] = useState<TableState>("loading");
  const [keyword, setKeyword] = useState("");
  const [status, setStatus] = useState<CaseStatus | "all">("all");
  const [modalOpen, setModalOpen] = useState(false);
  // 検索が実行済みか（空状態の文言を「初回」か「結果0件」で切り替える）
  const [filtered, setFiltered] = useState(false);

  const load = useCallback(
    async (filter: CaseListFilter, isFiltered: boolean) => {
      setState("loading");
      try {
        const res = await api.listCases(filter);
        setRows(res.items);
        setTotal(res.total);
        setFiltered(isFiltered);
        setState(res.items.length === 0 ? "empty" : "ready");
      } catch {
        setState("error");
      }
    },
    [],
  );

  useEffect(() => {
    // 初回マウント時の一覧ロード（API＝外部システムとの同期）のための意図的な呼び出し。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load({ status: "all" }, false);
  }, [load]);

  function onSearch() {
    const isFiltered = keyword.trim() !== "" || status !== "all";
    load({ keyword, status }, isFiltered);
  }

  function resetFilter() {
    setKeyword("");
    setStatus("all");
    load({ status: "all" }, false);
  }

  const columns: Column<CaseDetail>[] = [
    { key: "caseNo", header: "案件番号", numeric: true, width: "120px", render: (r) => r.caseNo },
    { key: "company", header: "企業", render: (r) => r.company },
    { key: "product", header: "商材", render: (r) => r.product },
    {
      key: "status",
      header: "ステータス",
      width: "120px",
      render: (r) => <StatusBadge status={r.status} />,
    },
    { key: "updatedAt", header: "更新日", numeric: true, width: "90px", render: (r) => r.updatedAt },
    { key: "assignee", header: "担当", width: "80px", render: (r) => r.assignee },
  ];

  return (
    <main className="mx-auto max-w-7xl px-6 py-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900">案件一覧</h1>
        <Button onClick={() => setModalOpen(true)}>＋ 新規案件作成</Button>
      </div>

      {/* フィルタバー */}
      <div className="mb-4 flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex-1 min-w-[200px]">
          <label htmlFor="kw" className="block text-sm font-medium text-slate-700">
            キーワード
          </label>
          <input
            id="kw"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onSearch()}
            placeholder="案件番号・企業・商材・担当"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          />
        </div>
        <div className="min-w-[160px]">
          <label htmlFor="st" className="block text-sm font-medium text-slate-700">
            ステータス
          </label>
          <select
            id="st"
            value={status}
            onChange={(e) => setStatus(e.target.value as CaseStatus | "all")}
            className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          >
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <Button variant="secondary" onClick={onSearch}>
          検索実行
        </Button>
        {filtered && (
          <Button variant="ghost" onClick={resetFilter}>
            条件をリセット
          </Button>
        )}
      </div>

      <DataTable<CaseDetail>
        columns={columns}
        rows={rows}
        state={state}
        rowKey={(r) => r.caseNo}
        onRowClick={(r) => router.push(`/cases/${encodeURIComponent(r.caseNo)}`)}
        emptySlot={
          filtered ? (
            <EmptyState
              icon="🔍"
              title="条件に一致する案件がありません"
              description="フィルタ条件を見直すか、リセットしてください。"
              action={
                <Button variant="secondary" size="sm" onClick={resetFilter}>
                  条件をリセット
                </Button>
              }
            />
          ) : (
            <EmptyState
              icon="📋"
              title="案件がまだありません"
              description="最初の交渉案件を作成しましょう。"
              action={<Button onClick={() => setModalOpen(true)}>＋ 新規案件作成</Button>}
            />
          )
        }
        errorSlot={
          <ErrorBanner
            message="案件の読み込みに失敗しました"
            onRetry={() => load({ keyword, status }, filtered)}
          />
        }
      />

      {state === "ready" && (
        <p className="mt-3 text-right text-sm text-slate-500 num">全{total}件を表示</p>
      )}

      <CreateCaseModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreated={(detail) => {
          setModalOpen(false);
          // 作成後は案件ワークスペース②へ遷移（デザインガイド §3.1）
          router.push(`/cases/${encodeURIComponent(detail.caseNo)}/collect`);
        }}
      />
    </main>
  );
}
