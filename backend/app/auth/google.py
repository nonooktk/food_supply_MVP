"""google.py — Google Identity Services（GIS）の ID トークン検証（認証シーム: google モード）。

りなれす（`rinaresu/backend/app/services/google_auth.py`）で実績のある方式を踏襲する。
フロントの GIS ボタンが返す credential（ID トークン=JWT）を google-auth で検証し、
検証済みの sub / email / name を取り出す。検証は aud（GOOGLE_CLIENT_ID）・署名・有効期限を
Google 側で行う。

認証シーム（設計）:
- 本モジュールは「ログイン方式=google」の検証実装。モックヘッダー／フォーム認証（mock モード）とは
  ``AUTH_MODE`` で共存する（app/api/auth.py がモードで振り分ける）。
- 将来 Entra へ移行する場合は、本モジュールと同じ粒度で ``app/auth/entra.py`` を追加し、
  auth.py のモード分岐に一手足すだけでよい（本体の認可＝テナント解決の仕組みは不変）。
"""

from __future__ import annotations

from app.config import get_settings


class GoogleAuthError(ValueError):
    """Google ID トークン検証に失敗したことを表す（呼び出し側で 401 に変換する）。"""


class GoogleIdentity:
    """検証済みの Google アカウント情報。"""

    def __init__(self, sub: str, email: str | None, name: str | None) -> None:
        self.sub = sub
        self.email = email
        self.name = name


def verify_google_credential(credential: str) -> GoogleIdentity:
    """GIS の credential（ID トークン）を検証し、sub / email / name を返す。

    検証失敗（署名不正・aud 不一致・期限切れ・sub 欠落・クライアントID未設定など）は
    GoogleAuthError を送出する。
    """
    if not credential:
        raise GoogleAuthError("credential が空です。")

    client_id = get_settings().google_client_id
    if not client_id:
        # google モードなのに GOOGLE_CLIENT_ID 未設定 → 検証できない（設定不備）。
        raise GoogleAuthError("GOOGLE_CLIENT_ID が未設定です（検証できません）。")

    # google-auth は import に I/O を伴わないが、mock モードで未使用のため関数内 import にする。
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    try:
        # aud（クライアントID）・署名・有効期限を Google 側で検証する。
        # clock_skew_in_seconds: ローカル開発機の時計が数秒ズレていると
        # 「Token used too early」で失敗するため、許容ズレ10秒を与える（Google 推奨の標準対処）。
        info = id_token.verify_oauth2_token(
            credential, google_requests.Request(), client_id, clock_skew_in_seconds=10
        )
    except Exception as exc:  # noqa: BLE001 - ライブラリは多様な例外を投げるため一括で扱う
        import logging

        logging.getLogger("app.auth.google").warning(
            "Google ID トークン検証失敗: %r", exc
        )
        raise GoogleAuthError("Google ID トークンの検証に失敗しました。") from exc

    sub = info.get("sub")
    if not sub:
        raise GoogleAuthError("ID トークンに sub が含まれていません。")
    return GoogleIdentity(sub=sub, email=info.get("email"), name=info.get("name"))
