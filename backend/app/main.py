"""main.py — FastAPI アプリのエントリポイント（アプリファクトリ）。

``create_app()`` でアプリを構築し、モジュール末尾で ``app`` を公開する。
起動例:
    cd backend
    uvicorn app.main:app --reload

設計 v3 §5 の DI コンテナ（RetrievalEngine の stub ⇄ 本実装 差し替え）は、
KRE 契約（kre/contract.py・ロトム担当）確定後にこの create_app 内で組み立てる。
現段階はヘルスチェックと CORS までの最小構成。
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, cases, health, lines, plans, rates, results, search, strategy, suppliers
from app.config import get_settings
from app.errors import register_exception_handlers


def create_app() -> FastAPI:
    """FastAPI アプリを構築して返すファクトリ。"""
    settings = get_settings()

    # 本番では API ドキュメント（/docs・/redoc・/openapi.json）を出さない（監査 F-14）。
    # 全エンドポイント・スキーマ・パラメータ名の一覧は攻撃者にとって設計図そのもの。
    # 開発時は従来どおり公開する（セットアップ手順の動線を壊さない）。
    docs_enabled = not settings.is_production

    app = FastAPI(
        title="ふりぃらじかるず API",
        description="購買交渉支援アプリ MVP のバックエンド API。",
        version="0.1.0",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    # CORS: フロント（Next.js）の配信元のみを許可する。
    # google モードは Authorization ヘッダー、mock モードは X-Tenant-Id / X-User-Id と
    # 冪等キーを使う。いずれも allow_headers=["*"] の範囲に含まれる。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):  # noqa: ANN001, ANN202
        """全レスポンスにセキュリティヘッダーを付与する（監査 F-15）。

        X-Content-Type-Options: nosniff … ブラウザの MIME スニッフィングを止め、
        JSON/テキスト応答が HTML/スクリプトとして解釈される事故を防ぐ。
        """
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response

    # RFC7807（problem+json）の例外ハンドラを登録する。
    register_exception_handlers(app)

    # ルータ登録。すべての API は /api 配下に置く。
    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(cases.router, prefix="/api")
    app.include_router(suppliers.router, prefix="/api")
    app.include_router(rates.router, prefix="/api")
    app.include_router(plans.router, prefix="/api")
    app.include_router(lines.router, prefix="/api")
    app.include_router(search.router, prefix="/api")
    app.include_router(strategy.router, prefix="/api")
    app.include_router(results.router, prefix="/api")

    return app


app = create_app()
