"""Tool groups: what is listed at first, load_tools, and that listing never gates calls."""

import json

import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError

from kitsu_mcp.server import groups, mcp
from tests.http_server import basic

CORE = {
    "whoami",
    "search",
    "list_projects",
    "project_overview",
    "search_tasks",
    "get_task",
    "get_person_tasks",
    "get_asset",
    "get_shot",
    "kitsu_get",
    "refresh_cache",
    "load_tools",
}


async def listed(client: Client) -> set[str]:
    return {t.name for t in await client.list_tools()}


async def test_only_core_tools_are_listed_at_first(fake):
    async with Client(mcp) as client:
        assert await listed(client) == CORE  # write is a default group, but writes are off


async def test_every_tool_is_in_exactly_one_group(all_groups):
    for t in await mcp.list_tools():
        tagged = {g for g in (*groups.GROUPS, groups.CORE) if g in t.tags}
        assert len(tagged) == 1, (t.name, tagged)


async def test_load_tools_lists_a_group_and_notifies(fake):
    notices = []

    async def handler(message):
        notices.append(type(message).__name__)

    async with Client(mcp, message_handler=handler) as client:
        result = (await client.call_tool("load_tools", {"groups": ["planning"]})).data
        assert "workload" in result and "timesheet" in result
        assert await listed(client) == CORE | {"workload", "timesheet", "quotas", "production_schedule", "budget"}
        assert "ToolListChangedNotification" in notices
        notices.clear()
        again = (await client.call_tool("load_tools", {"groups": ["planning"]})).data
        assert again.startswith("Already loaded") and notices == []


async def test_load_all_and_unknown_groups(fake):
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="Unknown groups"):
            await client.call_tool("load_tools", {"groups": ["budget"]})
        await client.call_tool("load_tools", {"groups": ["all"]})
        assert {"list_assets", "my_notifications", "review_video"} <= await listed(client)


async def test_calls_work_whether_or_not_the_group_is_listed(fake):
    """A client that ignores list_changed (or an agent that knows the name) can still call the tool."""
    async with Client(mcp) as client:
        assert "workload" not in await listed(client)
        rows = (await client.call_tool("workload", {"project": "p-1"})).structured_content
        assert rows and rows["result"]


async def test_load_tools_never_enables_write_tools(fake):
    async with Client(mcp) as client:
        result = (await client.call_tool("load_tools", {"groups": ["write"]})).data
        assert "KITSU_ALLOW_WRITE" in result
        assert not {"add_comment", "set_task_status"} & await listed(client)
        with pytest.raises(ToolError, match="Unknown tool"):
            await client.call_tool("add_comment", {"task_id": "t-hero-mod", "text": "hi"})


async def test_write_group_listed_by_default_when_writes_are_allowed(fake):
    mcp.enable(tags={"write"})
    try:
        async with Client(mcp) as client:
            assert {"add_comment", "set_task_status"} <= await listed(client)
        groups.set_default_groups("planning")
        async with Client(mcp) as client:
            names = await listed(client)
            assert "workload" in names and "add_comment" not in names
    finally:
        mcp.disable(tags={"write"})


def test_parse_groups():
    assert groups.parse_groups("") == set()
    assert groups.parse_groups(" Planning, review ,core") == {"planning", "review"}
    assert groups.parse_groups("all") == set(groups.GROUPS)
    with pytest.raises(RuntimeError, match="KITSU_TOOL_GROUPS"):
        groups.parse_groups("planing")


async def test_loaded_groups_are_per_http_caller(server):
    """Without MCP sessions (protocol 2026-07-28) a caller is their Kitsu login: Bob does not see what Alice
    loaded."""
    alice, bob = basic("alice@example.com", "right"), basic("bob@example.com", "right")
    async with Client(StreamableHttpTransport(server, headers=alice)) as client:
        await client.call_tool("load_tools", {"groups": ["activity"]})
        assert "project_activity" in await listed(client)
    async with Client(StreamableHttpTransport(server, headers=alice)) as client:
        assert "project_activity" in await listed(client)
    async with Client(StreamableHttpTransport(server, headers=bob)) as client:
        assert "project_activity" not in await listed(client)


def test_http_callers_are_keyed_by_session_then_full_login(monkeypatch):
    """A session ID wins; without one, the email *and* password, so knowing an email is not enough."""
    from types import SimpleNamespace

    from starlette.datastructures import Headers

    def request(headers):
        monkeypatch.setattr(groups, "get_http_request", lambda: SimpleNamespace(headers=Headers(headers)))
        return groups._client_key()

    auth = basic("alice@example.com", "right")
    assert request({"mcp-session-id": "s-1", **auth}) == "session:s-1"
    alice = request(auth)
    assert alice.startswith("user:")
    assert request(basic("alice@example.com", "guess")) != alice
    assert request({}) is None


# The core list is what every conversation pays for before any call. Raise this deliberately, with the
# README's "Context cost" paragraph, when a tool earns a place in core rather than in a group.
CORE_BUDGET_CHARS = 11_000  # 10.2k as of 12 core tools
SEP = (",", ":")


async def test_core_list_stays_within_its_context_budget(fake):
    async with Client(mcp) as client:
        tools = await client.list_tools()
    size = sum(
        len(
            json.dumps(
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}, separators=(",", ":")
            )
        )
        for t in tools
    )
    assert size <= CORE_BUDGET_CHARS, f"core tool list is {size} characters, over the {CORE_BUDGET_CHARS} budget"
