"use client";

// ログイン画面（デザインガイド §3.0）
// LoginForm（テナント/ID/PW）＋ SSOButton（Entra は Sprint 2・枠のみ）。
// 認証失敗時はフォーム下に赤文字（原因を推測させない一般文言）。ローディング中はボタン disabled。
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/Button";
import { MOCK_CREDENTIAL } from "@/lib/mock/data";

export default function LoginPage() {
  const { user, loading: authLoading, login } = useAuth();
  const router = useRouter();

  const [tenant, setTenant] = useState(MOCK_CREDENTIAL.tenant);
  const [userId, setUserId] = useState(MOCK_CREDENTIAL.userId);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // 既ログインなら一覧へ
  useEffect(() => {
    if (!authLoading && user) router.replace("/cases");
  }, [authLoading, user, router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(tenant, userId, password);
      router.replace("/cases");
    } catch (err) {
      setError(err instanceof Error ? err.message : "ログインに失敗しました。");
    } finally {
      setSubmitting(false);
    }
  }

  const focus =
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1";

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
        <div className="mb-6 text-center">
          <div className="text-3xl" aria-hidden="true">
            🥩
          </div>
          <h1 className="mt-2 text-xl font-bold text-slate-900">ふりぃらじかるず</h1>
          <p className="text-sm text-slate-500">購買交渉支援</p>
        </div>

        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          <div>
            <label htmlFor="tenant" className="block text-sm font-medium text-slate-700">
              テナント
            </label>
            <input
              id="tenant"
              value={tenant}
              onChange={(e) => setTenant(e.target.value)}
              autoComplete="organization"
              className={`mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm ${focus}`}
            />
          </div>
          <div>
            <label htmlFor="userId" className="block text-sm font-medium text-slate-700">
              ID
            </label>
            <input
              id="userId"
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              autoComplete="username"
              className={`mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm ${focus}`}
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-slate-700">
              パスワード
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              className={`mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm ${focus}`}
            />
          </div>

          {error && (
            <p role="alert" className="text-sm text-red-600">
              {error}
            </p>
          )}

          <Button type="submit" loading={submitting} className="w-full">
            ログイン
          </Button>
        </form>

        <div className="my-4 flex items-center gap-3 text-xs text-slate-400">
          <span className="h-px flex-1 bg-slate-200" />
          または
          <span className="h-px flex-1 bg-slate-200" />
        </div>

        {/* SSO は Sprint 2（Entra External ID）。枠のみで無効表示。 */}
        <Button variant="secondary" className="w-full" disabled title="Sprint 2 で対応（Entra External ID）">
          Microsoft でサインイン
        </Button>

        <p className="mt-6 text-center text-xs text-slate-400">
          デモ用: {MOCK_CREDENTIAL.tenant} / {MOCK_CREDENTIAL.userId} / {MOCK_CREDENTIAL.password}
        </p>
      </div>
    </div>
  );
}
