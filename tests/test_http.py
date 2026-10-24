"""HTTP mode: each caller runs as their own Kitsu user, local-disk tools are hidden, links point at Kitsu."""

import base64

import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError
from fastmcp.utilities.tests import run_server_async

from kitsu_mcp import auth
from kitsu_mcp import client as client_module
from kitsu_mcp import lookups as lookups_module
from kitsu_mcp.auth import Credentials, TTLCache, parse_authorization
from kitsu_mcp.server import mcp
from tests.fakes import ALICE, BOB, FakeClient


def basic(user: str, password: str) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


# --- header parsing ----------------------------------------------------------------------------------


def test_parse_basic_and_bearer():
    assert parse_authorization(basic("alice@example.com", "pa:ss")["Authorization"]) == Credentials(
        "alice@example.com", "pa:ss"
    )
    assert parse_authorization("Bearer bob@example.com:secret") == Credentials("bob@example.com", "secret")


@pytest.mark.parametrize(
    "header", ["", "Basic", "Basic !!!", "Basic " + base64.b64encode(b"no-colon").decode(), "Bearer :pw", "Token a:b"]
)
def test_parse_rejects_unusable_headers(header):
    assert parse_authorization(header) is None


def test_credentials_never_show_the_password():
    credentials = Credentials("alice@example.com", "hunter2")
    assert "hunter2" not in repr(credentials)
    assert "hunter2" not in credentials.key


def test_ttl_cache_expires_and_bounds():
    cache: TTLCache[int] = TTLCache(ttl=60, max_size=2)
    assert cache.get_or_create("a", lambda: 1) == 1
    assert cache.get_or_create("a", lambda: 99) == 1
    cache.get_or_create("b", lambda: 2)
    cache.get_or_create("c", lambda: 3)
    assert len(cache) == 2 and cache.get_or_create("a", lambda: 4) == 4  # "a" was the least recently used
    cache.ttl = -1
    assert cache.get_or_create("b", lambda: 5) == 5  # expired


# --- over a real HTTP server ---------------------------------------------------------------------------


class PerUserFake(FakeClient):
    """A fake Kitsu that answers auth/authenticated as the person the credentials belong to."""

    people = {"alice@example.com": ALICE, "bob@example.com": BOB}

    def __init__(self, settings, credentials=None):
        super().__init__()
        self.credentials = credentials
        if credentials is None or credentials.password != "right":
            raise AssertionError("tests only build clients for valid logins")
        self.data["me"] = self.people[credentials.user]


@pytest.fixture
async def server(monkeypatch):
    """The real server over HTTP, with the per-user Kitsu clients faked."""
    from kitsu_mcp import config

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
    async with run_server_async(mcp) as url:
        yield url
    client_module._user_clients.clear()
    lookups_module._user_lookups.clear()
    config.get_settings.cache_clear()


async def call(url: str, headers: dict[str, str], name: str, **args):
    async with Client(StreamableHttpTransport(url, headers=headers)) as session:
        return (await session.call_tool(name, args)).data


async def test_each_caller_runs_as_themselves(server):
    alice = await call(server, basic("alice@example.com", "right"), "whoami")
    bob = await call(server, {"Authorization": "Bearer bob@example.com:right"}, "whoami")
    assert (alice["id"], bob["id"]) == (ALICE, BOB)
    assert len(client_module._user_clients) == 2


async def test_my_tasks_follow_the_caller(server):
    alice = await call(server, basic("alice@example.com", "right"), "my_tasks")
    bob = await call(server, basic("bob@example.com", "right"), "my_tasks")
    assert {t["id"] for t in alice} == {"t-hero-mod"}
    assert {t["id"] for t in bob} == {"t-forest-mod", "t-sh010-comp"}


async def test_missing_credentials_never_fall_back_to_the_server_login(server, monkeypatch):
    from kitsu_mcp import config

    monkeypatch.setenv("KITSU_USER", "server@example.com")
    monkeypatch.setenv("KITSU_PASSWORD", "server-secret")
    config.get_settings.cache_clear()
    with pytest.raises(ToolError, match="Kitsu login missing"):
        await call(server, {}, "whoami")
    assert client_module._server_client is None


async def test_local_disk_tools_are_hidden_over_http(server, tmp_path):
    headers = basic("alice@example.com", "right")
    async with Client(StreamableHttpTransport(server, headers=headers)) as session:
        names = {t.name for t in await session.list_tools()}
    assert "whoami" in names
    assert not names & {"download_previews", "download_video"}
    with pytest.raises(ToolError, match="not available on the hosted server"):
        await call(server, headers, "download_previews", project="Demo Short", dest_dir=str(tmp_path))
    assert list(tmp_path.iterdir()) == []


async def test_local_disk_tools_stay_over_stdio():
    async with Client(mcp) as session:
        names = {t.name for t in await session.list_tools()}
    assert {"download_previews", "download_video"} <= names


async def test_health(server):
    import json
    import urllib.request

    import anyio

    url = server.removesuffix("/mcp") + "/health"
    body = await anyio.to_thread.run_sync(lambda: urllib.request.urlopen(url, timeout=5).read())
    assert json.loads(body) == {"status": "ok"}


def test_request_credentials_outside_http_is_none():
    assert auth.request_credentials() is None


# --- video cache -----------------------------------------------------------------------------------


def test_video_cache_is_per_user_with_one_shared_budget(fake, tmp_path):
    from kitsu_mcp import video

    fake.settings.video_cache_dir = tmp_path
    assert video.cache_dir() == tmp_path  # stdio: the server's own folder
    fake.credentials = Credentials("alice@example.com", "right")
    alice_dir = video.cache_dir()
    fake.credentials = Credentials("bob@example.com", "right")
    bob_dir = video.cache_dir()
    assert alice_dir != bob_dir and alice_dir.parent == bob_dir.parent == tmp_path / "users"

    (alice_dir / "old.mp4").write_bytes(b"x" * 600)
    (bob_dir / "new.mp4").write_bytes(b"x" * 600)
    import os

    os.utime(alice_dir / "old.mp4", (1, 1))
    fake.settings.video_cache_mb = 1000 / 2**20  # room for one movie, whoever it belongs to
    video.evict()
    assert not (alice_dir / "old.mp4").exists()
    assert (bob_dir / "new.mp4").exists()
