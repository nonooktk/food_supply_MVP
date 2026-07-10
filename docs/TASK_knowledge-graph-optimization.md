# タスク依頼書: 知識グラフ・判断継承まわり（KRE）の最適化

対象読者: 本リポジトリを初めて見る Claude（別セッション／別ユーザー）。本書だけを読んで着手できるよう、
必要な背景をすべて記載します。着手前に本書と、参照先として挙げるソースファイルを実際に読んでください。

---

## 1. 背景（アプリ概要）

本リポジトリ「ふりぃらじかるず」は、飲食店向けの**購買交渉支援・相場推定アプリ MVP**です。
仕入担当者が取引先と価格交渉する際に、

1. 交渉前に相場・過去経緯・自社計画を確認し、
2. 目標／着地／撤退の3ライン＋AI交渉シナリオを含む「作戦シート」を生成し、
3. 交渉後の結果（決着単価・決着理由タグ・所感）を構造化記録し、次回の同一商材×取引先案件で自動参照する

という一連の流れを支援します。3番目の「交渉結果を次回に活かす」仕組みが **判断継承ループ（BR-10）** と
呼ばれる本アプリの核心機能で、これを支えているのが本タスクの対象である**知識レイヤー（KRE）**です。

詳細な要件定義は本リポジトリ同梱の [`docs/要件定義書.md`](./要件定義書.md) を参照してください
（§5「モジュール分割と外部委託範囲」が KRE の定義・帰属境界・受け入れ条件の正本です）。

## 2. 知識レイヤーの構造（KRE = Knowledge Retrieval Engine）

KRE はリポジトリ内の Obsidian 的な「相互リンクされた知識」に相当する要素を、購買交渉ドメイン向けに
実装したモジュールです。実装場所は `backend/kre/`。本体アプリ（`backend/app/`）とは
`RetrievalEngine` という契約（Protocol）越しにのみ結合しており、KRE 単体で差し替え可能です。

### 2.1 データフロー概要

```
negotiation_cases / negotiation_results などの業務テーブル（MySQL/SQLite）
        │  build_index.py がドキュメント化・グラフ化
        ▼
  ┌─────────────────────┐        ┌───────────────────────────┐
  │ Azure AI Search       │        │ NetworkX グラフ (JSON永続化) │
  │ （ハイブリッド検索：     │        │  backend/kre/graph/data/    │
  │  BM25 + ベクトル）      │        │  {tenant}.json              │
  └─────────────────────┘        └───────────────────────────┘
        │  vector_store.search()             │  graph_search.build_graph_context()
        └───────────────┬─────────────────────┘
                         ▼
              AzureRetrievalEngine.retrieve()
                (backend/kre/engine.py)
                         │
                         ▼
              RetrieveResult（hits / graph_context / citations）
                         │  RetrievalEngine 契約（backend/kre/contract.py）
                         ▼
                     本体アプリ（app/）
```

### 2.2 ID 名前空間（重要な設計原則）

AI Search のドキュメントとグラフのノードは、共通の論理 ID 名前空間 `{tenant}:{type}:{pk}` を共有します
（例: `t-frd:case:No.500023`、`t-frd:sup:12`、`t-frd:spec:7`）。この共有により、
「AI Search のヒット案件 → グラフ上の同じ案件ノード」の名前引きが O(1) で成立します。

テナント境界は **この ID の接頭辞に埋め込まれています**。検索・グラフの両方で、返却直前に
`enforce_tenant_boundary()`（`backend/kre/stub.py` 内、`engine.py` からも呼ばれる）が
id 接頭辞が要求テナントと一致しない要素を機構的に除去する「第2の防波堤」として働きます。
第1の防波堤は AI Search の OData フィルタ（`vector_store.build_tenant_filter()`）による
`tenant_id eq '<tenant>'` の AND 強制です。この二重防御で「テナント越境ゼロ」を担保しています。

### 2.3 担当モジュール一覧（`backend/kre/`）

| ファイル | 役割 |
|---|---|
| `kre/contract.py` | 本体⇄KRE の唯一の結合面。`RetrievalEngine` Protocol、`RetrieveRequest`/`RetrieveResult` 等のデータ契約、`RetrieveResult` の正準 JSON Schema を定義。**この契約は既存の合意事項であり、変更する場合は本体側（`app/`）への影響を必ず確認すること。** |
| `kre/engine.py` | `RetrievalEngine` の本実装 `AzureRetrievalEngine`。検索→グラフ補完→テナント越境ゼロ強制→`RetrieveResult` 組み立ての順で処理する。`retrieval_config` のノブ（top_k / hybrid_weight / graph.enabled / depth）を反映する。 |
| `kre/stub.py` | 契約テスト・並行開発用のスタブ実装 `StubRetrievalEngine`。`fixtures/` の代表データを返す。`enforce_tenant_boundary()` の実装本体もここにある。`.env` の `USE_KRE_STUB=true`（既定）のとき本体はこちらを DI で注入する。 |
| `kre/retrieval/vector_store.py` | Azure AI Search クライアント。ハイブリッド検索（BM25＋ベクトル）、テナントフィルタの AND 強制、論理ID⇔AI SearchキーのBase64符号化。 |
| `kre/retrieval/embeddings.py` | Azure OpenAI Embeddings ラッパ（`text-embedding-3-small`、1536次元）。 |
| `kre/graph/graph_search.py` | 購買ドメインの GraphRAG（NetworkX＋JSON永続化）。ノード種別（product_spec / supplier / case / rate_change_reason / origin）、エッジ種別（対象商材／取引先／主張変動理由／認めた変動理由／産地／同一商材）、depth 展開＋ハブ展開のロジック本体。 |
| `kre/scripts/build_index.py` | DB → AI Search ドキュメント投入＋グラフ JSON 生成のバッチスクリプト。`--dry-run` で Azure 非接続確認が可能。 |
| `kre/config/retrieval_config.yaml` / `kre/config/loader.py` | 検索・グラフの調整ノブ（本タスクのチューニング対象の中心）。`config_version` で版管理。 |
| `kre/fixtures/*.json` | 契約テスト用の代表 fixture（鶏もも肉／丸紅畜産のシナリオ、他テナント混入データ）。 |
| `kre/services/` | 現状ほぼ未実装（今後の増分同期実装の置き場として想定。タスク(b)参照）。 |

## 3. 環境前提

- **Azure OpenAI / Azure AI Search のキーが必要**（本実装 `AzureRetrievalEngine` を実際に Azure へ
  接続して動かす場合）。`.env.example`（`backend/.env.example`）に必要なキー名を記載しています。
  `cp backend/.env.example backend/.env` してから値を埋めてください。
- **キー未設定でも開発は可能**です。`.env` の `USE_KRE_STUB=true`（既定）のときは `StubRetrievalEngine`
  が同梱 fixture を返すため、Azure 未接続のままロジック開発・契約テストができます。
- DB は SQLite の seed データで開発できます（リポジトリルートの `CLAUDE.md` のセットアップ手順を参照）。
  `python -m app.ingest.seed` でマスタ・サンプル案件データを投入できます。
- テストは `backend/` で `pytest -q`（KRE 関連は `backend/tests/kre/` 配下）。

## 4. 切り出すタスク

(a)〜(d) は KRE（検索・グラフ）まわりのタスクで、独立して着手可能ですが、(d) の契約テスト green は
**(a)〜(c)・(e) 共通の受け入れ条件**です。(e) は相場高騰要因の推定アルゴリズム導入で、
アルゴリズム仕様の受領前後で着手可否が分かれます（詳細は該当節）。(f) は GPT プロンプトの最適化で、
KRE ではなく本体アプリ（`app/llm/`）の領域です。

### (a) 検索チューニング — ハイブリッド検索のスコアリング調整

**背景**: `retrieval_config.yaml` の `search.min_score`（足切りスコア）は設定項目として定義されている
ものの、実装（`kre/retrieval/vector_store.py` の `search()` 関数、`kre/engine.py` の呼び出し箇所）では
一切参照されていません。理由は、Azure AI Search のハイブリッド検索が返す `@search.score` は
RRF（Reciprocal Rank Fusion）由来のスコアで、BM25単体やベクトル単体のスコアと異なりレンジが
安定しないため、固定閾値による足切りが実データ上うまく機能しなかった（採用を見送った）という
実測知見があります。この経緯を踏まえてチューニングしてください。

**対象ファイル**:
- `backend/kre/config/retrieval_config.yaml`（`search.hybrid_weight` / `search.top_k` / `search.min_score` の扱い）
- `backend/kre/config/loader.py`（`SearchConfig` モデル）
- `backend/kre/retrieval/vector_store.py`（`search()`, `_vector_weight()`, `build_tenant_filter()`）
- `backend/kre/engine.py`（`AzureRetrievalEngine.retrieve()` の top_k / hybrid_weight 反映箇所）

**タスク内容**:
1. `top_k` / `hybrid_weight` を実データ（seed データまたは実運用に近いサンプル）で調整し、
   代表クエリ（`kre/fixtures/chicken_thigh_marubeni.json` 等）で関連度を検証する。
2. `min_score` によるスコア足切りが本当に不要か再検証する。不要と判断した場合は
   `retrieval_config.yaml` から項目を削除するか、あるいは「未使用である」ことをコメントで明記する
   （設定ファイル上に「使われない設定」を残さない、または理由を明記するのがゴール）。
3. セマンティック再ランカー（`rerank.enabled`。現状 `false` で未実装）の導入を検討する。
   Azure AI Search のセマンティックランキング機能、またはアプリ側での再ランク実装のどちらが
   適切か比較検討し、実装するなら `kre/engine.py` の `retrieve()` パイプラインに組み込む。

**受け入れ条件**: 既存の契約テスト（後述 §5 の (d)）を green に保ったまま、代表クエリでの
関連度改善が確認できること。`retrieval_config.yaml` の `config_version` を更新すること。

### (b) インデックス・グラフの同期最適化 — 増分同期の実装

**背景**: 現在の索引・グラフ更新は `kre/scripts/build_index.py` を手動またはバッチで実行する方式のみです。
`kre/engine.py` の `AzureRetrievalEngine.index_upsert()` は、取込イベントを受けても「同期時刻と
件数の擬似更新」に留まり、実際の索引・グラフへの反映は行いません（メソッドの docstring に
明記されている既知の未実装箇所です）。`retrieval_config.yaml` の `sync.mode` ノブ
（`on_write` | `scheduled`）はすでに設定として存在しますが、実装は伴っていません。

**対象ファイル**:
- `backend/kre/engine.py`（`index_upsert()` メソッド。現状は doc_count・last_sync_at の擬似更新のみ）
- `backend/kre/services/`（現状ほぼ空。増分同期の indexer 実装の置き場として想定されている）
- `backend/kre/scripts/build_index.py`（バッチ全件再構築の既存実装。増分版の参考にする）
- `backend/kre/config/retrieval_config.yaml` の `sync.mode` / `sync.interval`
- `backend/kre/contract.py` の `IndexEvent`（本体からの取込契約。`op: upsert|delete`, `entity`, `pk`, `payload?`）

**タスク内容**:
1. `sync.mode: on_write` のとき、本体が `index_upsert(IndexEvent)` を呼んだ契機で、該当1件のみを
   AI Search ドキュメントとグラフへ即時反映する実装を `kre/services/` 配下に追加する。
   （全件再構築ではなく、単発 upsert/delete の差分反映であることに注意。）
2. `sync.mode: scheduled` のときの定期実行（バッチジョブ想定）の設計・実装方針を検討し、
   `sync.interval` の反映方法（cron 相当の仕組み、または呼び出し側の責務として整理するか）を決める。
3. グラフ側（`kre/graph/graph_search.py` の `save_graph_records`/`load_graph_records`）は
   テナント単位1ファイルの全件書き出しのみに対応している。増分更新（1ノード/エッジの追加削除）に
   対応させるか、許容できる頻度なら全件再書き出しのままにするかを判断し、理由を記録する。

**受け入れ条件**: `index_upsert()` 呼び出し後、`health()` の `doc_count` / `last_sync_at` だけでなく
実際の検索結果・グラフにも反映が確認できること。既存契約テスト（§5 (d)）が green のまま。

### (c) グラフ補完の品質向上

**背景**: 現在のグラフ補完（`kre/graph/graph_search.py` の `build_graph_context()`）は
depth=1 の隣接展開＋ハブ展開（supplier / rate_change_reason 経由）で
「同一取引先の別商材」「同一変動理由の他社事例」を補完しています。これは要件定義書 §5.4
受け入れ条件(3)で明示された必須機能です。MVP は NetworkX＋JSON 永続化ですが、将来
ノード数が増えた場合の Cosmos DB (Gremlin) 移行が要件定義書・アーキ設計書側で想定されています。

**対象ファイル**:
- `backend/kre/graph/graph_search.py`（`build_graph_context()`, `PurchasingGraph`, `_summarize()`）
- `backend/kre/config/retrieval_config.yaml` の `graph.node_types` / `graph.edge_types` / `graph.max_neighbors`
- `backend/tests/kre/test_graph_search.py`（既存のグラフ挙動テスト。精度評価の土台にする）

**タスク内容**:
1. depth=1 隣接補完の精度評価: 実際の交渉ケース（またはより現実的な seed データ）に対して、
   「補完されるべきなのに漏れているケース」「補完されているがノイズになっているケース」を
   洗い出し、`build_graph_context()` のハブ展開ロジック（`hubs` 集合の扱い、`max_neighbors` の上限）
   を調整する。
2. エッジ種別の追加を検討する。現状のエッジ種別は `対象商材` `取引先` `主張変動理由`
   `認めた変動理由` `産地` `同一商材` の6種（`retrieval_config.yaml` の `graph.edge_types` と
   `graph_search.py` の `build_graph_records()` 双方に定義がある）。
   例えば「産地・時期近接」（同一産地×近い年月の相場変動を関連付ける）などの新エッジ種別を
   追加する場合、(i) `build_graph_records()` でのエッジ生成ロジック追加、(ii) `retrieval_config.yaml`
   の `edge_types` への追加、(iii) `RetrieveResult.graph_context` のスキーマ自体は
   `contract.py` の `GraphEdge`（`src`/`dst`/`relation` の汎用構造）を変更せずに済むはずなので、
   契約変更が本当に不要か確認する、の3点をセットで行うこと。
3. **ノード数増加時の Cosmos DB (Gremlin) 移行判断条件を本ファイルまたは
   `kre/graph/graph_search.py` のモジュール docstring に明記する**。目安として
   「1テナントあたりノード数 5万件超」を移行検討の閾値とする（要件定義書・アーキ設計書の
   想定を踏襲した目安値。実データで再検証し、必要なら閾値を更新すること）。
   移行時は `PurchasingGraph`（現状 NetworkX ラッパ）のインターフェースを保ったまま、
   内部実装のみ Gremlin クライアントに差し替えられる設計にする（`build_graph_context()` を
   呼び出す `kre/engine.py` 側への影響をゼロにすることが目標）。

**受け入れ条件**: 代表クエリ（`kre/fixtures/`）で「同一取引先の別商材」「同一変動理由の他社事例」の
補完が引き続き機能すること（既存契約テストの受け入れ条件3）。新エッジ種別を追加した場合は
対応するテストを `backend/tests/kre/test_graph_search.py` に追加すること。

### (d) 契約テストの維持 — 全タスク共通の絶対条件

**これは (a)〜(c) のどのタスクを行う場合でも必ず満たすべき、変更してはいけない受け入れ条件です。**

**背景**: KRE と本体アプリの結合面は `backend/kre/contract.py` の `RetrievalEngine` Protocol と
`RetrieveResult` の JSON Schema に固定されています。本体は KRE の内部実装を知らずにこの契約だけで
実装されているため、契約を破る変更（フィールドの削除・型変更・テナント越境の抜け穴など）は
本体側の実装を壊します。

**対象**: `backend/tests/kre/` 配下すべて。
- `test_contract.py` … `RetrieveResult` が JSON Schema（`RETRIEVE_RESULT_JSON_SCHEMA`）に適合すること、
  `StubRetrievalEngine` が `RetrievalEngine` Protocol を満たすこと。
- `test_tenant_isolation.py` … **テナント越境ゼロ**の検証。他テナント fixture を意図的に混入させ、
  `enforce_tenant_boundary()` が hit / node / edge / citation のいずれからも漏らさず除去することを確認する。
- `test_stub_contract.py` / `test_engine.py` / `test_vector_store_filter.py` / `test_graph_search.py` /
  `test_build_index_docs.py` … 各モジュールの単体テスト。

**タスク内容**:
1. (a)〜(c) のいずれかを実装した後、必ず `backend/` で `pytest tests/kre -q` を実行し、
   全テスト green を確認する。
2. 契約（`contract.py` のモデル・JSON Schema）自体を変更する必要が生じた場合は、
   後方互換性（本体側 `app/` の呼び出し箇所への影響）を必ず確認し、破壊的変更であれば
   requirements.txt のバージョン管理と同様に慎重に扱う。契約変更は原則避け、
   どうしても必要な場合はその理由と影響範囲を明記すること。
3. 特に **テナント越境ゼロ**（`test_tenant_isolation.py`）は、いかなるチューニング・機能追加でも
   絶対に緩めてはならない。新しいノード種別・エッジ種別・検索フィールドを追加した場合は、
   それらも `enforce_tenant_boundary()` の除去対象に含まれているか（id 接頭辞判定の対象に
   なっているか）を必ず確認する。

**受け入れ条件**: `pytest tests/kre -q` が green であること。これが (a)〜(c)・(e) すべての作業の
最終的な受け入れ条件です（(f) はプロンプト領域のため対象外。代わりに後述の数値捏造ゼロガードテストが
対応する受け入れ条件になります）。

### (e) 相場高騰要因の推定アルゴリズムの導入と調整

**背景**: 相場データ（`market_rates` テーブル）と変動理由マスタ（`rate_change_reasons`。RC-01〜10）
から「なぜ相場が高騰しているか」の要因を推定する機能です。この機能は**GraphRAG（`backend/kre/graph/`）
への影響が大きく**、変動理由ノード・エッジの拡張や、要因間の関連づけ（例: 「飼料価格高騰」と
「為替変動」が同時期に相場を押し上げているといった複合要因の表現）が必要になる見込みです。

**重要な前提: 想定アルゴリズムの情報は発注元から入手予定で、現時点では未着です。**
そのため本タスクは、

- **(e-1) 先行タスク（アルゴリズム仕様の受領前に着手可能）**
- **(e-2) 本タスク（アルゴリズム仕様の受領後に着手）**

の2段階に分けて進めてください。**(e-2) にはアルゴリズム仕様が届くまで着手しないでください。**

#### (e-1) 先行タスク（着手可能）

**対象ファイル**:
- `backend/app/db/models.py`（`MarketRate`, `RateChangeReason` のモデル定義。§2.1・§2.2 相当のテーブル）
- `backend/kre/graph/graph_search.py`（`build_graph_records()` の変動理由ノード生成箇所 `add_rc()`、
  エッジ種別 `主張変動理由` / `認めた変動理由`）
- `backend/kre/config/retrieval_config.yaml` の `graph.node_types` / `graph.edge_types`

**タスク内容**:
1. **データ構造の確認**: `market_rates`（`year_month`, `price_yen_kg`, `yoy_change` 等）と
   `rate_change_reasons`（RC-01〜10 の固定マスタ）、および `negotiation_cases.claimed_reasons` /
   `negotiation_results.accepted_reasons`（案件ごとに紐づく変動理由タグ）の関係を整理する。
   現状は「案件に対して変動理由タグが付与される」構造であり、「相場の時系列変動そのものに
   要因を紐づける」構造は未整備であることを確認する。
2. **変動理由タグと相場時系列の突き合わせ基盤づくり**: 同一 `spec_id`（規格）について、
   `market_rates` の年月推移と、その期間に発生した案件（`negotiation_cases`）の `claimed_reasons` /
   `accepted_reasons` を時系列で突き合わせられるクエリ・ビュー（またはサービス関数）を用意する。
   これは推定アルゴリズム本体ではなく、**アルゴリズムに食わせる入力データを揃える下ごしらえ**です。
3. **アルゴリズム差し替え可能なインターフェース設計**: 本プロジェクトの調整シーム思想
   （リポジトリルート `CLAUDE.md` の「調整シーム」節を参照。未確定要件は設定／インターフェース
   差し替えで吸収する）と同じ考え方で、将来の推定アルゴリズムを差し替え可能にする受け皿
   （例: `EstimationEngine` Protocol のような抽象化）を設計する。アーキ設計上、これは Phase 2 の
   「相場推定エンジン」（要件定義書 F-11）につながる位置づけです。実装は空実装／ダミー実装で構わない
   （KRE の `StubRetrievalEngine` と同様、契約だけ先に固定し実装は後追いする方針）。

**受け入れ条件（e-1）**: 既存の契約テスト（本ファイル §4 (d)）を green に保ったまま、
上記のデータ突き合わせ基盤とインターフェース設計（契約）が用意されていること。
まだ推定ロジック本体は実装しないため、生成される推定結果の精度は評価対象外です。

#### (e-2) 本タスク（アルゴリズム仕様の受領後に着手）

**対象ファイル**:
- (e-1) で設計した `EstimationEngine` 相当のインターフェース
- `backend/kre/graph/graph_search.py`（変動理由ノード・エッジの拡張、要因間の関連づけ）
- `backend/kre/config/retrieval_config.yaml`（新規ノブが必要になった場合の追加）

**タスク内容**:
1. 発注元から受領したアルゴリズム仕様に基づき、(e-1) で用意した受け皿インターフェースの
   実装を追加する。
2. GraphRAG 側の拡張（変動理由ノードの関連づけ、必要であれば新エッジ種別の追加）を行う。
   エッジ種別を追加する場合は本ファイル §4 (c) の手順（`build_graph_records()` への追加・
   `retrieval_config.yaml` の `edge_types` への追加・契約変更要否の確認）に準じること。
3. アルゴリズムのパラメータ（閾値・重み等）は `retrieval_config.yaml` 相当の設定ファイルへ
   外部化し、本体コードを変更せずに調整できるようにする。

**受け入れ条件（e-2）**: アルゴリズムが**設定／インターフェース差し替えで交換可能**であること
（本プロジェクトの調整シーム思想に従う）。`pytest tests/kre -q` の契約テストが green のまま
維持されていること。

### (f) GPT に渡すプロンプトの最適化

**背景**: 交渉ポイント／シナリオ生成（FR-08 の最終生成）のプロンプトは `backend/app/llm/prompts.py`
に集約されています。現状の品質ガードは**維持が絶対条件**です。具体的には:

- AI は価格（数値）を決めない・作らない。目標／着地／撤退の3ラインと過去決着単価は、
  本体が算出・記録した値をそのまま引用するのみ（`POINTS_SYSTEM_PROMPT` / `SCENARIO_SYSTEM_PROMPT`
  冒頭の「絶対に守るルール」）。
- 価格以外の数値（数量・年間発注量・原価率・前年比・割合・期間等）も、与えられた事実
  （コンテキスト）に明記された値だけを使う。事実にない数値・概算・推測値を書かない。
- 引用（`citation_case_nos`）は実在する過去案件番号のみを使う。
- AI は判断材料の整理に徹し、交渉の意思決定自体は行わない。

**対象ファイル**:
- `backend/app/llm/prompts.py`（`POINTS_SYSTEM_PROMPT` / `POINTS_USER_PROMPT_TEMPLATE` /
  `SCENARIO_SYSTEM_PROMPT` / `SCENARIO_USER_PROMPT_TEMPLATE`）
- `backend/app/llm/strategy_generator.py`（`build_context_text()` でコンテキストを整形し、
  `generate_strategy()` で並列にポイント／シナリオを生成する。プロンプトインジェクション対策
  として `_escape_braces()` で中括弧をエスケープしている点に注意）
- 評価は `backend/tests/test_strategy_generator.py` の `RUN_REAL_AI=1` 統合テスト経路
  （既定ではスキップされる実 Azure OpenAI 呼び出しテスト。課金が発生するため通常の CI では
  実行しない設計）
- モデルバージョン管理は `model_versions` テーブル（`backend/app/db/models.py` の
  `ModelVersion`。`model_type="ai_prompt"` として `definition`（JSON）にプロンプトを版管理し、
  `version_label` で版を上げる運用を想定。3ライン算出式 `CALC_RULE_V1` と同じ運用パターン
  ＝`backend/app/db/seams.py` を参照）

**タスク内容**:
1. **生成品質の評価軸づくり**: 少なくとも次の3軸で評価基準を明文化する。
   - 実務で使える具体性（担当者が明日の交渉でそのまま使えるか。抽象的な一般論になっていないか）
   - 引用の適切さ（`citation_case_nos` が実在案件かつ文脈上妥当か。過不足がないか）
   - 冗長さ（同じ内容の繰り返し・不要な前置きがないか。3件のポイントが互いに重複していないか）
2. **プロンプト改善の反復**: 評価軸に基づき `prompts.py` のプロンプト文言を改善する。
   1回の変更ごとに `RUN_REAL_AI=1 pytest tests/test_strategy_generator.py -q` で実 Azure OpenAI
   呼び出しを行い、生成結果を評価軸に沿って確認する（課金が発生するため、変更をまとめてから
   実行するなど呼び出し回数に配慮すること）。
3. **版管理**: プロンプトを変更したら `model_versions` テーブルに新しい `version_label` で
   投入する運用に合わせる（既存の `CALC_RULE_V1` / `CALC_RULE_V09` のパターンを踏襲）。
   `app/ingest/seed.py` の該当箇所（`model_versions` 投入部）を参考にすること。

**受け入れ条件**: 品質ガード（数値捏造ゼロ・引用は実在案件のみ）を検証するテストが green の
まま維持されていること。具体的には `backend/tests/test_strategy_generator.py` の
`test_prompts_forbid_fabricated_numbers`（プロンプトが数値捏造を禁止する文言を含むことの検証）と
`test_generated_output_only_uses_context_numbers`（生成結果がコンテキストに無い数値を含まないことの
検証）の2テストで、これらは `RUN_REAL_AI` 有無に関わらず（モックでも）green を保つこと。加えて、
プロンプト変更の提案時には**生成結果の before/after 比較**（変更前後のポイント／シナリオ出力例）を
提示すること。

## 5. 進め方の推奨

1. まず `backend/` で環境構築し（リポジトリルートの `CLAUDE.md` のセットアップ手順に従う）、
   `pytest -q`（全体）と `pytest tests/kre -q`（KRE のみ）が green な状態から着手する。
2. (a)〜(c) は独立性が高いため、優先順位や並行着手は状況に応じて判断してよい。
   ただし各タスク完了時に必ず (d) の契約テストを回すこと。
3. (e) はまず (e-1) 先行タスクから着手する。**(e-2) はアルゴリズム仕様の受領を待ってから着手する**
   （受領前に着手しない）。
4. (f) は KRE と独立した領域（`app/llm/`）なので、(a)〜(e) と並行して進めてよい。ただし品質ガード
   （数値捏造ゼロ）のテストは他タスクの有無に関わらず常に green を維持すること。
5. `retrieval_config.yaml` を変更した場合は `config_version` を更新し、変更理由をコメントに残す
   （既存の運用慣習。ファイル冒頭のコメントを参照）。プロンプト（(f)）を変更した場合は
   `model_versions` テーブルへ新しい版として投入する運用に合わせる。
6. 本ドキュメントおよび `docs/要件定義書.md` に記載のない実装判断（契約変更の要否、Cosmos DB
   移行の実施タイミング、推定アルゴリズムの受け皿インターフェースの詳細設計など）は、
   コミットメッセージまたはコード内コメントに根拠を残すこと。
