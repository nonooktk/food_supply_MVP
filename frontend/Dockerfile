# ふりぃらじかるず フロントエンド（Next.js）用 Dockerfile。
# りなれす（rinaresu/frontend/Dockerfile）の multi-stage 方式に倣う。
#
# build ステージで next build（standalone 出力・next.config.ts の output:"standalone"）を行い、
# runtime ステージには .next/standalone / .next/static / public のみを配置して軽量化する。
#
# 注意: NEXT_PUBLIC_* はビルド時にバンドルへ埋め込まれるため、接続先・クライアントID・モードは
# ビルド引数（ARG）で渡し、build 前に ENV へ設定する（az acr build の --build-arg で指定する）。

# ---------- deps: 依存関係インストール ----------
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ---------- build: 本番ビルド ----------
FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# ビルド時に埋め込む公開設定（いずれも秘匿値ではない）。
ARG NEXT_PUBLIC_API_BASE
ARG NEXT_PUBLIC_GOOGLE_CLIENT_ID
ARG NEXT_PUBLIC_USE_MOCK=false
ARG NEXT_PUBLIC_AUTH_MODE=google
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}
ENV NEXT_PUBLIC_GOOGLE_CLIENT_ID=${NEXT_PUBLIC_GOOGLE_CLIENT_ID}
ENV NEXT_PUBLIC_USE_MOCK=${NEXT_PUBLIC_USE_MOCK}
ENV NEXT_PUBLIC_AUTH_MODE=${NEXT_PUBLIC_AUTH_MODE}

RUN npm run build

# ---------- runtime: 実行イメージ ----------
FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000

# standalone 出力・静的アセット・public を配置
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public

EXPOSE 3000

CMD ["node", "server.js"]
