"""health.py — ヘルスチェックエンドポイント。

死活監視・起動確認用の軽量エンドポイント。外部依存（DB・AI Search・AOAI）には
アクセスせず、プロセスが応答可能かと現在の設定サマリのみを返す。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """200 とヘルス情報を返す。"""
    settings = get_settings()
    return {
        "status": "ok",
        "service": "freeradicals-backend",
        "app_env": settings.app_env,
        "db_backend": settings.db_backend.value,
        "use_kre_stub": settings.use_kre_stub,
    }
