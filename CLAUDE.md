# CLAUDE.md — ふりぃらじかるず（購買交渉支援アプリ MVP）

このファイルは、本リポジトリで作業する Claude／AIメンバー向けの指示書です。**すべて日本語で書き、日本語で応答してください。**

## プロジェクト概要

飲食店向けの購買交渉・相場推定を支援するアプリの MVP。バックエンドは FastAPI で、本体アプリ（`app/`）と関連知識検索エンジン KRE（`kre/`・外部委託モジュール）の 2 パッケージに分割し、`RetrievalEngine` 契約越しに DI で結合します。フロントは Next.js（`frontend/`・後日 scaffold）。

## 設計正本（先に読む）

- **アーキテクチャ設計書 v3**: MyDocs `outputs/freeradicals-rfp/02_アーキテクチャ設計書_draft-v3.md`
  - §1 システム構成図 / §5 バックエンド構成（`app/`・`kre/` 2パッケージ + DIコンテナ）
  - §9 モジュール分割（本体 ⇄ KRE の境界・責務）/ §10 KRE インターフェース契約 / §11 retrieval_config
  - v3 は MySQL 化版。以後 v3 以降の最新版を正本とする。
- 要件定義書 v3: 同フォルダ `01_要件定義書_draft-v3.md`

> 設計は [[キャタピー]]、UI は [[マイメロディ]] のモックアップに従う。実装は本リポジトリ配下に限定する。

## 構成（要約）

```
backend/app/    本体アプリ（api/ auth/ db/ ingest/ llm/ observability/・config.py・main.py）
backend/kre/    関連知識検索エンジン（retrieval/ graph/ services/ scripts/ config/）※契約・実装はロトム担当
frontend/       Next.js（イーブイが scaffold）
docs/ scripts/  ドキュメント・運用スクリプト
```

起動・テスト手順は [README.md](./README.md) を参照（コピペ可）。

## 実装の約束（toolmaker 規定に従う）

作業前に toolmaker 保管庫 `00_組織/社内規定/` の規定を読むこと。

1. **計画 → 承認 → 実装**。承認前に実装着手しない（承認合図: 「OK」「Aで」「進めてください」「同意です」）。
2. **既存資産（コード・設計・ナレッジ）を先に読む**。車輪の再発明をしない。
3. **すべて日本語**。コメント・ドキュメント・報告も日本語。コマンドはコピペで動く具体例で示す。
4. 作業スコープは**本リポジトリ配下に限定**。横断調査は事前に範囲提示して承認を得る。
5. **エラー報告はトレースバック全文**。
6. 危険な git 操作（`checkout -f` / `reset` / `clean` 等）は**事前警告と確認**。`git checkout -f` は明示承認なしに実行しない。
7. **`.env`・秘匿値は絶対にコミットしない**（`.gitignore` 済み）。`.env.example` の秘匿値は空。
8. **デプロイはローカル動作確認＋統括の明示的承認の後のみ**。push 前にコミット対象ファイル一覧を提示して確認。
9. 実装は**テストとセット**で整備し、[[シナモロール]] のレビューを受ける。

## 現状（基盤フェーズ）

- ディレクトリ骨組み・`.gitignore`・`backend/.env.example` を整備。
- `app/config.py`: `DB_BACKEND`（sqlite/mysql/postgresql）シームで接続URLを解決。
- `app/main.py`: アプリファクトリ + CORS + `/api/health`。
- SQLite バックエンドで起動確認済み（`/api/health` → 200）。`pytest` グリーン。
- 未着手（後続）: DB モデル/接続（`app/db/`）、KRE 契約/実装（`kre/`・ロトム）、認証（Entra）、フロント scaffold（イーブイ）。

## 担当

- Web バックエンド基盤: [[ポリゴン]]
- KRE 契約・実装: [[ロトム]]
- フロント: [[イーブイ]]
- 設計: [[キャタピー]] / UI: [[マイメロディ]] / QA: [[シナモロール]]
