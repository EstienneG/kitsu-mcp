import json

import pytest
from fastmcp import Client

from kitsu_mcp import client as client_module
from kitsu_mcp import lookups as lookups_module
from kitsu_mcp.lookups import Lookups
from kitsu_mcp.server import mcp
from tests.fakes import FakeClient


@pytest.fixture
def fake() -> FakeClient:
    fake = FakeClient()
    client_module.set_client(fake)  # type: ignore[arg-type]
    lookups_module.set_lookups(Lookups(fake, ttl=300))  # type: ignore[arg-type]
    yield fake
    client_module.set_client(None)
    lookups_module.set_lookups(None)


@pytest.fixture
async def call(fake):
    """Call a tool through the MCP protocol and return its JSON result (or raise on tool error)."""
    async with Client(mcp) as mcp_client:

        async def _call(name: str, /, **args):
            result = await mcp_client.call_tool(name, args)
            if result.structured_content is not None:
                content = result.structured_content
                return content["result"] if set(content) == {"result"} else content
            text = result.content[0].text
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text

        yield _call


@pytest.fixture(autouse=True)
def pinned_today(monkeypatch):
    """Tests see 2026-10-15 as today: t-hero-mod (due 10-01, wfa) and t-sh010-comp (due 10-10) are overdue."""
    from datetime import date

    from kitsu_mcp import production

    monkeypatch.setattr(production, "today", lambda: date(2026, 10, 15))


@pytest.fixture(autouse=True)
def readable_ids(monkeypatch):
    """The fake data uses readable IDs (t-hero-mod) instead of UUIDs; let object_id accept them."""
    import re

    from kitsu_mcp import validation

    monkeypatch.setattr(validation, "id_pattern", re.compile(f"{validation.UUID.pattern}|[a-z0-9]+(?:-[a-z0-9]+)*"))


@pytest.fixture(autouse=True)
def fresh_groups():
    """Each test starts with the default tool groups and nothing loaded."""
    from kitsu_mcp import groups

    groups.reset()
    groups.set_default_groups("write")
    yield
    groups.reset()
    groups.set_default_groups("write")


@pytest.fixture
def all_groups():
    """List every tool, as KITSU_TOOL_GROUPS=all does (for tests about the whole registry)."""
    from kitsu_mcp import groups

    groups.set_default_groups("all")
