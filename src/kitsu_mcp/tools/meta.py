from typing import Any

from fastmcp.exceptions import ToolError

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
    """Run a raw read-only GET on a Zou `data/` route, e.g. path="data/projects/open".

    See https://api-docs.kitsu.cloud/ for routes. Use for anything the other tools don't cover.
    """
    route = path.strip().lstrip("/").removeprefix("api/")
    segments = route.split("?")[0].split("/")
    # Only data/ routes are plain reads; some GETs elsewhere (auth/logout) or under build/ (playlist
    # renders) change server state.
    if segments[0] != "data" or ".." in segments or "build" in segments:
        raise ToolError("kitsu_get only allows read routes under data/ (no '..' or build/ segments)")
    return get_client().get(route, params)


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True}, tags={"meta"})
def refresh_cache() -> str:
    """Drop cached reference data (projects, task types, statuses, people) so the next call refetches it."""
    get_lookups().clear()
    return "Cache cleared."
