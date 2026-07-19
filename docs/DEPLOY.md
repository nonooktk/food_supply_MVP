# デプロイ手順書 — ふりぃらじかるず（Azure Container Apps）

りなれす方式に倣い、既存リソースへ相乗りして追加費用を最小化する。**リソース作成・ライブ切替は
コーディネーターがメインセッションで実行する**（本書はそのコマンド列）。ポリゴンはここまでの準備
（Dockerfile / .dockerignore / 本書）を担当。

## 前提（既存リソース・確認済み）

| 項目 | 値 |
|---|---|
| リソースグループ | `rg-001-gen12`（Japan East） |
| ACR（相乗り） | `acrrinaresua37c`（`acrrinaresua37c.azurecr.io`） |
| Container Apps 環境（相乗り） | `cae-rinaresu` |
| DB | Tech0 MySQL `mysql-gen12-class3.mysql.database.azure.com` / db `freeradicals`（スキーマ・seed 投入済み） |
| 新規アプリ | `ca-freeradicals-api`（backend）/ `ca-freeradicals-web`（frontend） |
| イメージ | `freeradicals-api:v1` / `freeradicals-web:v1` |

- DB は Azure 内から AllowAllAzureServices で接続可（TLS 必須。アプリは SSLContext で対応済み）。
- AI Search インデックス（`negotiation-docs-v1`）はクラウド側に既存。**再投入不要**。
- KRE グラフ JSON は起動時に `build_index --graph-only` で自動生成（`BUILD_GRAPH_ON_BOOT=true`・埋め込み課金なし）。

> 秘匿値（DB パスワード / AOAI キー / AI Search キー / DB ユーザ / 各エンドポイント）は `backend/.env`
> から転記する。本書は `<...>` プレースホルダで示す。**`.env` はコミット・イメージ同梱しない。**

---

## 0. ログインと変数

```bash
az login
az account set --subscription "<りなれすと同一サブスクリプションID>"

RG=rg-001-gen12
ACR=acrrinaresua37c
ACR_LOGIN=acrrinaresua37c.azurecr.io
ENVNAME=cae-rinaresu
API_APP=ca-freeradicals-api
WEB_APP=ca-freeradicals-web
TAG=v1
```

---

## 1. backend イメージをビルド（ACR 内ビルド・ローカル docker 不要）

`backend/` をコンテキストに ACR でビルド＆プッシュする。

```bash
az acr build \
  --registry "$ACR" \
  --image "freeradicals-api:$TAG" \
  --file backend/Dockerfile \
  backend
```

---

## 2. backend アプリを作成（secrets + env-vars）

秘匿値は `--secrets` に登録し、`--env-vars` から `secretref:` で参照する（値をログに残さない）。
CORS_ORIGINS は web の URL が未確定のため、まず暫定（`*` ではなく後で 6 で更新）。

```bash
az containerapp create \
  --name "$API_APP" \
  --resource-group "$RG" \
  --environment "$ENVNAME" \
  --image "$ACR_LOGIN/freeradicals-api:$TAG" \
  --registry-server "$ACR_LOGIN" \
  --target-port 8000 \
  --ingress external \
  --min-replicas 1 --max-replicas 1 \
  --secrets \
      db-password="<DB_PASSWORD>" \
      aoai-key="<AZURE_OPENAI_API_KEY>" \
      search-key="<AZURE_SEARCH_API_KEY>" \
  --env-vars \
      APP_ENV=production \
      DB_BACKEND=mysql \
      DB_HOST=mysql-gen12-class3.mysql.database.azure.com \
      DB_PORT=3306 \
      DB_NAME=freeradicals \
      DB_USER="<DB_USER>" \
      DB_PASSWORD=secretref:db-password \
      DB_SSL_DISABLED=false \
      USE_KRE_STUB=false \
      BUILD_GRAPH_ON_BOOT=true \
      AZURE_OPENAI_ENDPOINT="<AZURE_OPENAI_ENDPOINT>" \
      AZURE_OPENAI_API_KEY=secretref:aoai-key \
      AZURE_OPENAI_API_VERSION=2024-08-01-preview \
      AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o \
      AZURE_OPENAI_EMBED_DEPLOYMENT=text-embedding-3-small \
      AZURE_SEARCH_ENDPOINT="<AZURE_SEARCH_ENDPOINT>" \
      AZURE_SEARCH_API_KEY=secretref:search-key \
      AZURE_SEARCH_INDEX_NAME=negotiation-docs-v1 \
      AUTH_MODE=google \
      GOOGLE_CLIENT_ID="<GOOGLE_CLIENT_ID>" \
      CORS_ORIGINS=https://placeholder.invalid
```

> `--registry-server` を渡すと Container Apps が ACR プルを自動構成する（同一サブスクリプション・
> 権限がある前提）。うまくいかない場合は ACR 管理者資格情報を明示指定:
> `--registry-username $(az acr credential show -n $ACR --query username -o tsv)`
> `--registry-password $(az acr credential show -n $ACR --query 'passwords[0].value' -o tsv)`

**非秘匿 env 一覧**（上記のうち値を平文で入れるもの）: `APP_ENV / DB_BACKEND / DB_HOST / DB_PORT /
DB_NAME / DB_USER / DB_SSL_DISABLED / USE_KRE_STUB / BUILD_GRAPH_ON_BOOT / AZURE_OPENAI_ENDPOINT /
AZURE_OPENAI_API_VERSION / AZURE_OPENAI_CHAT_DEPLOYMENT / AZURE_OPENAI_EMBED_DEPLOYMENT /
AZURE_SEARCH_ENDPOINT / AZURE_SEARCH_INDEX_NAME / AUTH_MODE / GOOGLE_CLIENT_ID / CORS_ORIGINS`。
**secrets（secretref 参照）**: `DB_PASSWORD / AZURE_OPENAI_API_KEY / AZURE_SEARCH_API_KEY`。

backend の URL を取得:

```bash
API_FQDN=$(az containerapp show -g "$RG" -n "$API_APP" --query properties.configuration.ingress.fqdn -o tsv)
echo "backend: https://$API_FQDN"
```

---

## 3. frontend イメージをビルド（NEXT_PUBLIC_* をビルド時埋め込み）

`NEXT_PUBLIC_*` はビルド時にバンドルへ焼き込まれるため、backend URL 確定後にビルドする。

```bash
az acr build \
  --registry "$ACR" \
  --image "freeradicals-web:$TAG" \
  --file frontend/Dockerfile \
  --build-arg NEXT_PUBLIC_API_BASE="https://$API_FQDN/api" \
  --build-arg NEXT_PUBLIC_GOOGLE_CLIENT_ID="<GOOGLE_CLIENT_ID>" \
  --build-arg NEXT_PUBLIC_USE_MOCK=false \
  --build-arg NEXT_PUBLIC_AUTH_MODE=google \
  frontend
```

---

## 4. frontend アプリを作成

```bash
az containerapp create \
  --name "$WEB_APP" \
  --resource-group "$RG" \
  --environment "$ENVNAME" \
  --image "$ACR_LOGIN/freeradicals-web:$TAG" \
  --registry-server "$ACR_LOGIN" \
  --target-port 3000 \
  --ingress external \
  --min-replicas 1 --max-replicas 1

WEB_FQDN=$(az containerapp show -g "$RG" -n "$WEB_APP" --query properties.configuration.ingress.fqdn -o tsv)
echo "frontend: https://$WEB_FQDN"
```

---

## 5. backend の CORS を web の URL に更新

```bash
az containerapp update \
  --name "$API_APP" --resource-group "$RG" \
  --set-env-vars CORS_ORIGINS="https://$WEB_FQDN"
```

---

## 6. Google OAuth の設定（重要）

GCP コンソール（プロジェクト `food-supply-502014`）で、対象の OAuth クライアントの
**「承認済みの JavaScript 生成元」に `https://<WEB_FQDN>` を追加**する。
（GIS はオリジン厳格。未登録だとボタンは出てもトークン発行で失敗する。）

---

## 7. デプロイ後スモーク

```bash
# リビジョンが Running/Healthy か
az containerapp revision list -g "$RG" -n "$API_APP" \
  --query "[].{name:name,active:properties.active,health:properties.healthState,replicas:properties.replicas}" -o table
az containerapp revision list -g "$RG" -n "$WEB_APP" \
  --query "[].{name:name,active:properties.active,health:properties.healthState}" -o table

# backend ヘルス（200 期待）
curl -fsS "https://$API_FQDN/api/health" ; echo

# 変動理由マスタ（DB 接続の確認・要ヘッダー無しの共有マスタ）
curl -fsS "https://$API_FQDN/api/reasons" | head -c 200 ; echo

# ブラウザで https://$WEB_FQDN を開き、Google ログイン → 案件一覧が実データで出ることを確認。
```

起動ログ（グラフ自動生成の確認）:

```bash
az containerapp logs show -g "$RG" -n "$API_APP" --tail 50 | grep -i "entrypoint\|graph\|uvicorn"
# 期待: "[entrypoint] グラフJSONが無いため build_index --graph-only を実行します..." → 生成 → uvicorn 起動
```

---

## ロールバック / 更新

- イメージ更新: `az acr build ... --image freeradicals-api:v2` → `az containerapp update -n $API_APP -g $RG --image $ACR_LOGIN/freeradicals-api:v2`。
- 旧リビジョンへ戻す: `az containerapp revision list ...` で名前を確認し
  `az containerapp ingress traffic set -g $RG -n $API_APP --revision-weight <旧リビジョン>=100`。

## 注意

- `.env` および秘匿値はイメージへ入れない（`.dockerignore` で除外・env/secrets で注入）。
- backend は `--min-replicas 1 --max-replicas 1`（KRE グラフのインメモリ常駐＋起動時グラフ生成の
  一貫性のため単一レプリカ運用。スケールが必要になったらグラフ供給を共有ストレージ化する）。
- 結果記録などで DB を更新しても、KRE の AI Search 反映は `build_index` 再実行（手動/バッチ）が必要
  （リアルタイム同期は将来課題）。

## 追記（2026-07-19）: フロントビルドは最小コンテキスト方式で行う

`az acr build` をリポジトリ内 `frontend/` から直接実行すると、コンテキスト梱包時に
`node_modules`（数十万ファイル）の走査が発生し、**iCloud 同期対象ディレクトリ（Desktop 配下）では
実体取得と重なって数十分単位で停滞する**（2026-07-19 の v2 デプロイで実発生）。

対策: 除外対象を含まない最小コンテキストをローカル領域へ切り出してからビルドする。

```bash
CTX=$(mktemp -d)/fr-web-ctx
mkdir -p "$CTX"
rsync -a --delete --exclude node_modules --exclude .next --exclude out --exclude build \
  --exclude dist --exclude ".env" --exclude ".env.local" --exclude .turbo --exclude .git \
  frontend/ "$CTX/"
cd "$CTX" && az acr build --registry $ACR --image "freeradicals-web:$TAG" --file Dockerfile \
  --build-arg NEXT_PUBLIC_API_BASE="https://$API_FQDN/api" \
  --build-arg NEXT_PUBLIC_GOOGLE_CLIENT_ID="<GOOGLE_CLIENT_ID>" \
  --build-arg NEXT_PUBLIC_USE_MOCK=false \
  --build-arg NEXT_PUBLIC_AUTH_MODE=google .
```

（backend はコンテキストが小さいため従来どおりで可。約684KB・ビルド約1分半で完了する。）
