"""Tool groups: a small core list, and the rest loaded when a conversation needs it.

Every tool name and schema costs context before the first call, and long lists make agents pick worse. So
`tools/list` shows the core tools, the groups in KITSU_TOOL_GROUPS and the groups a client loaded with
`load_tools`; the server then tells the client its list changed. Only the listing is filtered: a call to a
registered tool works whether or not its group is loaded, so a client that ignores the notification can
still call a tool the agent heard of (and write tools stay governed by KITSU_ALLOW_WRITE alone).

Loaded groups are kept per client: the process over stdio (one client), the MCP session over HTTP, or the
caller's Kitsu login when the protocol has no sessions (MCP 2026-07-28), so one person's conversations then
share what they loaded. That only lists more tools; it never grants anything.
"""

import threading
from typing import Annotated

from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware import Middleware
from mcp_types import ToolListChangedNotification
from pydantic import Field

from kitsu_mcp.kitsu.auth import TTLCache, parse_authorization
from kitsu_mcp.server.app import GROUPS as GROUP_DESCRIPTIONS
from kitsu_mcp.server.app import mcp, tool
from kitsu_mcp.server.http import LOCAL_TAG, over_http

CORE = "core"

GROUPS = tuple(GROUP_DESCRIPTIONS)
"""Groups `load_tools` adds (described in kitsu_mcp.server.app.GROUPS). A tool's group is its tag."""

_loaded: TTLCache[frozenset[str]] = TTLCache(ttl=24 * 3600, max_size=4096)
_lock = threading.Lock()


def group_of(tags: set[str]) -> str | None:
    """The group a tool belongs to (core, or one of GROUPS); None for tools outside any group."""
    if CORE in tags:
        return CORE
    return next((g for g in GROUPS if g in tags), None)


def parse_groups(value: str) -> set[str]:
    """KITSU_TOOL_GROUPS: comma-separated group names, or "all"."""
    names = {n.strip().lower() for n in value.split(",") if n.strip()}
    if "all" in names:
        return set(GROUPS)
    unknown = names - set(GROUPS) - {CORE}
    if unknown:
        raise RuntimeError(f"KITSU_TOOL_GROUPS: unknown groups {sorted(unknown)}; use some of {', '.join(GROUPS)}")
    return names - {CORE}


_defaults: set[str] = {"write"}


def set_default_groups(value: str) -> None:
    """Groups listed from the start (KITSU_TOOL_GROUPS; `main()` sets it, the default lists write tools)."""
    _defaults.clear()
    _defaults.update(parse_groups(value))


def default_groups() -> set[str]:
    return set(_defaults)


def _client_key() -> str | None:
    """Who loaded the groups: the MCP session, else the HTTP caller's login, else this process (stdio).
    None for an HTTP request without either: nothing to remember it by."""
    try:
        request = get_http_request()
    except RuntimeError:
        return "stdio"
    session = request.headers.get("mcp-session-id")
    if session:
        return f"session:{session}"
    credentials = parse_authorization(request.headers.get("authorization", ""))
    # The full login (email and password): someone who only knows an email cannot change that user's list.
    return f"user:{credentials.key}" if credentials else None


def loaded_groups() -> set[str]:
    key = _client_key()
    return default_groups() | set((_loaded.get(key) if key else None) or ())


def reset() -> None:
    """Forget every client's loaded groups (tests)."""
    _loaded.clear()


class GroupFilter(Middleware):
    """Lists the core tools and the loaded groups; tools outside every group are always listed."""

    async def on_list_tools(self, context, call_next):
        tools = await call_next(context)
        shown = loaded_groups() | {CORE}
        return [t for t in tools if (group := group_of(t.tags)) is None or group in shown]


mcp.add_middleware(GroupFilter())


_LOAD_TOOLS = (
    "Add tool groups to this conversation. At first only the core tools are listed (search, projects, task "
    "search and details, people's tasks, assets, shots); load a group before you need its tools.\n\n"
    + "\n".join(f"{name}: {holds}." for name, holds in GROUP_DESCRIPTIONS.items())
)


@tool(
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
    tags={CORE},
    description=_LOAD_TOOLS,
)
async def load_tools(
    groups: Annotated[list[str], Field(description=f"Some of: {', '.join(GROUPS)}; or all")],
    ctx: Context,
) -> str:
    """Add groups to what this client lists (description: _LOAD_TOOLS, built from the group map)."""
    wanted = {g.strip().lower() for g in groups}
    if "all" in wanted:
        wanted = set(GROUPS)
    unknown = wanted - set(GROUPS)
    if unknown:
        raise ToolError(f"Unknown groups {sorted(unknown)}; use some of {', '.join(GROUPS)}, or all")
    key = _client_key()
    with _lock:
        before = loaded_groups()
        if key:
            _loaded.put(key, frozenset(set(_loaded.get(key) or ()) | wanted))
    added = sorted(wanted - before)
    if added:
        await ctx.send_notification(ToolListChangedNotification())
    hidden = LOCAL_TAG if over_http() else None
    names = sorted(
        t.name
        for t in await mcp.list_tools(run_middleware=False)
        if group_of(t.tags) in wanted and hidden not in t.tags
    )
    if not names:
        return f"No tools available in {', '.join(sorted(wanted))} on this server (write tools need KITSU_ALLOW_WRITE)."
    state = f"Loaded {', '.join(added)}" if added else "Already loaded"
    return f"{state}. Tools: {', '.join(names)}. If your tool list did not refresh, call them by name anyway."
