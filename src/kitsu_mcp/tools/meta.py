import json
import re
from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from pydantic import Field

from kitsu_mcp.app import READ_ONLY, mcp
from kitsu_mcp.client import get_client
from kitsu_mcp.lookups import get_lookups
from kitsu_mcp.models import User
from kitsu_mcp.validation import MAX_LIMIT


@mcp.tool(annotations=READ_ONLY, tags={"meta"})
def whoami() -> User:
    """Return the Kitsu user the server is logged in as."""
    user = get_client().get("auth/authenticated")["user"]
    return User(id=user["id"], full_name=user.get("full_name"), email=user.get("email"), role=user.get("role"))


_SAFE_ROUTE = re.compile(r"data(/[A-Za-z0-9_.-]+)*/?")


@mcp.tool(annotations=READ_ONLY, tags={"meta"})
def kitsu_get(path: str, params: dict | None = None, max_items: Annotated[int, Field(ge=1, le=MAX_LIMIT)] = 100) -> Any:
    """Run a raw read-only GET on a Zou `data/` route, e.g. path="data/projects/open".

    See https://api-docs.kitsu.cloud/ for routes. Use for anything the other tools don't cover.
    Raw answers can be huge (all of a project's tasks is ~2 MB), so a list answer keeps its first
    max_items items, and any answer over ~50 KB is cut: the result then says truncated, with the total.
    Prefer the typed tools, or narrow with `params` (e.g. {"project_id": ...}).
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
    return _bounded(get_client().get(route, params), max_items)


_MAX_CHARS = 50_000


def _bounded(answer: Any, max_items: int) -> Any:
    """Keep a raw answer small enough for a model's context: cap list length, then total size."""
    if isinstance(answer, list):
        items = answer[:max_items]
        while len(items) > 1 and len(json.dumps(items, default=str)) > _MAX_CHARS:
            items = items[: len(items) // 2]
        if len(items) < len(answer):
            return {
                "truncated": True,
                "total": len(answer),
                "returned": len(items),
                "items": items,
                "hint": "Narrow with params, page with the typed tools, or raise max_items for small items.",
            }
        return answer
    text = json.dumps(answer, default=str)
    if len(text) > _MAX_CHARS:
        return {
            "truncated": True,
            "chars": len(text),
            "preview": text[:_MAX_CHARS],
            "hint": "The answer is too large to return whole; use a typed tool or a narrower route.",
        }
    return answer


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True}, tags={"meta"})
def refresh_cache() -> str:
    """Drop cached reference data (projects, task types, statuses, people) so the next call refetches it."""
    get_lookups().clear()
    return "Cache cleared."
