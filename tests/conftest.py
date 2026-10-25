import json

import pytest
from fastmcp import Client

from kitsu_mcp.kitsu import client as client_module
from kitsu_mcp.kitsu import lookups as lookups_module
from kitsu_mcp.kitsu.lookups import Lookups
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

    from kitsu_mcp.kitsu import production

    monkeypatch.setattr(production, "today", lambda: date(2026, 10, 15))


@pytest.fixture(autouse=True)
def readable_ids(monkeypatch):
    """The fake data uses readable IDs (t-hero-mod) instead of UUIDs; let object_id accept them."""
    import re

    from kitsu_mcp.kitsu import validation

    monkeypatch.setattr(validation, "id_pattern", re.compile(f"{validation.UUID.pattern}|[a-z0-9]+(?:-[a-z0-9]+)*"))


@pytest.fixture(autouse=True)
def fresh_groups():
    """Each test starts with the default tool groups and nothing loaded."""
    from kitsu_mcp.server import groups

    groups.reset()
    groups.set_default_groups("write")
    yield
    groups.reset()
    groups.set_default_groups("write")


@pytest.fixture
def all_groups():
    """List every tool, as KITSU_TOOL_GROUPS=all does (for tests about the whole registry)."""
    from kitsu_mcp.server import groups

    groups.set_default_groups("all")


@pytest.fixture
async def server(monkeypatch):
    """The real server over HTTP, with the per-user Kitsu clients faked (see tests/http_server.py)."""
    from fastmcp.utilities.tests import run_server_async

    from kitsu_mcp import config
    from kitsu_mcp.kitsu import auth
    from tests.http_server import REQUESTS, PerUserFake

    monkeypatch.setenv("KITSU_HOST", "http://kitsu.test/api")
    for var in ("KITSU_USER", "KITSU_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir("/")  # no .env
    config.get_settings.cache_clear()
    monkeypatch.setattr(client_module, "KitsuClient", PerUserFake)
    client_module.set_client(None)
    lookups_module.set_lookups(None)
    client_module._user_clients.clear()
    lookups_module._user_lookups.clear()
    monkeypatch.setattr(client_module, "_server_client", None)
    monkeypatch.setattr(client_module, "_logins", auth.LoginThrottle())
    REQUESTS.clear()
    PerUserFake.logins.clear()
    PerUserFake.kitsu_down = False
    async with run_server_async(mcp) as url:
        yield url
    client_module._user_clients.clear()
    lookups_module._user_lookups.clear()
    config.get_settings.cache_clear()
