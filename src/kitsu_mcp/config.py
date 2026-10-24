"""Server settings, read from environment variables or a `.env` in the working directory."""

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KITSU_", env_file=".env", extra="ignore")

    host: str
    """Zou API URL, e.g. https://example.cg-wire.com/api."""
    user: str | None = None
    """Kitsu login for stdio. Over HTTP each caller sends their own, and these are not used."""
    password: SecretStr | None = None
    allow_write: bool = False
    """Register tools that modify Kitsu (comments, status changes, assignments, ...)."""
    cache_ttl: float = Field(300, ge=0)
    """Seconds to keep reference data (task types, statuses, people, ...) before refetching."""
    timeout: float = Field(30, gt=0)
    """Per-request timeout in seconds."""
    max_retries: int = Field(3, ge=1)
    """Attempts for idempotent requests that fail with a server or network error."""
    video_cache_dir: Path | None = None
    """Where downloaded movies are cached (default: a kitsu-mcp-videos folder in the system temp dir)."""
    video_cache_mb: int = Field(1024, ge=0)
    """Size of the movie cache; the least recently used movies are deleted past it."""
    video_max_mb: int = Field(500, gt=0)
    """Largest movie the video tools will download."""
    # Status roles. Each is a comma-separated list of task status short names or names (case-insensitive).
    # A listed status takes that role; any other status gets its role from Kitsu's flags. Checked in this
    # order, so a status in two lists takes the first.
    omitted_statuses: str = "omit,na,n/a,omitted,cancelled,canceled"
    """Dropped, not finished: left out of progress and open work (Kitsu flags them done)."""
    done_statuses: str = ""
    """Finished, even if Kitsu flags them otherwise, e.g. "cbb" for a "could be better" status flagged retake."""
    on_hold_statuses: str = "stand by,standby,pause,paused,blocked,on hold"
    """Open but paused: never counted as overdue or in progress."""
    review_statuses: str = ""
    """Waiting for review/approval, in addition to statuses Kitsu flags as feedback requests."""
    retake_statuses: str = ""
    """Sent back for changes, in addition to statuses Kitsu flags as retakes."""
    dry_run_log: Path | None = None
    """JSONL file that every write-tool dry run (dry_run=True) is appended to."""


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except Exception as error:
        missing = [
            f"KITSU_{e['loc'][0]}".upper() for e in getattr(error, "errors", lambda: [])() if e.get("type") == "missing"
        ]
        if missing:
            raise RuntimeError(f"Missing configuration: {', '.join(missing)}") from error
        raise


def require_login(settings: Settings) -> None:
    """Over stdio the server logs in as KITSU_USER; fail at startup, not on the first tool call."""
    missing = [
        name for name, value in (("KITSU_USER", settings.user), ("KITSU_PASSWORD", settings.password)) if not value
    ]
    if missing:
        raise RuntimeError(f"Missing configuration: {', '.join(missing)}")


def without_userinfo(url: str) -> str:
    """A host URL without any user:password@ part (a proxy login must never reach callers)."""
    parts = urlsplit(url)
    if "@" not in parts.netloc:
        return url
    return urlunsplit(parts._replace(netloc=parts.netloc.rsplit("@", 1)[1]))
