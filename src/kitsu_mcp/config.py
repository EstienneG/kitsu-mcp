"""Server settings, read from environment variables or a `.env` in the working directory."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KITSU_", env_file=".env", extra="ignore")

    host: str
    """Zou API URL, e.g. https://example.cg-wire.com/api."""
    user: str
    password: SecretStr
    allow_write: bool = False
    """Register tools that modify Kitsu (comments, status changes, assignments, ...)."""
    cache_ttl: float = 300
    """Seconds to keep reference data (task types, statuses, people, ...) before refetching."""
    timeout: float = 30
    """Per-request timeout in seconds."""
    max_retries: int = 3
    """Attempts for idempotent requests that fail with a server or network error."""


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except Exception as error:
        missing = [
            f"KITSU_{e['loc'][0]}".upper()
            for e in getattr(error, "errors", lambda: [])()
            if e.get("type") == "missing"
        ]
        if missing:
            raise RuntimeError(f"Missing configuration: {', '.join(missing)}") from error
        raise
