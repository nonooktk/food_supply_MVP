import type { NextConfig } from "next";

// 開発モード（next dev）判定。CSP の一部を開発時のみ緩める用途に使う。
const isDev = process.env.NODE_ENV === "development";

// ── backend API のオリジン（CSP connect-src で許可する） ──────────────────
// 本番（Azure Container Apps）の API オリジンを既定で許可する。
// 加えて NEXT_PUBLIC_API_BASE が別オリジン（ローカル開発の http://127.0.0.1:8000 や
// 検証環境）を指している場合は、そのオリジンも動的に許可する。
// ※ NEXT_PUBLIC_API_BASE が相対パス（例: /api）のときは 'self' で足りるため追加しない。
const PROD_API_ORIGIN =
  "https://ca-freeradicals-api.happywater-4b65aee9.japaneast.azurecontainerapps.io";

function apiOriginFromEnv(): string | null {
  const base = process.env.NEXT_PUBLIC_API_BASE;
  if (!base) return null;
  try {
    return new URL(base).origin;
  } catch {
    return null; // 相対パス指定。'self' でカバーされるので追加不要。
  }
}

const apiOrigins = Array.from(
  new Set([PROD_API_ORIGIN, apiOriginFromEnv()].filter((o): o is string => Boolean(o))),
).join(" ");

// ── Google Identity Services（GIS）向けの許可オリジン ─────────────────────
// ログインは GIS（frontend/src/lib/gsi.ts）に依存している。GIS は
//   - スクリプト:  https://accounts.google.com/gsi/client
//   - スタイル:    https://accounts.google.com/gsi/style
//   - ボタン iframe: https://accounts.google.com/gsi/button
//   - 画像・静的資産: *.gstatic.com / *.googleusercontent.com（アバター等）
// を読み込む。ここを締めるとログインボタンが描画されず認証が機能しなくなるため、
// script / style / frame / connect / img で必ず許可する。
const GIS_ORIGINS = "https://accounts.google.com https://*.gstatic.com";

// ── Content-Security-Policy ──────────────────────────────────────────────
// 方針: nonce 方式は全ページの動的レンダリング強制（静的最適化・CDN キャッシュの無効化）を
// 伴うため MVP では採用せず、Next.js 公式ドキュメントの "Without Nonces" 方式
// （node_modules/next/dist/docs/01-app/02-guides/content-security-policy.md）に従い
// next.config の headers() で静的に配信する。
//
// 'unsafe-inline' が必要な理由（意図的な許容。TV_MVP と同じ判断）:
//   - script-src: App Router の SSR は RSC ペイロードを `self.__next_f.push(...)` の
//     インラインスクリプトとして HTML に埋め込む。nonce を使わない構成ではこれを
//     許可しないと画面がハイドレートせず動作しない。
//   - style-src: Next.js / next-font がインライン <style> を出力し、GIS も
//     ボタン描画時にスタイルを注入するため。
// ただし以下は必ず締める（監査指摘 F-10 の必須条件）:
//   object-src 'none' / base-uri 'self' / frame-ancestors 'none'
const csp = [
  `default-src 'self'`,
  // 'unsafe-eval' は next dev（React の eval によるエラースタック再構築）でのみ必要。本番では付けない。
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""} ${GIS_ORIGINS}`,
  `style-src 'self' 'unsafe-inline' ${GIS_ORIGINS}`,
  `img-src 'self' data: blob: ${GIS_ORIGINS} https://*.googleusercontent.com`,
  `font-src 'self' data:`,
  // 開発時は Turbopack/webpack の HMR が ws:// を使うため許可する。
  `connect-src 'self' ${GIS_ORIGINS} ${apiOrigins}${isDev ? " ws: http://localhost:* http://127.0.0.1:*" : ""}`,
  // GIS のサインインボタン／One Tap は accounts.google.com の iframe として描画される。
  `frame-src 'self' ${GIS_ORIGINS}`,
  `object-src 'none'`,
  `base-uri 'self'`,
  `form-action 'self'`,
  `frame-ancestors 'none'`,
  // 本番のみ。ローカル検証で http://127.0.0.1:8000 の API 呼び出しが https へ
  // 強制昇格されて壊れるのを避けるため、開発時は付与しない。
  ...(isDev ? [] : [`upgrade-insecure-requests`]),
].join("; ");

// 全レスポンス共通のセキュリティヘッダ（監査指摘 F-10 / F-15 対応）
const securityHeaders = [
  // クリックジャッキング対策。CSP frame-ancestors 'none' と二重で指定する（旧ブラウザ対策）。
  { key: "X-Frame-Options", value: "DENY" },
  // MIME スニッフィング抑止（F-15 web 側）。
  { key: "X-Content-Type-Options", value: "nosniff" },
  // HTTPS 強制（1年）。http でのアクセス時はブラウザ側が無視するためローカルでも無害。
  { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  // 本アプリが使わない強力な機能を明示的に無効化する。
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
  { key: "Content-Security-Policy", value: csp },
];

const nextConfig: NextConfig = {
  // Docker（multi-stage・軽量ランタイム）向けに standalone 出力を有効化する。
  // .next/standalone に server.js と必要な node_modules だけが吐き出される（DEPLOY.md 参照）。
  output: "standalone",

  // X-Powered-By: Next.js による技術スタックの露出を止める（監査指摘 F-19）。
  poweredByHeader: false,

  async headers() {
    return [
      {
        // 全パスに適用する。
        source: "/(.*)",
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;
