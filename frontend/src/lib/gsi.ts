// Google Identity Services (GIS) の最小型定義とローダー。
// りなれす（rinaresu/frontend/lib/gsi.ts）で実績のある方式を本プロジェクトへ移植。
// 公式の型パッケージは入れず、使う API だけを自前で最小限に定義する。
//
// 注意（GIS の制約）: GIS ボタンは Google Cloud コンソールの「承認済み JavaScript 生成元」に
// 現在のオリジン（例: http://localhost:3000）が登録されている必要がある。未登録だと
// ボタン描画やトークン発行が失敗する。クライアントID未設定時は呼び出し側でガードする。

/** GIS のコールバックが返す資格情報レスポンス */
export interface GsiCredentialResponse {
  credential: string; // Google の IDトークン（JWT）
  select_by?: string;
}

// google.accounts.id の使う範囲のみ
interface GsiIdApi {
  initialize(config: {
    client_id: string;
    callback: (response: GsiCredentialResponse) => void;
    auto_select?: boolean;
    cancel_on_tap_outside?: boolean;
  }): void;
  renderButton(
    parent: HTMLElement,
    options: {
      type?: "standard" | "icon";
      theme?: "outline" | "filled_blue" | "filled_black";
      size?: "small" | "medium" | "large";
      text?: "signin_with" | "signup_with" | "continue_with" | "signin";
      shape?: "rectangular" | "pill" | "circle" | "square";
      width?: number;
      locale?: string;
    },
  ): void;
  disableAutoSelect(): void;
}

export interface GoogleGsi {
  accounts: {
    id: GsiIdApi;
  };
}

// window.google をアプリ内で参照するためのグローバル拡張
declare global {
  interface Window {
    google?: GoogleGsi;
  }
}

const GSI_SRC = "https://accounts.google.com/gsi/client";

/** GIS スクリプトを一度だけ読み込む（読み込み完了で resolve）。 */
export function loadGsiScript(): Promise<GoogleGsi> {
  return new Promise((resolve, reject) => {
    if (typeof window === "undefined") {
      reject(new Error("window がありません（SSR）"));
      return;
    }
    if (window.google?.accounts?.id) {
      resolve(window.google);
      return;
    }

    const existing = document.querySelector<HTMLScriptElement>(`script[src="${GSI_SRC}"]`);

    const onReady = () => {
      if (window.google?.accounts?.id) resolve(window.google);
      else reject(new Error("GIS の初期化に失敗しました"));
    };

    if (existing) {
      existing.addEventListener("load", onReady, { once: true });
      existing.addEventListener(
        "error",
        () => reject(new Error("GIS スクリプトの読み込みに失敗しました")),
        { once: true },
      );
      if (window.google?.accounts?.id) onReady();
      return;
    }

    const script = document.createElement("script");
    script.src = GSI_SRC;
    script.async = true;
    script.defer = true;
    script.onload = onReady;
    script.onerror = () => reject(new Error("GIS スクリプトの読み込みに失敗しました"));
    document.head.appendChild(script);
  });
}
