from typing import Any

from kitsu_mcp.app import READ_ONLY, mcp
from kitsu_mcp.client import get_client
from kitsu_mcp.lookups import get_lookups
from kitsu_mcp.models import User


@mcp.tool(annotations=READ_ONLY, tags={"meta"})
def whoami() -> User:
    """Return the Kitsu user the server is logged in as."""
    user = get_client().get("auth/authenticated")["user"]
    return User(id=user["id"], full_name=user.get("full_name"), email=user.get("email"), role=user.get("role"))


@mcp.tool(annotations=READ_ONLY, tags={"meta"})
def kitsu_get(path: str, params: dict | None = None) -> Any:
    """Run a raw read-only GET on the Zou API, e.g. path="data/projects/open".

    See https://api-docs.kitsu.cloud/ for routes. Use for anything the other tools don't cover.
    """
    return get_client().get(path.lstrip("/").removeprefix("api/"), params)


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True}, tags={"meta"})
def refresh_cache() -> str:
    """Drop cached reference data (projects, task types, statuses, people) so the next call refetches it."""
    get_lookups().clear()
    return "Cache cleared."
