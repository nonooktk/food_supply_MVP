# CLAUDE.md — ふりぃらじかるず（購買交渉支援アプリ MVP）

このファイルは、本リポジトリで作業する Claude Code（および他の AI 開発アシスタント）向けの指示書です。
**本リポジトリだけで開発を継続できるように書かれています**。すべて日本語で書き、日本語で応答してください。

## プロジェクト概要

飲食店向けの購買交渉・相場推定を支援するアプリの MVP です。仕入担当者が、

1. 交渉前に相場・過去経緯・自社計画を確認し、
2. 目標／着地／撤退の3ライン＋AI交渉シナリオを含む「作戦シート」を生成し、
3. 交渉後の結果（決着単価・決着理由タグ・所感）を構造化記録し、次回の同一商材×取引先案件で
   自動参照する（**判断継承ループ BR-10**）

という一連の流れを支援します。詳細な要件は [`docs/要件定義書.md`](./docs/要件定義書.md) を参照してください。

### モジュール構成（本体 CORE ⇄ KRE の2分割）

バックエンド（`backend/`）は2パッケージに分かれています。

- **`app/`（本体アプリ / CORE）**: 画面・API・認証・DB・3ライン算出・交渉ポイント/シナリオの最終生成など、
  KRE 以外の全機能を持つ。
- **`kre/`（関連知識検索エンジン / KRE）**: 過去経緯参照（AI Search 検索＋GraphRAG＋整合）を担う独立モジュール。
  本体とは `RetrievalEngine` 契約（`backend/kre/contract.py`）越しにのみ結合しており、実装（スタブ ⇄ 本実装）を
  DI（依存性注入）で差し替え可能。将来 HTTP/gRPC で別サービスへ切り出しても本体の呼び出し口が変わらない設計。
  KRE の構造・データフローの詳細は [`docs/TASK_knowledge-graph-optimization.md`](./docs/TASK_knowledge-graph-optimization.md)
  §2 にまとめています。

フロントは Next.js（`frontend/`、App Router）。

### 調整シーム（未確定要件を「設定／インターフェース差し替え」で吸収する思想）

本プロジェクトは発注者確認待ちの仕様を、本体コードの改修なしに切り替えられる「調整シーム」として
実装しています。要件が未確定でも実装を止めずに前進させ、確定後は設定変更またはインターフェース裏の
実装差し替えだけで対応する考え方です。主な調整シーム（7点）:

1. **テナント分離水準**: アプリ層テナントフィルタを既定とし、DB を PostgreSQL へ移行した段階で
   RLS を三層目として追加できるよう抽象化（現状 MySQL は RLS 非対応）。
2. **case_no 採番**: `NumberingService` インターフェースで差し替え可能（`app/db/numbering.py`）。
3. **規格グレード運用**: `product_specs.grade` を config フラグ（`free_text` ⇔ `mastered`）で切替
   （`app/db/seams.py` の `GradeMode`）。
4. **対象業務範囲**: `negotiation_cases.case_type` を拡張 enum とし、将来販売側を追加可能
   （`app/db/seams.py` の `CaseType`）。
5. **農水省等の外部データ取込**: `IngestAdapter` インターフェースで manual/CSV → API を差し替え可能。
6. **DB バックエンド**: `DB_BACKEND` 設定で `sqlite`（ローカル開発）⇔ `mysql`（検収・本番）⇔
   `postgresql`（将来）を切替。SQLAlchemy モデルは方言中立に保つ（`app/config.py`）。
7. **認証方式**: `AUTH_MODE` 設定で `mock`（開発・テスト）⇔ `google`（GIS。MVP 採用）⇔
   将来 `entra` 等へ切替可能（`app/auth/`）。

未確定の仕様に出会ったら、まずこれらのシームで吸収できないか検討してください。

## セットアップ手順（コピペ可）

### バックエンド

```bash
cd backend

# 1. 仮想環境を作成して有効化（初回のみ）
python3 -m venv .venv
source .venv/bin/activate         # Windows は .venv\Scripts\activate

# 2. 依存パッケージをインストール
pip install --upgrade pip
pip install -r requirements.txt

# 3. 環境変数ファイルを用意
cp .env.example .env
#   既定値のままで（DB_BACKEND=sqlite, USE_KRE_STUB=true, AUTH_MODE=mock）
#   外部サービス（Azure・Google）に一切接続せずに起動できます。
#   各キーの意味は .env.example のコメントを参照してください。

# 4. DBマイグレーションを適用
alembic -c app/alembic.ini upgrade head

# 5. マスタ・サンプルデータを投入
python -m app.ingest.seed

# 6. 開発サーバを起動
uvicorn app.main:app --reload
#   → http://127.0.0.1:8000/api/health が 200 を返せば OK
#   → API ドキュメント: http://127.0.0.1:8000/docs
```

ヘルスチェック例:

```bash
curl http://127.0.0.1:8000/api/health
# {"status":"ok","service":"freeradicals-backend","app_env":"development","db_backend":"sqlite","use_kre_stub":true}
```

### フロントエンド

```bash
cd frontend

# 1. 依存パッケージをインストール
npm install

# 2. 環境変数ファイルを用意
cp .env.example .env.local
#   既定値のままで（NEXT_PUBLIC_USE_MOCK=true）モックデータで起動できます。
#   バックエンドと接続する場合は NEXT_PUBLIC_USE_MOCK=false, NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000/api とする。

# 3. 開発サーバを起動
npm run dev
#   → http://localhost:3000
```

## 重要な規約

作業前に、本ファイルと [`docs/要件定義書.md`](./docs/要件定義書.md) に必ず目を通してください。
設計・実装で以下のルールを守ってください。

1. **全 DB アクセスは `TenantScopedRepository` 経由に限定する**（`backend/app/db/repository.py`）。
   MySQL 8.4 は RLS 非対応のため、テナント分離はアプリ層で必須です。
   - 全クエリに `tenant_id` 条件を強制する（この Repository を経由しない素の SQLAlchemy セッションを
     画面／サービス層へ露出させない）。
   - `tenant_id` の唯一の源泉は認証（JWT／セッション）。リクエストボディ・クエリパラメータ由来の
     値は信用しない。
   - 書込時も強制付与。他テナント行への UPDATE/DELETE はゼロ件化する。
   - 共有マスタ（`model_versions` 等）は対象外（参照＝自テナント＋共通、書込＝自テナントのみ）。
   - KRE 側（AI Search・グラフ）でも同様に、ID 名前空間 `{tenant}:{type}:{pk}` の接頭辞判定で
     テナント越境をゼロにする二重防御を行っています（詳細は
     [`docs/TASK_knowledge-graph-optimization.md`](./docs/TASK_knowledge-graph-optimization.md) §2.2）。

2. **業務ロジックの正本は `backend/app/db/seams.py`**。未確定要件を吸収する調整シーム
   （`CaseType`, `GradeMode`, 3ライン算出式 `CALC_RULE_V1` 等）をここに集約しています。
   モック実装・テストダブルを作る場合も、この正本と挙動を一致させてください。

3. **KRE との境界は `backend/kre/contract.py` の契約に限定する**。本体は `RetrievalEngine` Protocol
   （`retrieve` / `index_upsert` / `health`）に対してコーディングし、実装は
   `USE_KRE_STUB` 設定で `StubRetrievalEngine`（`kre/stub.py`）⇔ `AzureRetrievalEngine`（`kre/engine.py`）を
   DI で切り替えます。契約（Pydantic モデル・JSON Schema）を変更する場合は本体側への影響を必ず確認してください。

4. **認証は `AUTH_MODE` シームで切替**（`backend/app/config.py` の `Settings.auth_mode`）。
   - `mock`（既定）: 開発・テスト用。外部認証サービスへの接続不要。
   - `google`: Google Identity Services（GIS）による ID トークン検証（`backend/app/auth/google.py`）。
     利用には `GOOGLE_CLIENT_ID` の設定が必要（後述「既知の制約」参照）。

5. **コミットメッセージは日本語**で書いてください。

6. **`.env` および秘匿値を含むファイルは絶対にコミットしない**（`.gitignore` で除外済み）。
   `.env.example` を作成・更新する場合は秘匿値を空にし、キー名と説明のみを記載してください。

7. **危険な git 操作**（`git checkout -f` / `git reset --hard` / `git clean` 等）を行う前には、
   影響範囲を提示し確認を取ってください。

8. **push 前にはコミット対象ファイル一覧を提示して確認を取ってください。**

## テストの実行方法

```bash
cd backend
source .venv/bin/activate
pytest -q                 # 全テスト
pytest tests/kre -q       # KRE（知識レイヤー）関連のみ
```

KRE 関連の契約テスト（`backend/tests/kre/test_contract.py`, `test_tenant_isolation.py` 等）は、
KRE の実装変更（検索チューニング・グラフ補完の追加等）を行った場合に **必ず green を維持する**
必要がある受け入れ条件です。詳細は [`docs/TASK_knowledge-graph-optimization.md`](./docs/TASK_knowledge-graph-optimization.md)
§4 (d) を参照してください。

フロントエンドの Lint:

```bash
cd frontend
npm run lint
```

## 設計ドキュメントの所在

- **要件定義書**: [`docs/要件定義書.md`](./docs/要件定義書.md)（機能要件・非機能要件・KRE モジュール分割の
  帰属境界・見積もりの正本）。
- **デザインガイド**: [`docs/design-guide.md`](./docs/design-guide.md)（画面設計・UI/UX の方針）。
- **KRE 最適化タスク**: [`docs/TASK_knowledge-graph-optimization.md`](./docs/TASK_knowledge-graph-optimization.md)
  （知識グラフ・判断継承まわりの構造説明と、切り出しタスクの依頼書）。
- より詳細なアーキテクチャ設計（システム構成図、DB スキーマ DDL、KRE インターフェース契約の逐語仕様、
  `retrieval_config` の全項目解説など）は本リポジトリ外の設計書（アーキテクチャ設計書）で別管理されています。
  本リポジトリ内の実装・契約（`backend/kre/contract.py` のコード自体、`backend/app/db/models.py` の
  SQLAlchemy モデル）が実装上の正本であり、疑義がある場合はコードを正とします。

## 既知の制約

- **Google 認証（`AUTH_MODE=google`）を使うには GCP クライアント ID が必要**です
  （`GOOGLE_CLIENT_ID` / フロントの `NEXT_PUBLIC_GOOGLE_CLIENT_ID`）。未設定でも `AUTH_MODE=mock`
  （既定）でモック認証を使えば開発を継続できます。
- **AI 機能（過去経緯参照の本実装・作戦シートAI生成）を使うには Azure OpenAI / Azure AI Search の
  キーが必要**です（`AZURE_OPENAI_*` / `AZURE_SEARCH_*`）。未設定でも `USE_KRE_STUB=true`（既定）で
  KRE のスタブ実装（同梱 fixture を返す）を使えば開発を継続できます。
- **上記いずれも無くても、SQLite + KRE スタブ + モック認証の組み合わせで開発可能**です。
  「セットアップ手順」の手順どおりに `cp .env.example .env` した既定値のまま起動すれば、
  外部サービスに一切接続せずにバックエンド・フロントエンドの双方を動かせます。
- 本番相当の DB は Azure Database for MySQL Flexible Server（8.4・RLS 非対応）を想定しています。
  テナント分離はアプリ層フィルタ（`TenantScopedRepository`）＋ AI Search 側の OData フィルタによる
  二層防御で担保しており、DB 層の RLS には依存していません（詳細は `docs/要件定義書.md` §3 N-02）。
