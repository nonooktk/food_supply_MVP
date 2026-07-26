"""policy.py — 認証ポリシー（許可アカウント allowlist・本番でのモック認証禁止）。

セキュリティ監査 2026-07-26（担当: バリヤード）の指摘 F-2 / F-3 / F-16 への対応。

【なぜ独立モジュールにするか】
allowlist の照合は **2 経路**（ログイン `POST /api/auth/google` と、データ API の Bearer 検証）で
必ず効く必要がある。片方だけに書くと素通りする経路が残るため、判定をここ 1 箇所に集約し、
両経路から同じ関数を呼ぶ構造にしている。

【MVP のスコープ】
users テーブル（DB）はまだ持たない。「誰が入れるか」は設定（環境変数 ``ALLOWED_EMAILS``）で
持つ。役割別ユーザー管理は後続タスク。
"""

from __future__ import annotations

from app.auth.google import GoogleIdentity
from app.config import get_settings
from app.errors import ApiProblem


def normalize_email(email: str | None) -> str:
    """email を照合用の正規形（トリム＋小文字）にする。未指定は空文字。"""
    return (email or "").strip().lower()


def is_email_allowed(email: str | None) -> bool:
    """email が allowlist に載っているか。

    allowlist が空の場合は **全拒否**（fail-closed）。設定漏れが「全開放」ではなく
    「誰も入れない」に倒れるようにする。
    """
    normalized = normalize_email(email)
    if not normalized:
        return False
    return normalized in get_settings().allowed_emails


def authorize_google_identity(identity: GoogleIdentity) -> str:
    """検証済み Google アカウントを「利用してよいか」判定し、正規化済み email を返す。

    ここに来る時点で ID トークンの署名・aud・exp は検証済み（app/auth/google.py）。
    本関数は **その先の認可**（そのアカウントに本アプリを使う資格があるか）を担う。

    - email 未取得 / ``email_verified`` が True でない … 403（F-16。email を身元として
      使う以上、Google 側で確認済みでない email は信用しない）
    - allowlist 未登録 … 403（F-2）

    401 ではなく 403 を返すのは「トークンは正しいが、このアカウントには権限がない」ため。
    フロントは 403 で再ログインを促さず、管理者への連絡を案内する。
    """
    email = normalize_email(identity.email)
    if not email or identity.email_verified is not True:
        raise ApiProblem(
            403,
            "このアカウントでは利用できません",
            detail="確認済みのメールアドレスを持つ Google アカウントでログインしてください。",
        )
    if not is_email_allowed(email):
        raise ApiProblem(
            403,
            "このアカウントでは利用できません",
            detail="利用を許可されたアカウントではありません。管理者にお問い合わせください。",
        )
    return email


def ensure_mock_auth_allowed() -> None:
    """モック認証（ヘッダー方式・モックログイン）が使える環境かを実行時に検査する。

    F-3 の起動時ガード（``Settings`` の model_validator）と二重化する実行時ガード。
    起動後に設定オブジェクトが差し替えられた場合（テスト・動的再設定）でも、
    本番でモック認証が開かないようにする。
    """
    settings = get_settings()
    if settings.is_production and settings.normalized_auth_mode == "mock":
        raise ApiProblem(
            403,
            "この環境ではモック認証を利用できません",
            detail="本番環境では AUTH_MODE=google（Google ログイン）のみ利用できます。",
        )
