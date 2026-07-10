"use client";

// モック認証コンテキスト（テナント/ユーザーをローカルステートに保持）
// Entra External ID 認証は Sprint 2。ここでは要件の動線確認のためのモック。
// ログイン成功時のユーザーを localStorage に保持し、リロードしても維持する。

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api } from "@/lib/api";
import type { AuthUser } from "@/lib/types";

const STORAGE_KEY = "freeradicals.auth.v1";

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean; // 初期復元中か
  login: (tenant: string, userId: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  // 初期化: localStorage からユーザーを復元
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      // localStorage（外部システム）からの初期復元のための意図的な setState。
      // ハイドレーション不整合を避けるため、あえてマウント後の effect で行う。
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (raw) setUser(JSON.parse(raw) as AuthUser);
    } catch {
      // 破損時は無視（未ログイン扱い）
    } finally {
      setLoading(false);
    }
  }, []);

  const login = useCallback(async (tenant: string, userId: string, password: string) => {
    const u = await api.login(tenant, userId, password);
    setUser(u);
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(u));
  }, []);

  const logout = useCallback(() => {
    setUser(null);
    window.localStorage.removeItem(STORAGE_KEY);
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, logout }),
    [user, loading, login, logout],
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
