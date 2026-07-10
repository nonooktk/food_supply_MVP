"use client";

// ログイン画面（デザインガイド §3.0）
// 認証シーム: モックフォーム（テナント/ID/PW・開発用）＋ Google でログイン（GIS・統合/デモ）。
// - AUTH_MODE はバックエンドが実際の可否を決める（mock/google 排他）。画面は両方を提示し、
//   下部に現在の認証モードを表示する。
// - Google ボタンは NEXT_PUBLIC_GOOGLE_CLIENT_ID が必要（GIS の「承認済み JavaScript 生成元」依存）。
//   未設定時は無効表示＋案内文にフォールバックする。
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/Button";
import { MOCK_CREDENTIAL } from "@/lib/mock/data";
import { loadGsiScript, type GsiCredentialResponse } from "@/lib/gsi";

// クライアントID（秘匿値ではない）。ビルド時に NEXT_PUBLIC_GOOGLE_CLIENT_ID から埋め込む。
const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";
const AUTH_MODE = process.env.NEXT_PUBLIC_AUTH_MODE || "mock";

export default function LoginPage() {
  const { user, loading: authLoading, login, loginWithGoogle } = useAuth();
  const router = useRouter();

  const [tenant, setTenant] = useState(MOCK_CREDENTIAL.tenant);
  const [userId, setUserId] = useState(MOCK_CREDENTIAL.userId);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const googleBtnRef = useRef<HTMLDivElement>(null);
  const [googleError, setGoogleError] = useState<string | null>(null);
  const [googleBusy, setGoogleBusy] = useState(false);

  // 既ログインなら一覧へ
  useEffect(() => {
    if (!authLoading && user) router.replace("/cases");
  }, [authLoading, user, router]);

  // GIS コールバック: credential をバックエンドで検証してログイン
  async function handleCredential(res: GsiCredentialResponse) {
    if (!res.credential) {
      setGoogleError("Google 認証に失敗しました。もう一度お試しください。");
      return;
    }
    setGoogleBusy(true);
    setGoogleError(null);
    try {
      await loginWithGoogle(res.credential);
      router.replace("/cases");
    } catch (err) {
      setGoogleError(err instanceof Error ? err.message : "Google 認証に失敗しました。");
      setGoogleBusy(false);
    }
  }

  // GIS スクリプトを読み込み、公式ボタンを描画する（クライアントID未設定時は描画しない）
  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return;
    let alive = true;
    (async () => {
      try {
        const google = await loadGsiScript();
        if (!alive) return;
        google.accounts.id.initialize({
          client_id: GOOGLE_CLIENT_ID,
          callback: (r) => {
            void handleCredential(r);
          },
          cancel_on_tap_outside: true,
        });
        if (googleBtnRef.current) {
          google.accounts.id.renderButton(googleBtnRef.current, {
            type: "standard",
            theme: "outline",
            size: "large",
            text: "signin_with",
            shape: "rectangular",
            width: 320,
            locale: "ja",
          });
        }
      } catch {
        if (alive) setGoogleError("Google ログインの読み込みに失敗しました。");
      }
    })();
    return () => {
      alive = false;
    };
    // 初期化は一度でよい（handleCredential は毎レンダー生成されるが依存に含めない）。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

        {/* Google でログイン（認証シーム: google。GIS 公式ボタン） */}
        <div className="space-y-2">
          {GOOGLE_CLIENT_ID ? (
            <>
              {googleBusy ? (
                <div className="flex h-11 items-center justify-center text-sm text-slate-500">
                  認証中…
                </div>
              ) : (
                <div ref={googleBtnRef} className="flex justify-center" />
              )}
              {googleError && (
                <p role="alert" className="text-sm text-red-600">
                  {googleError}
                </p>
              )}
            </>
          ) : (
            <>
              <Button
                variant="secondary"
                className="w-full"
                disabled
                title="Google クライアントID未設定（GCP 設定後に有効化）"
              >
                Google でログイン
              </Button>
              <p className="text-xs text-slate-400">
                Google ログインは準備中です（クライアントID未設定）。GCP 設定後に有効化されます。
              </p>
            </>
          )}
        </div>

        <div className="my-4 flex items-center gap-3 text-xs text-slate-400">
          <span className="h-px flex-1 bg-slate-200" />
          または（開発用ログイン）
          <span className="h-px flex-1 bg-slate-200" />
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

        <p className="mt-6 text-center text-xs text-slate-400">
          認証モード: <span className="font-medium text-slate-500">{AUTH_MODE}</span>
          <br />
          デモ用: {MOCK_CREDENTIAL.tenant} / {MOCK_CREDENTIAL.userId} / {MOCK_CREDENTIAL.password}
        </p>
      </div>
    </div>
  );
}
