# ふりぃらじかるず backend（FastAPI + KRE）用 Dockerfile。
#
# python:3.11-slim をベースに、requirements を先にインストール（レイヤキャッシュ効率）。
# 本体 app/ と KRE kre/ を同梱し、起動スクリプト（docker-entrypoint.sh）経由で uvicorn を起動する。
# 起動時に KRE グラフ JSON を必要に応じて自動生成する（BUILD_GRAPH_ON_BOOT・entrypoint 参照）。
FROM python:3.11-slim

WORKDIR /app

# ランタイム依存（PyMySQL は純Python、cryptography 等は manylinux wheel を利用するため
# ビルドツールは基本不要。curl はヘルスチェック用に入れておく）。
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# 依存を先に入れてレイヤをキャッシュ
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# アプリ本体（app/）と KRE（kre/）を同梱
COPY app ./app
COPY kre ./kre
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh

# Container Apps の ingress ターゲットポート
ENV PORT=8000
EXPOSE 8000

# ヘルスチェック（Container Apps 側でも設定可能だが、イメージにも持たせる）
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/api/health" || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
