# ふりぃらじかるず — 購買交渉支援アプリ MVP

飲食店向けの購買交渉・相場推定を支援するアプリケーションです。本リポジトリは MVP の基盤（バックエンド Python 骨組み・フロント枠・設計/ドキュメント枠）です。

- 設計正本: MyDocs `outputs/freeradicals-rfp/02_アーキテクチャ設計書_draft-v3.md`（MySQL 化版。§1 構成図 / §5 バックエンド構成 / §9 KRE 分割 / §10 KRE 契約）
- チーム規定: toolmaker 保管庫 `00_組織/社内規定/`（作業・レビュー・リリース・セキュリティ・Slack）

## 構成

```
freeradicals/
├── backend/                本体アプリ（FastAPI）と KRE パッケージ
│   ├── app/                本体アプリ（KRE 以外の全機能・BFF・認証・DB・3ライン算出）
│   │   ├── api/            エンドポイント（health ほか）
│   │   ├── auth/           テナント解決・Entra JWT 検証（今後）
│   │   ├── db/             DB モデル・接続（今後）
│   │   ├── ingest/         raw_imports 正規化・CSV/農水省パーサ（今後）
│   │   ├── llm/            FR-08 最終生成・プロンプト（今後）
│   │   ├── observability/  trace_id 付き構造化ログ（今後）
│   │   ├── config.py       環境変数集中管理（DB_BACKEND シーム）
│   │   └── main.py         アプリファクトリ（create_app）
│   ├── kre/                関連知識検索エンジン（外部委託モジュール・ロトム担当）
│   │   ├── retrieval/      AI Search ベクトル検索・埋め込み
│   │   ├── graph/          GraphRAG（NetworkX）
│   │   ├── services/       DB→AI Search 投入・整合 sync
│   │   ├── scripts/        索引構築・グラフ同期スクリプト
│   │   └── config/         retrieval_config.yaml 置き場
│   ├── tests/              ユニットテスト
│   ├── requirements.txt    Python 依存（固定バージョン）
│   └── .env.example        環境変数の雛形（秘匿値は空）
├── frontend/               Next.js（イーブイが後で scaffold）
├── docs/                   プロジェクト内ドキュメント
├── scripts/                運用スクリプト
└── CLAUDE.md               本リポジトリで作業する AI 向け指示書
```

> `app/` と `kre/` は同一 FastAPI プロセス内だが、結合は `RetrievalEngine` 契約（`kre/contract.py`）に限定する。将来 KRE を別サービス（HTTP/gRPC）へ切り出しても本体の呼び出し口は不変にする（設計 v3 §9）。KRE の契約・実装はロトム担当。

## セットアップと起動（バックエンド）

いずれも `backend/` ディレクトリで実行します。

```bash
# 1. backend へ移動
cd backend

# 2. 仮想環境を作成して有効化（初回のみ）
python3 -m venv .venv
source .venv/bin/activate         # Windows は .venv\Scripts\activate

# 3. 依存パッケージをインストール
pip install --upgrade pip
pip install -r requirements.txt

# 4. 環境変数ファイルを用意（秘匿値を埋める）
cp .env.example .env
#   既定は DB_BACKEND=sqlite なので、ローカルは外部DBなしで起動できる。

# 5. 開発サーバを起動
uvicorn app.main:app --reload
#   → http://127.0.0.1:8000/api/health が 200 を返せば OK
#   → API ドキュメント: http://127.0.0.1:8000/docs
```

### ヘルスチェック

```bash
curl http://127.0.0.1:8000/api/health
# {"status":"ok","service":"freeradicals-backend","app_env":"development","db_backend":"sqlite","use_kre_stub":true}
```

### テスト

```bash
cd backend
source .venv/bin/activate
pytest -q
```

## DB バックエンドの切り替え（DB_BACKEND シーム）

`backend/.env` の `DB_BACKEND` で接続先を切り替えます。`app/config.py` の
`resolve_database_url()` が値に応じて SQLAlchemy 接続URLを解決します。

| DB_BACKEND | 用途 | 必要な環境変数 |
|---|---|---|
| `sqlite`（既定） | ローカル開発（外部DB不要） | `SQLITE_PATH` |
| `mysql` | Azure Database for MySQL（本番／検証） | `DB_HOST` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` / `DB_PORT` / `DB_SSL_*` |
| `postgresql` | 将来切替用 | `PG_*`（別途 `psycopg` ドライバの追加が必要） |

> MySQL 接続の疎通確認は、統括が `.env` に接続情報を記入した後に行います（本 MVP 基盤は SQLite 起動確認まで）。

## 注意（セキュリティ）

- `.env` および秘匿値を含むファイルは**絶対にコミットしない**（`.gitignore` で除外済み）。
- `.env.example` の秘匿値は常に空にする。
