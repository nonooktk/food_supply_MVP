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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.config import get_settings


def create_app() -> FastAPI:
    """FastAPI アプリを構築して返すファクトリ。"""
    settings = get_settings()

    app = FastAPI(
        title="ふりぃらじかるず API",
        description="購買交渉支援アプリ MVP のバックエンド API。",
        version="0.1.0",
    )

    # CORS: フロント（Next.js）の配信元のみを許可する。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ルータ登録。すべての API は /api 配下に置く。
    app.include_router(health.router, prefix="/api")

    return app


app = create_app()
