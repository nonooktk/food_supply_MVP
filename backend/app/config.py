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
            return (
                f"mysql+pymysql://{self.db_user}:{self.db_password}"
                f"@{self.db_host}:{self.db_port}/{self.db_name}"
            )
        if self.db_backend is DbBackend.POSTGRESQL:
            # postgresql は sslmode をクエリで渡せる（psycopg ドライバ・要 requirements 追加）。
            return (
                f"postgresql+psycopg://{self.pg_user}:{self.pg_password}"
                f"@{self.pg_host}:{self.pg_port}/{self.pg_name}?sslmode={self.pg_sslmode}"
            )
        # Enum で縛っているため通常到達しないが、保険として明示的に失敗させる。
        raise ValueError(f"未対応の DB_BACKEND です: {self.db_backend!r}")

    def database_connect_args(self) -> dict:
        """SQLAlchemy の create_engine に渡す connect_args を DB 種別ごとに返す。

        MySQL（Azure）は TLS 必須のため、SSL を無効化しない限り ssl 設定を付与する。
        DB エンジンの生成自体は app/db 側（ロトム／後続タスク）で行う。
        """
        if self.db_backend is DbBackend.MYSQL and not self.db_ssl_disabled:
            ssl: dict = {}
            if self.db_ssl_ca:
                ssl["ca"] = self.db_ssl_ca
            # ca 未指定でも ssl を有効化する（空 dict で TLS を要求）。
            return {"ssl": ssl}
        return {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """設定を 1 回だけロードしてキャッシュする。"""
    return Settings()


# 便利のため、モジュールレベルでも参照可能にする。
settings = get_settings()
