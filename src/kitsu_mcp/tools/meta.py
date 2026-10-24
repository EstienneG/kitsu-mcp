import re
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


_SAFE_ROUTE = re.compile(r"data(/[A-Za-z0-9_.-]+)*/?")


@mcp.tool(annotations=READ_ONLY, tags={"meta"})
def kitsu_get(path: str, params: dict | None = None) -> Any:
    """Run a raw read-only GET on a Zou `data/` route, e.g. path="data/projects/open".

    See https://api-docs.kitsu.cloud/ for routes. Use for anything the other tools don't cover.
    """
    route = path.strip().lstrip("/").removeprefix("api/")
    # Only data/ routes are plain reads; some GETs elsewhere (auth/logout) or under build/ (playlist
    # renders) change server state. Allowlisting plain characters rules out encoded or escaped
    # tricks (%2e%2e, %62uild, backslashes) that would be decoded before reaching the server;
    # query parameters belong in `params`.
    if not _SAFE_ROUTE.fullmatch(route):
        raise ToolError(
            "kitsu_get only allows plain read routes under data/ (letters, digits, '-', '_', '.', '/'; "
            "no '..', build/, '%' escapes or query string; pass query parameters in `params`)"
        )
    segments = route.split("/")
    if ".." in segments or "." in segments or "build" in segments:
        raise ToolError("kitsu_get refuses '.', '..' and build/ segments")
    return get_client().get(route, params)


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True}, tags={"meta"})
def refresh_cache() -> str:
    """Drop cached reference data (projects, task types, statuses, people) so the next call refetches it."""
    get_lookups().clear()
    return "Cache cleared."
