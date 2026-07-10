"""config.py — 環境変数の集中管理。

pydantic-settings で backend/.env または OS 環境変数から設定を読み込む。
DB 接続先は ``DB_BACKEND``（sqlite / mysql / postgresql）で切り替える「シーム」を持ち、
``resolve_database_url()`` が値に応じて SQLAlchemy 用の接続URLを解決する。

流用元: PoC_phase1/backend/config.py の思想（pydantic-settings + database_url プロパティ）。
差分: PoC の ``USE_MYSQL``（bool 2択）を ``DB_BACKEND``（3択の文字列シーム）へ拡張。
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/.env の絶対パス（CWD に依存させない）。
# このファイルは backend/app/config.py なので、2つ上が backend/。
_ENV_FILE = str(Path(__file__).resolve().parent.parent / ".env")


class DbBackend(str, Enum):
    """対応する DB バックエンド種別。"""

    SQLITE = "sqlite"
    MYSQL = "mysql"
    POSTGRESQL = "postgresql"


class Settings(BaseSettings):
    """アプリケーション設定。"""

    # ===== DB 切替シーム =====
    db_backend: DbBackend = Field(DbBackend.SQLITE, alias="DB_BACKEND")

    # ----- SQLite -----
    sqlite_path: str = Field("./freeradicals.db", alias="SQLITE_PATH")

    # ----- MySQL（Azure Database for MySQL） -----
    db_host: str = Field("localhost", alias="DB_HOST")
    db_user: str = Field("", alias="DB_USER")
    db_password: str = Field("", alias="DB_PASSWORD")
    db_name: str = Field("freeradicals", alias="DB_NAME")
    db_port: int = Field(3306, alias="DB_PORT")
    db_ssl_disabled: bool = Field(False, alias="DB_SSL_DISABLED")
    db_ssl_ca: str = Field("", alias="DB_SSL_CA")

    # ----- PostgreSQL（将来用） -----
    pg_host: str = Field("localhost", alias="PG_HOST")
    pg_user: str = Field("", alias="PG_USER")
    pg_password: str = Field("", alias="PG_PASSWORD")
    pg_name: str = Field("freeradicals", alias="PG_NAME")
    pg_port: int = Field(5432, alias="PG_PORT")
    pg_sslmode: str = Field("require", alias="PG_SSLMODE")

    # ===== Azure OpenAI =====
    azure_openai_endpoint: str = Field("", alias="AZURE_OPENAI_ENDPOINT")
    azure_openai_api_key: str = Field("", alias="AZURE_OPENAI_API_KEY")
    azure_openai_api_version: str = Field("2024-08-01-preview", alias="AZURE_OPENAI_API_VERSION")
    azure_openai_chat_deployment: str = Field("gpt-4o-mini", alias="AZURE_OPENAI_CHAT_DEPLOYMENT")
    azure_openai_embed_deployment: str = Field(
        "text-embedding-3-small", alias="AZURE_OPENAI_EMBED_DEPLOYMENT"
    )

    # ===== Azure AI Search =====
    azure_search_endpoint: str = Field("", alias="AZURE_SEARCH_ENDPOINT")
    azure_search_api_key: str = Field("", alias="AZURE_SEARCH_API_KEY")
    azure_search_index_name: str = Field("freeradicals-docs-v1", alias="AZURE_SEARCH_INDEX_NAME")

    # ===== KRE（関連知識検索エンジン） =====
    # true のときスタブ実装を DI で注入し、外部サービス未接続でも本体を起動できる。
    use_kre_stub: bool = Field(True, alias="USE_KRE_STUB")

    # ===== 認証シーム =====
    # ログイン方式の切替。mock=モックヘッダー/フォーム（開発・テスト） / google=Google Identity Services。
    # 将来 Entra へ移行する場合は "entra" を足し、対応する検証実装を auth 層に追加するだけでよい。
    auth_mode: str = Field("mock", alias="AUTH_MODE")
    # Google のクライアントID（aud 検証に使用。秘匿値ではない）。google モードでは必須。
    google_client_id: str = Field("", alias="GOOGLE_CLIENT_ID")

    # ===== CORS =====
    cors_origins_raw: str = Field("http://localhost:3000", alias="CORS_ORIGINS")

    # ===== 観測性・動作モード =====
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    trace_id_header: str = Field("x-trace-id", alias="TRACE_ID_HEADER")
    app_env: str = Field("development", alias="APP_ENV")

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origins(self) -> list[str]:
        """CORS_ORIGINS をカンマ区切りで分解したリストを返す。"""
        return [o.strip().rstrip("/") for o in self.cors_origins_raw.split(",") if o.strip()]

    def resolve_database_url(self) -> str:
        """DB_BACKEND シームに応じて SQLAlchemy 用の接続URLを解決する。

        - sqlite     : sqlite:///<SQLITE_PATH>
        - mysql      : mysql+pymysql://<user>:<pass>@<host>:<port>/<db>
        - postgresql : postgresql+psycopg://<user>:<pass>@<host>:<port>/<db>?sslmode=...

        SSL 等の細かな接続オプションは connect_args（下記 database_connect_args）で
        別途エンジンに渡す方針とし、URL 自体は素直に組み立てる。
        """
        if self.db_backend is DbBackend.SQLITE:
            return f"sqlite:///{self.sqlite_path}"
        if self.db_backend is DbBackend.MYSQL:
            # user / password は記号（@ : / 等）を含みうるため URL エンコードする。
            user = quote_plus(self.db_user)
            password = quote_plus(self.db_password)
            return (
                f"mysql+pymysql://{user}:{password}"
                f"@{self.db_host}:{self.db_port}/{self.db_name}"
            )
        if self.db_backend is DbBackend.POSTGRESQL:
            # postgresql は sslmode をクエリで渡せる（psycopg ドライバ・要 requirements 追加）。
            user = quote_plus(self.pg_user)
            password = quote_plus(self.pg_password)
            return (
                f"postgresql+psycopg://{user}:{password}"
                f"@{self.pg_host}:{self.pg_port}/{self.pg_name}?sslmode={self.pg_sslmode}"
            )
        # Enum で縛っているため通常到達しないが、保険として明示的に失敗させる。
        raise ValueError(f"未対応の DB_BACKEND です: {self.db_backend!r}")

    def database_connect_args(self) -> dict:
        """SQLAlchemy の create_engine に渡す connect_args を DB 種別ごとに返す。

        MySQL（Azure）は ``require_secure_transport=ON`` のため TLS が必須。SSL を無効化
        しない限り SSLContext を付与して暗号化接続を強制する（空 dict は PyMySQL では
        falsy 扱いとなり TLS が無効化される点に注意）。DB_SSL_CA 指定時はその CA で
        サーバ証明書を検証し、未指定時は暗号化のみ要求する（疎通用途。運用では CA 設定を推奨）。
        """
        if self.db_backend is DbBackend.MYSQL and not self.db_ssl_disabled:
            import ssl as _ssl

            ctx = _ssl.create_default_context(cafile=self.db_ssl_ca or None)
            if not self.db_ssl_ca:
                # CA 未指定時は証明書検証を行わず、暗号化のみ要求する。
                ctx.check_hostname = False
                ctx.verify_mode = _ssl.CERT_NONE
            return {"ssl": ctx}
        return {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """設定を 1 回だけロードしてキャッシュする。"""
    return Settings()


# 便利のため、モジュールレベルでも参照可能にする。
settings = get_settings()
