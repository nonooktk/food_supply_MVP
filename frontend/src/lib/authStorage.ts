// 認証資格情報のブラウザ保管（React 非依存）。
//
// api.ts（リクエスト送出）と auth.tsx（認証コンテキスト）の両方が同じキー・同じ規約で
// 読み書きする必要があるため、保管の責務をこのモジュールへ集約する。
//
// 【2026-07-26 セキュリティ監査 F-1 対応】
// 従来は AuthUser（tenantId / userId）を保存し、それをそのまま X-Tenant-Id / X-User-Id
// ヘッダーで送っていた。これは「クライアントが自分でテナントを名乗る」だけで、
// サーバ側の防御になっていなかった。現在は Google の **ID トークン** を保持し、
// 毎リクエスト `Authorization: Bearer <id_token>` で送ってサーバに検証させる。
//
// 注: ID トークンは localStorage に置くため XSS 耐性は無い（従来の AuthUser 保存と同水準）。
// HttpOnly Cookie ／サーバ側セッションへの移行は後続タスク（本修正のスコープ外）。

import type { AuthUser } from "@/lib/types";

/** 認証ユーザー（表示用）の保管キー。 */
export const AUTH_STORAGE_KEY = "freeradicals.auth.v1";
/** Google ID トークン（サーバへ送る唯一の資格情報）の保管キー。 */
export const ID_TOKEN_STORAGE_KEY = "freeradicals.idtoken.v1";
/** セッション切れをログイン画面へ伝えるフラグ（sessionStorage）。 */
export const SESSION_EXPIRED_KEY = "freeradicals.sessionExpired";

/** 401 を受けたことをアプリ全体へ通知するイベント名。 */
export const UNAUTHORIZED_EVENT = "freeradicals:unauthorized";

function hasWindow(): boolean {
  return typeof window !== "undefined";
}

export function loadAuthUser(): AuthUser | null {
  if (!hasWindow()) return null;
  try {
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    // 破損時は未ログイン扱い
    return null;
  }
}

export function loadIdToken(): string | null {
  if (!hasWindow()) return null;
  try {
    return window.localStorage.getItem(ID_TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

/** ログイン成功時に資格情報を保存する（idToken は Google ログイン時のみ）。 */
export function saveCredential(user: AuthUser, idToken?: string | null): void {
  if (!hasWindow()) return;
  try {
    window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(user));
    if (idToken) {
      window.localStorage.setItem(ID_TOKEN_STORAGE_KEY, idToken);
    } else {
      // モックログイン（開発用）は ID トークンを持たない。古い値を残さない。
      window.localStorage.removeItem(ID_TOKEN_STORAGE_KEY);
    }
  } catch {
    // ストレージが使えない環境（プライベートモード等）ではメモリ上の状態のみで動く
  }
}

export function clearCredential(): void {
  if (!hasWindow()) return;
  try {
    window.localStorage.removeItem(AUTH_STORAGE_KEY);
    window.localStorage.removeItem(ID_TOKEN_STORAGE_KEY);
  } catch {
    // 失敗しても致命的ではない
  }
}

/** 「セッション切れで弾かれた」ことをログイン画面へ引き継ぐ。 */
export function markSessionExpired(): void {
  if (!hasWindow()) return;
  try {
    window.sessionStorage.setItem(SESSION_EXPIRED_KEY, "1");
  } catch {
    // 失敗時はメッセージが出ないだけ
  }
}

/** セッション切れフラグを読み取り、同時に消す（1回だけ表示する）。 */
export function consumeSessionExpired(): boolean {
  if (!hasWindow()) return false;
  try {
    const flag = window.sessionStorage.getItem(SESSION_EXPIRED_KEY);
    if (flag) window.sessionStorage.removeItem(SESSION_EXPIRED_KEY);
    return flag === "1";
  } catch {
    return false;
  }
}

/**
 * サーバから 401 が返ったときの共通処理。
 * 資格情報を破棄し、認証コンテキストへイベントで通知する（→ /login へリダイレクト）。
 * ID トークンの有効期限は約1時間。サイレント更新は行わず、再ログインを促す方針。
 */
export function handleUnauthorized(): void {
  clearCredential();
  markSessionExpired();
  if (!hasWindow()) return;
  window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
}
