#!/usr/bin/env bash
#
# food_supply_MVP（ふりぃらじかるず）ローカル起動スクリプト
# ------------------------------------------------------------
# 使い方（このファイルのあるフォルダで実行）:
#   ./run.sh          … 起動（裏方=FastAPI:8000 と 画面=Next.js を起動）
#   ./run.sh stop     … 停止
#   ./run.sh status   … いま動いているか確認
#
# 画面のURL: http://localhost:3000（使用中なら自動で 3001 へ）
# ログイン（開発用）: freeradicals / tanaka / demo1234
# ログ: /tmp/food_supply_MVP/backend.log, frontend.log
# ------------------------------------------------------------
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOGDIR="/tmp/food_supply_MVP"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"   # npm/node の場所を明示

start() {
  mkdir -p "$LOGDIR"

  # --- 事前チェック（分かりやすい案内を出して止まる） ---
  if [ ! -x "$ROOT/backend/.venv/bin/uvicorn" ]; then
    echo "❌ backend の仮想環境がありません。先に README のセットアップ（python3 -m venv .venv 等）を行ってください。"
    exit 1
  fi
  if [ ! -d "$ROOT/frontend/node_modules" ]; then
    echo "📦 frontend の部品が未インストールのため、いまから入れます（初回のみ・数分）..."
    (cd "$ROOT/frontend" && npm install) || { echo "❌ npm install に失敗しました"; exit 1; }
  fi

  # --- 裏方（FastAPI）。画面が 3000/3001 のどちらでも注文を受けられるようにする ---
  # LISTEN 状態（=窓口を開けているプロセス）だけを起動済みとみなす
  if lsof -iTCP:8000 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "（裏方 :8000 は既に起動しています）"
  else
    (cd "$ROOT/backend" && \
      CORS_ORIGINS="http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001" \
      nohup ./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 \
        > "$LOGDIR/backend.log" 2>&1 & echo $! > "$LOGDIR/backend.pid")
    echo "🍳 裏方を起動しました（:8000）"
  fi

  # --- 画面（Next.js）。Googleログインの許可オリジンに合わせ 3000 番へ固定する ---
  if lsof -iTCP:3000 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "（画面は既に起動しています）"
  else
    (cd "$ROOT/frontend" && \
      nohup npm run dev -- -p 3000 > "$LOGDIR/frontend.log" 2>&1 & echo $! > "$LOGDIR/frontend.pid")
    echo "🖥  画面を起動しました（:3000 固定）"
  fi

  echo ""
  echo "数秒待ってから ./run.sh status で確認してください。"
  echo "ログイン（開発用）: freeradicals / tanaka / demo1234"
}

stop() {
  for name in backend frontend; do
    if [ -f "$LOGDIR/$name.pid" ]; then
      kill "$(cat "$LOGDIR/$name.pid")" 2>/dev/null && echo "🛑 $name を停止しました" || true
      rm -f "$LOGDIR/$name.pid"
    fi
  done
  # 念のためポートに残ったプロセスも畳む（このアプリのポートのみ）
  for port in 8000 3000 3001; do
    pids=$(lsof -ti :$port 2>/dev/null)
    [ -n "$pids" ] && kill $pids 2>/dev/null && echo "🛑 :$port の残プロセスを停止しました"
  done
  echo "（画面が :3000 で動いていた場合は ./run.sh status で確認してください）"
}

status() {
  echo "=== サーバ応答 ==="
  code_back=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 http://127.0.0.1:8000/api/health 2>/dev/null || echo "---")
  echo "  裏方 :8000 = $code_back （200なら正常）"
  found=0
  for port in 3000 3001 3002; do
    title=$(curl -s --max-time 2 "http://localhost:$port" 2>/dev/null | grep -oE "<title>[^<]*" | head -1 | sed 's/<title>//')
    if echo "$title" | grep -q "ふりぃらじかるず"; then
      echo "  画面 :$port = 200 → http://localhost:$port  ✅ここを開く"
      found=1
    elif [ -n "$title" ]; then
      echo "  （:$port は別アプリ「$title」）"
    fi
  done
  if [ $found -eq 0 ]; then
    echo "  画面: 見つかりません（./run.sh で起動してください）"
  fi
}

case "${1:-start}" in
  start|"") start ;;
  stop)     stop ;;
  status)   status ;;
  *) echo "使い方: ./run.sh [start|stop|status]"; exit 1 ;;
esac
