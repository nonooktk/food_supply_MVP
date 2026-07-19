"""errors.py — RFC7807 (problem+json) エラー応答と冪等キー基盤。

PoC（api/analyses.py）の RFC7807・冪等キーのパターンを本プロジェクト向けに整理する。
- ``ApiProblem``: 業務例外。ハンドラが application/problem+json で返す。
- 例外ハンドラ: HTTPException / RequestValidationError / ApiProblem を problem+json 化。
- ``IdempotencyStore``: Idempotency-Key による重複実行防止（MVP はプロセス内メモリ）。
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_CONTENT_TYPE = "application/problem+json"


class ApiProblem(Exception):
    """RFC7807 形式で返す業務例外。

    例: ``raise ApiProblem(404, "案件が見つかりません", detail="No.500001 は存在しません")``
    """

    def __init__(
        self,
        status: int,
        title: str,
        *,
        detail: str = "",
        type_: str = "about:blank",
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(title)
        self.status = status
        self.title = title
        self.detail = detail
        self.type = type_
        self.extra = extra or {}


def _json_safe(value: Any) -> Any:
    """非有限 float（inf / -inf / nan）を文字列化して JSON 安全にする。

    starlette の JSONResponse は ``json.dumps(..., allow_nan=False)`` を使うため、
    検証エラー詳細（``exc.errors()`` の ``input`` / ``ctx`` 等）に非有限 float が
    含まれると ``ValueError`` で 500 に化ける。dict / list を再帰的に走査し、
    非有限 float のみ ``str()`` に変換する（それ以外の値・構造は変えない）。
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _problem_body(status: int, title: str, detail: str, type_: str, extra: dict) -> dict:
    body = {"type": type_, "title": title, "status": status}
    if detail:
        body["detail"] = detail
    body.update(extra)
    return body


def _problem_response(status: int, title: str, detail: str = "", type_: str = "about:blank", extra: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type=PROBLEM_CONTENT_TYPE,
        content=_problem_body(status, title, detail, type_, extra or {}),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """アプリに RFC7807 の例外ハンドラを登録する。"""

    @app.exception_handler(ApiProblem)
    async def _handle_api_problem(_req: Request, exc: ApiProblem) -> JSONResponse:
        return _problem_response(exc.status, exc.title, exc.detail, exc.type, exc.extra)

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exc(_req: Request, exc: StarletteHTTPException) -> JSONResponse:
        # HTTPException.detail を title として扱う（文字列前提）。
        title = exc.detail if isinstance(exc.detail, str) else "エラーが発生しました"
        return _problem_response(exc.status_code, title)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_req: Request, exc: RequestValidationError) -> JSONResponse:
        # 検証エラー詳細の input/ctx に非有限 float（Infinity/NaN 入力等）が含まれると
        # starlette の JSON 直列化（allow_nan=False）が 500 に化けるため JSON 安全化する。
        return _problem_response(
            422,
            "入力値が不正です",
            detail="リクエストの検証に失敗しました。",
            type_="about:blank",
            extra={"errors": _json_safe(exc.errors())},
        )


class IdempotencyStore:
    """Idempotency-Key による重複実行防止（プロセス内メモリ・TTL 付き）。

    同一 (tenant_id, key) の再送に対しては、最初に確定した結果を返し、副作用を再実行しない。
    MVP は単一プロセス前提。将来は DB / Redis に差し替える（設計 §5 の冪等キー）。
    """

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._ttl = ttl_seconds
        self._data: dict[tuple[str, str], tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, tenant_id: str, key: str) -> Optional[Any]:
        now = time.time()
        with self._lock:
            item = self._data.get((tenant_id, key))
            if item is None:
                return None
            ts, value = item
            if now - ts > self._ttl:
                del self._data[(tenant_id, key)]
                return None
            return value

    def put(self, tenant_id: str, key: str, value: Any) -> None:
        with self._lock:
            self._data[(tenant_id, key)] = (time.time(), value)
