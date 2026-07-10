"use client";

// マスタ管理（デザインガイド §3.6）— 本スプリント（Task #6）では枠のみ。
// 商材・規格・取引先・変動理由・インフォマート分類の管理は後続スプリントで実装。
import { AuthGuard, TopBar } from "@/components/AppChrome";
import { EmptyState } from "@/components/ui/states";

export default function MasterPage() {
  return (
    <AuthGuard>
      <TopBar />
      <main className="mx-auto max-w-7xl px-6 py-6">
        <h1 className="mb-4 text-2xl font-bold text-slate-900">マスタ管理</h1>
        <div className="rounded-lg border border-slate-200 bg-white">
          <EmptyState
            icon="🗂️"
            title="マスタ管理は後続スプリントで実装します"
            description="商材・規格・取引先・変動理由・インフォマート分類（2,492件）の管理画面を予定しています。"
          />
        </div>
      </main>
    </AuthGuard>
  );
}
