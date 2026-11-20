"""Settings loaded from environment variables / backend/.env."""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import secrets

PLACEHOLDER = "CHANGE_ME"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CATDASH_", extra="ignore")

    litterrobot_username: str | None = None
    litterrobot_password: SecretStr | None = None

    petlibro_email: str | None = None
    petlibro_password: SecretStr | None = None
    petlibro_region: str = "US"

    timezone: str = "America/Chicago"
    petlibro_poll_seconds: int = 60
    litterrobot_history_poll_seconds: int = 900

    data_dir: Path = Path("data")
    host: str = "127.0.0.1"
    port: int = 8000

    @field_validator(
        "litterrobot_username",
        "litterrobot_password",
        "petlibro_email",
        "petlibro_password",
        mode="before",
    )
    @classmethod
    def _blank_placeholders(cls, value: object) -> object:
        """Treat empty strings and the .env.example placeholder as unset."""
        if isinstance(value, str) and value.strip() in ("", PLACEHOLDER):
            return None
        return value

    # Passwords: an env var / .env value wins if set; otherwise the macOS Keychain
    # (store one with `uv run cat-dash-secrets set <integration>`).
    def litterrobot_password_value(self) -> str | None:
        if self.litterrobot_password:
            return self.litterrobot_password.get_secret_value()
        return secrets.get_password("litterrobot", self.litterrobot_username)

    def petlibro_password_value(self) -> str | None:
        if self.petlibro_password:
            return self.petlibro_password.get_secret_value()
        return secrets.get_password("petlibro", self.petlibro_email)

    @property
    def litterrobot_configured(self) -> bool:
        return bool(self.litterrobot_username and self.litterrobot_password_value())

    @property
    def petlibro_configured(self) -> bool:
        return bool(self.petlibro_email and self.petlibro_password_value())

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cat_dash.sqlite3"

    @property
    def litterrobot_token_path(self) -> Path:
        return self.data_dir / "litterrobot_tokens.json"

    @property
    def petlibro_token_path(self) -> Path:
        return self.data_dir / "petlibro_token.txt"
