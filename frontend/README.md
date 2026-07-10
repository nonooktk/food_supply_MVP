# ふりぃらじかるず フロントエンド

購買交渉支援アプリ MVP のフロントエンド（Next.js 16 App Router + TypeScript + Tailwind v4）。

- デザイン正本: `../docs/design-guide.md`（マイメロディ作成）
- 要件: 要件定義書 v3 §2（F-01/02/04/05 が画面①②③に対応）
- バックエンド（FastAPI）は並行実装中のため、当面 **モックデータ**（`NEXT_PUBLIC_USE_MOCK=true`）で動作する。

## セットアップと起動

```bash
cd frontend

# 依存インストール（初回のみ）
npm install

# 環境変数を用意（既定はモックで動く）
cp .env.example .env.local

# 開発サーバ起動 → http://localhost:3000
npm run dev
```

デモ用ログイン: テナント `freeradicals` / ID `tanaka` / パスワード `demo1234`

## 検証

```bash
npm run build   # 本番ビルド（型チェック込み）
npm run lint    # ESLint
```

## 画面構成（Task #6 実装範囲）

| ルート | 画面 | 要件 |
|---|---|---|
| `/login` | ログイン（モック認証。Entra は Sprint 2） | N-02 |
| `/cases` | ① 案件一覧／作成（検索・状態フィルタ） | F-01・FR-10 |
| `/cases/[caseNo]/collect` | ② 情報収集（相場・過去経緯・自社計画） | F-02・F-03・F-04 |
| `/cases/[caseNo]/lines` | ③ 3ライン算出（算出・手修正・理由記録） | F-05 |
| `/master` | マスタ管理（枠のみ・後続スプリント） | F-08 |

②③は「案件ワークスペース」（`/cases/[caseNo]/layout.tsx`）内のステップとして実装。作戦シート④・結果記録⑤は後続スプリント。

## API クライアント層（切替シーム）

画面は必ず `src/lib/api.ts` の `api` 経由でデータアクセスする（`fetch` を画面に直書きしない）。

- `NEXT_PUBLIC_USE_MOCK=true`（既定）: `MockApi`（`src/lib/mock/` の fixture ＋ localStorage ストア）
- `NEXT_PUBLIC_USE_MOCK=false`: `RealApi`（`NEXT_PUBLIC_API_BASE` の FastAPI と通信）

実 API が揃ったら `.env.local` の `NEXT_PUBLIC_USE_MOCK=false` と `NEXT_PUBLIC_API_BASE` を設定する。エンドポイントの形はポリゴンと擦り合わせて確定する。

## ディレクトリ

```
src/
├── app/                    App Router（各画面）
│   ├── login/
│   ├── cases/              ①一覧・作成モーダル
│   │   └── [caseNo]/       案件ワークスペース（layout=共通ヘッダー＋ステップ）
│   │       ├── collect/    ②情報収集
│   │       └── lines/      ③3ライン算出
│   └── master/
├── components/
│   ├── AppChrome.tsx       AuthGuard / TopBar
│   └── ui/                 共通コンポーネント（DataTable / Form / ThreeLineCard 等）
└── lib/
    ├── types.ts            ドメイン型
    ├── api.ts              API クライアント（モック/実API 切替）
    ├── calc.ts             3ライン算出・年間影響額（純粋関数）
    ├── auth.tsx            モック認証コンテキスト
    ├── store.ts            モック用 localStorage ストア
    └── mock/data.ts        fixture（鶏もも肉/丸紅畜産 ¥620/kg 等）
```
