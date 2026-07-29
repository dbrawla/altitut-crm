"""
Environment-level configuration — the equivalent of the Go app's config.toml.

Only bootstrap-level values live here (DB connection, listen address, first-run
admin credentials). Everything else (SMTP, privacy, uploads, appearance, …) is
runtime-editable and lives in the `settings` DB table, exactly like the
original listmonk.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Env(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # HTTP listener
    app_address: str = Field(default="0.0.0.0:9000")

    # Database (LISTMONK_db__* equivalents)
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "listmonk"
    db_password: str = "listmonk"
    db_name: str = "listmonk"
    db_ssl_mode: str = "disable"
    db_max_open_conns: int = 25
    db_conn_max_lifetime: int = 300  # seconds

    # First-run super admin (used only when installing into an empty DB).
    admin_username: str = "listmonk"
    admin_password: str = "listmonk"

    # Session cookie
    session_cookie_name: str = "listmonk_session"
    session_max_age: int = 86400 * 7  # seconds


env = Env()
