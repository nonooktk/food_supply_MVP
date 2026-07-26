"use client";

// 認証コンテキスト（表示用ユーザー ＋ 資格情報のライフサイクル管理）
//
// 【2026-07-26 セキュリティ監査 F-1 対応】
// Google ログインで得た **ID トークン** を保持し、api.ts が毎リクエスト
// `Authorization: Bearer <id_token>` として送る。サーバがそのトークンを検証して
// テナント・実行者を決めるため、クライアント側の状態は「表示用」に過ぎない
// （旧実装はここで保持した tenantId/userId をそのままヘッダーで送っており、
//   クライアントが自由にテナントを名乗れる状態だった）。
//
// ID トークンの寿命は約1時間。期限切れは API が 401 を返し、api.ts が資格情報を破棄して
// UNAUTHORIZED_EVENT を発火する。ここで受けて未ログイン状態へ落とし、AuthGuard が
// /login へ送る（サイレント更新は行わない＝再ログイン導線）。
//
// 開発用モックログイン（バックエンド AUTH_MODE=mock）は ID トークンを持たないため、
// api.ts が X-Tenant-Id / X-User-Id ヘッダーへフォールバックする。

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api } from "@/lib/api";
import {
  UNAUTHORIZED_EVENT,
  clearCredential,
  loadAuthUser,
  saveCredential,
} from "@/lib/authStorage";
import type { AuthUser } from "@/lib/types";

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean; // 初期復元中か
  login: (tenant: string, userId: string, password: string) => Promise<void>;
  /** Google Identity Services の credential（ID トークン）でログインする（認証シーム: google）。 */
  loginWithGoogle: (credential: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  // 初期化: localStorage からユーザーを復元
  useEffect(() => {
    try {
      const restored = loadAuthUser();
      // localStorage（外部システム）からの初期復元のための意図的な setState。
      // ハイドレーション不整合を避けるため、あえてマウント後の effect で行う。
      if (restored) setUser(restored);
    } finally {
      setLoading(false);
    }
  }, []);

  // API が 401 を返したら（未認証・ID トークンの期限切れ）未ログイン状態へ落とす。
  // 資格情報の破棄と「セッション切れ」フラグの記録は api.ts（authStorage）側で済んでいる。
  useEffect(() => {
    const onUnauthorized = () => setUser(null);
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  const login = useCallback(async (tenant: string, userId: string, password: string) => {
    // 開発用モックログイン。ID トークンは発行されない。
    const u = await api.login(tenant, userId, password);
    setUser(u);
    saveCredential(u, null);
  }, []);

  const loginWithGoogle = useCallback(async (credential: string) => {
    // credential（＝ Google の ID トークン）をサーバで検証し、成功したら
    // そのトークン自体を以後の Bearer 資格情報として保持する。
    const u = await api.googleAuth(credential);
    setUser(u);
    saveCredential(u, credential);
  }, []);

  const logout = useCallback(() => {
    setUser(null);
    clearCredential();
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, loginWithGoogle, logout }),
    [user, loading, login, loginWithGoogle, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth は AuthProvider の内側で使用してください。");
  }
  return ctx;
}
