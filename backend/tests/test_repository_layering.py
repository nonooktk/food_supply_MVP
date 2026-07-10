"""test_repository_layering.py — 読み取り系が Repository 経由であることの機械検査。

設計 v3 §2.8 ルール1「素の SQLAlchemy セッションを画面／サービス層に露出しない」を担保する。
業務エンドポイント（cases/rates/plans/lines/search）とサービス層（pricing/case_view）に
生セッション（Depends(get_session) / 直接 session.execute / session.query）が残っていないことを
ソース走査で検査する。

例外（許容）:
- auth.py … ログインはテナント解決の前段（認証境界）であり、テナントスコープの外で tenants を引く。
- db/numbering.py … 採番専用の内部ユーティリティ（tenant 必須・Repository 外。モジュール docstring 参照）。
- repo.session … Repository 自身のセッション（書き込み時の flush/commit）は許容。
"""

from __future__ import annotations

from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]

# 生セッションが残っていてはならないモジュール（読み取り/サービス層）。
_GUARDED_FILES = [
    "app/api/cases.py",
    "app/api/rates.py",
    "app/api/plans.py",
    "app/api/lines.py",
    "app/api/search.py",
    "app/services/pricing.py",
    "app/services/case_view.py",
]

# 検出したら NG のパターン（repo.session は除外するため個別に判定）。
_FORBIDDEN = ["Depends(get_session)", "session.query(", ".execute("]


@pytest.mark.parametrize("relpath", _GUARDED_FILES)
def test_no_raw_session_in_read_layer(relpath: str) -> None:
    src = (_BACKEND / relpath).read_text(encoding="utf-8")
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("*"):
            continue  # コメント行は対象外
        for pat in _FORBIDDEN:
            if pat in line:
                # repo.session.exec(...) は Repository のセッション経由なので許容。
                if pat == ".execute(" and "repo.session" in line:
                    continue
                raise AssertionError(
                    f"{relpath} に生セッションの痕跡: {pat!r} → {stripped!r}"
                )


def test_services_do_not_import_session() -> None:
    """サービス層は sqlalchemy.orm.Session を import しない（Repository のみに依存）。"""
    for relpath in ("app/services/pricing.py", "app/services/case_view.py"):
        src = (_BACKEND / relpath).read_text(encoding="utf-8")
        assert "from sqlalchemy.orm import Session" not in src, relpath
        assert "import sqlalchemy" not in src, relpath
