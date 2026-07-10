"""logging.py — 構造化ログと監査ログ（trace_id 付き）。

PoC observability/logging.py の思想（trace_id 付き JSON ログ）を流用。案件の作成・修正・
状態変更・保存などの操作を追記型（append-only）で記録する（監査要件 N-02・設計 v3 §6.3）。
秘匿情報はログに出さない（セキュリティ規定）。
"""

from __future__ import annotations

import structlog

# 構造化ログの初期化（JSON 出力・タイムスタンプ付き）。
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.JSONRenderer(ensure_ascii=False),
    ],
)

_logger = structlog.get_logger("freeradicals.audit")


def emit_audit(
    action: str,
    *,
    tenant_id: str,
    user_id: str,
    trace_id: str = "",
    **fields: object,
) -> None:
    """監査イベントを1件記録する（append-only）。

    action 例: "case.create" / "case.status_change" / "plan.save" / "lines.save"。
    fields には案件番号など非秘匿の識別子のみを渡すこと（価格等の業務値は最小限）。
    """
    _logger.info(
        "audit",
        action=action,
        tenant_id=tenant_id,
        user_id=user_id,
        trace_id=trace_id,
        **fields,
    )
