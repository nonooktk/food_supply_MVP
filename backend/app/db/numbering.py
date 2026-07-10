"""numbering.py — 案件番号の採番サービス（調整シーム #3・設計 v3 §2.7）。

`case_no` の採番規則は発注者確認待ち（[確認3]）。暫定設計として「テナント内連番＋接頭辞、
アプリ登録は No.500001〜、再交渉の枝番は -a/-b をアプリ層で付与」を実装する。
確認後は `NumberingService` プロトコルの実装を DI で差し替えるだけで移行できる。

【Repository 経由化の例外】[レビュー許容済み]:
本サービスは案件番号の最大値を走査する採番専用の内部ユーティリティであり、
``TenantScopedRepository`` の外に置く。ただし tenant_id を必須引数に取り、全クエリを
``NegotiationCase.tenant_id == tenant_id`` で明示的に絞り込むことでテナント境界を保つ
（§2.8 ルール1「素のセッションを画面/サービス層へ露出しない」に対する、採番用途に限った例外）。
呼び出しは書き込み系（cases.create）からのみ行い、画面/読み取り層には露出しない。
"""

from __future__ import annotations

import re
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import NegotiationCase

# アプリ登録案件の採番開始番号（初期データ No.1234xx と衝突しない領域）。
APP_CASE_START = 500001

# "No.500001-a" / "No.123456" 等から数値部を取り出す正規表現。
_CASE_NO_RE = re.compile(r"No\.(\d+)")


class NumberingService(Protocol):
    """案件番号採番のインターフェース（差し替え可能な調整シーム）。"""

    def next_case_no(self, session: Session, tenant_id: str) -> str:
        """新規案件番号（枝番 -a 付き）を採番して返す。"""
        ...

    def next_branch(self, session: Session, tenant_id: str, base_case_no: str) -> str:
        """再交渉時の枝番付き案件番号（-b, -c ...）を返す。"""
        ...


class SequentialNumberingService:
    """テナント内連番＋接頭辞の暫定実装（No.500001〜・枝番 -a〜）。"""

    def __init__(self, start: int = APP_CASE_START) -> None:
        self._start = start

    @staticmethod
    def _numeric_part(case_no: str) -> int | None:
        m = _CASE_NO_RE.search(case_no or "")
        return int(m.group(1)) if m else None

    def next_case_no(self, session: Session, tenant_id: str) -> str:
        """当該テナントで使用済みの最大番号（No.500001 以上）の次を採番する。"""
        rows = session.execute(
            select(NegotiationCase.case_no).where(NegotiationCase.tenant_id == tenant_id)
        ).scalars().all()

        max_num = self._start - 1
        for case_no in rows:
            n = self._numeric_part(case_no)
            # アプリ採番領域（>= start）のみを連番の対象にする。
            if n is not None and n >= self._start:
                max_num = max(max_num, n)

        next_num = max_num + 1
        prefix = self._tenant_prefix(session, tenant_id)
        return f"{prefix}No.{next_num}-a"

    def next_branch(self, session: Session, tenant_id: str, base_case_no: str) -> str:
        """同一基底番号の既存枝番を調べ、次のアルファベット枝番を返す。"""
        base_num = self._numeric_part(base_case_no)
        if base_num is None:
            raise ValueError(f"案件番号の形式が不正です: {base_case_no!r}")

        rows = session.execute(
            select(NegotiationCase.case_no).where(NegotiationCase.tenant_id == tenant_id)
        ).scalars().all()

        used_suffixes = []
        for case_no in rows:
            if self._numeric_part(case_no) == base_num:
                m = re.search(r"-([a-z])$", case_no)
                if m:
                    used_suffixes.append(m.group(1))

        next_suffix = "a"
        if used_suffixes:
            last = max(used_suffixes)
            next_suffix = chr(ord(last) + 1)
        prefix = self._tenant_prefix(session, tenant_id)
        return f"{prefix}No.{base_num}-{next_suffix}"

    @staticmethod
    def _tenant_prefix(session: Session, tenant_id: str) -> str:
        """tenants.case_no_prefix があれば接頭辞として付与する（無ければ空）。"""
        from app.db.models import Tenant

        prefix = session.execute(
            select(Tenant.case_no_prefix).where(Tenant.tenant_id == tenant_id)
        ).scalar_one_or_none()
        return prefix or ""
