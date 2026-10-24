import json
import re
from importlib import metadata
from typing import Annotated, Any
from urllib.parse import urlsplit, urlunsplit

from fastmcp.exceptions import ToolError
from pydantic import Field

from kitsu_mcp import video
from kitsu_mcp.app import READ_ONLY, tool
from kitsu_mcp.client import get_client
from kitsu_mcp.lookups import ROLE_SETTINGS, get_lookups, names_in
from kitsu_mcp.models import ServerInfo, User
from kitsu_mcp.validation import MAX_LIMIT


@tool(annotations=READ_ONLY, tags={"meta"})
def whoami() -> User:
    """The Kitsu user the server is logged in as, and how the server is set up (`server`): version,
    Kitsu host, whether write and video tools are available, page size limit and the status-role
    settings. A good first call."""
    client = get_client()
    user = client.get("auth/authenticated")["user"]
    return User(
        id=user["id"],
        full_name=user.get("full_name"),
        email=user.get("email"),
        role=user.get("role"),
        server=_server_info(client),
    )


def _server_info(client) -> ServerInfo:
    settings = client.settings
    lookups = get_lookups()
    return ServerInfo(
        version=_version(),
        kitsu_host=_without_userinfo(settings.host),
        write_tools=settings.allow_write,
        video_tools=video.available(),
        max_page_size=MAX_LIMIT,
        status_role_settings={
            f"KITSU_{name.upper()}": sorted(names_in(getattr(settings, name))) for name, _ in ROLE_SETTINGS
        },
        unmatched_status_settings=_unmatched(lookups),
        cache_ttl_seconds=settings.cache_ttl,
        video_max_mb=settings.video_max_mb,
    )


def _unmatched(lookups) -> dict[str, list[str]]:
    """Best effort: whoami is a connectivity check and must not fail on the status lookup."""
    try:
        return lookups.unmatched_role_names()
    except ToolError:
        return {}


def _without_userinfo(url: str) -> str:
    """A host URL without any user:password@ part."""
    parts = urlsplit(url)
    if "@" not in parts.netloc:
        return url
    return urlunsplit(parts._replace(netloc=parts.netloc.rsplit("@", 1)[1]))


def _version() -> str:
    try:
        return metadata.version("kitsu-mcp")
    except metadata.PackageNotFoundError:
        return "unknown"


_SAFE_ROUTE = re.compile(r"data(/[A-Za-z0-9_.-]+)*/?")


@tool(annotations=READ_ONLY, tags={"meta"})
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
    """Keep a raw answer small enough for a model's context and still valid data.

    Lists (top level, or the list values of a top-level dict such as {"data": [...]}) keep at most
    max_items items, fewer if they are still over the size cap. Anything else over the cap, or a single
    item that alone is over it, is replaced by a note with its size.
    """
    if isinstance(answer, list):
        return _bounded_list(answer, max_items)
    if isinstance(answer, dict) and any(isinstance(v, list) for v in answer.values()):
        bounded = {k: _bounded_list(v, max_items) if isinstance(v, list) else v for k, v in answer.items()}
        if _size(bounded) <= _MAX_CHARS:
            return bounded
        return _too_big(answer)
    return answer if _size(answer) <= _MAX_CHARS else _too_big(answer)


def _bounded_list(items: list, max_items: int) -> Any:
    kept = items[:max_items]
    while kept and _size(kept) > _MAX_CHARS:
        kept = kept[: len(kept) // 2]
    if len(kept) == len(items):
        return items
    return {
        "truncated": True,
        "total": len(items),
        "returned": len(kept),
        "items": kept,
        "hint": "Narrow with params, page with the typed tools, or raise max_items for small items."
        if kept
        else "Even one item is over the size limit; use a typed tool or a narrower route.",
    }


def _size(value: Any) -> int:
    return len(json.dumps(value, default=str))


def _too_big(answer: Any) -> dict:
    return {
        "truncated": True,
        "chars": _size(answer),
        "hint": "The answer is too large to return; use a typed tool, narrower params or a narrower route.",
    }


@tool(annotations={"readOnlyHint": True, "idempotentHint": True}, tags={"meta"})
def refresh_cache() -> str:
    """Drop cached reference data (projects, task types, statuses, people) so the next call refetches it."""
    get_lookups().clear()
    return "Cache cleared."
