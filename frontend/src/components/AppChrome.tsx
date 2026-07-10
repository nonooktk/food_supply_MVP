"use client";

// アプリ共通クローム: 認証ガード＋トップバー
// - AuthGuard: 未ログインなら /login へリダイレクト（モック認証・Sprint 2 で Entra 置換）。
// - TopBar: ロゴ・グローバルナビ・ユーザーメニュー（デザインガイド §3.1 ヘッダー）。
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import type { ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { Spinner } from "@/components/ui/Spinner";

export function AuthGuard({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) {
      router.replace("/login");
    }
  }, [loading, user, router]);

  if (loading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center text-slate-400">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }
  return <>{children}</>;
}

export function TopBar() {
  const { user, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  function onLogout() {
    logout();
    router.replace("/login");
  }

  const navItems = [
    { href: "/cases", label: "案件一覧" },
    { href: "/master", label: "マスタ管理" },
  ];

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-7xl items-center gap-4 px-6 py-3">
        <Link href="/cases" className="flex items-center gap-2 font-bold text-slate-900">
          <span className="text-lg" aria-hidden="true">
            🥩
          </span>
          購買交渉支援
        </Link>

        <nav className="ml-2 flex items-center gap-1" aria-label="グローバルナビ">
          {navItems.map((n) => {
            const active = pathname.startsWith(n.href);
            return (
              <Link
                key={n.href}
                href={n.href}
                className={`rounded-md px-3 py-1.5 text-sm ${
                  active
                    ? "bg-blue-50 font-medium text-blue-700"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {n.label}
              </Link>
            );
          })}
        </nav>

        {/* グローバル検索（枠のみ。案件一覧のフィルタが主検索） */}
        <div className="ml-auto hidden md:block">
          <input
            type="search"
            placeholder="グローバル検索"
            aria-label="グローバル検索"
            className="w-56 rounded-md border border-slate-300 px-3 py-1.5 text-sm
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          />
        </div>

        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-600">{user?.displayName}</span>
          <button
            type="button"
            onClick={onLogout}
            className="rounded-md px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          >
            ログアウト
          </button>
        </div>
      </div>
    </header>
  );
}
