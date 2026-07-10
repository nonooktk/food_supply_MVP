#!/usr/bin/env sh
# ふりぃらじかるず backend コンテナの起動スクリプト。
#
# KRE の GraphRAG 用グラフ JSON は gitignore 済みのローカル生成物（リポジトリに含めない）。
# コンテナ起動時、グラフ JSON が無く BUILD_GRAPH_ON_BOOT=true の場合のみ、DB から
# `build_index --graph-only`（AI Search へは投入せず・埋め込み課金なし）で再生成する。
# AI Search インデックスはクラウド側に既存のものを使うため、ここでは再投入しない。
set -e

GRAPH_DIR="${KRE_GRAPH_DIR:-/app/kre/graph/data}"
mkdir -p "$GRAPH_DIR"

if [ "${BUILD_GRAPH_ON_BOOT:-false}" = "true" ]; then
  if ls "$GRAPH_DIR"/*.json >/dev/null 2>&1; then
    echo "[entrypoint] グラフ JSON が既に存在します。生成をスキップします。"
  else
    echo "[entrypoint] グラフ JSON が無いため build_index --graph-only を実行します..."
    # 失敗しても KRE はグラフ無しで動作継続できる（検索は返る／グラフ補完のみ空）ため止めない。
    python -m kre.scripts.build_index --graph-only --graph-dir "$GRAPH_DIR" \
      || echo "[entrypoint] グラフ生成に失敗しました（グラフ補完なしで継続します）。"
  fi
fi

echo "[entrypoint] uvicorn を起動します（port=${PORT:-8000}）。"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
