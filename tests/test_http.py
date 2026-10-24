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


def test_keys_cannot_be_checked_offline():
    """Keys are HMACs under a per-process secret, not plain hashes an attacker could recompute."""
    import hashlib

    credentials = Credentials("alice@example.com", "hunter2")
    assert credentials.key != hashlib.sha256(b"alice@example.com\0hunter2").hexdigest()
    assert credentials.user_key == Credentials("ALICE@example.com", "other").user_key  # the user alone


def test_login_throttle(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(auth.time, "monotonic", lambda: clock[0])
    throttle = auth.LoginThrottle(free=2, cap=8)
    throttle.failed("u")
    throttle.failed("u")
    throttle.check("u")  # the free failures do not slow anything down
    throttle.failed("u")  # third failure: next attempt waits 2 s
    with pytest.raises(ToolError, match="Too many failed Kitsu logins"):
        throttle.check("u")
    clock[0] += 2.5
    throttle.check("u")
    throttle.check("someone-else")
    throttle.succeeded("u")
    throttle.failed("u")
    throttle.check("u")  # a success resets the count


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


REQUESTS: list[tuple[str, str]] = []
"""(login the request was made with, path) of every request the fake Kitsu received."""


class PerUserFake(FakeClient):
    """A fake Kitsu client: logs in like the real one (wrong password rejected on connect) and records which
    login each request was made with, the way a real Zou would see its bearer token."""

    people = {"alice@example.com": ALICE, "bob@example.com": BOB}
    logins: list[str] = []

    def __init__(self, settings, credentials=None):
        super().__init__()
        self.settings = settings
        self.credentials = credentials
        self.data["me"] = self.people.get(credentials.user) if credentials else None

    def connect(self) -> None:
        PerUserFake.logins.append(self.credentials.user)
        if self.credentials.user not in self.people or self.credentials.password != "right":
            raise ToolError("Kitsu rejected the credentials; check the Kitsu email and password")

    def get(self, path, params=None):
        REQUESTS.append((self.credentials.user, path))
        return super().get(path, params)


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
    monkeypatch.setattr(client_module, "_logins", auth.LoginThrottle())
    REQUESTS.clear()
    PerUserFake.logins.clear()
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


async def test_interleaved_sessions_reach_kitsu_as_their_own_user(server):
    """Several concurrent sessions alternating two users: every Kitsu request carries the caller's login."""
    import asyncio

    users = {"A": "alice@example.com", "B": "bob@example.com"}
    seen: list[tuple[str, str]] = []

    async def session(tag: str) -> None:
        async with Client(StreamableHttpTransport(server, headers=basic(users[tag], "right"))) as session:
            for _ in range(5):
                me = (await session.call_tool("whoami", {})).data
                seen.append((tag, me["id"]))
                await session.call_tool("list_projects", {})

    await asyncio.gather(*(session("A" if i % 2 == 0 else "B") for i in range(8)))
    expected = {"A": ALICE, "B": BOB}
    assert len(seen) == 40 and all(person == expected[tag] for tag, person in seen)
    assert {user for user, _ in REQUESTS} == set(users.values())
    assert PerUserFake.logins.count("alice@example.com") == 1  # logged in once, then reused


async def test_header_decides_per_request(server):
    """A session's own header decides who each call runs as, not who opened earlier sessions."""
    assert (await call(server, basic("alice@example.com", "right"), "whoami"))["id"] == ALICE
    assert (await call(server, basic("bob@example.com", "right"), "whoami"))["id"] == BOB
    assert (await call(server, basic("alice@example.com", "right"), "whoami"))["id"] == ALICE


async def test_wrong_passwords_are_not_cached_and_get_throttled(server):
    alice = basic("alice@example.com", "right")
    await call(server, alice, "whoami")
    for attempt in range(8):
        with pytest.raises(ToolError, match="rejected the credentials|Too many failed"):
            await call(server, basic("bob@example.com", f"guess{attempt}"), "whoami")
    assert len(client_module._user_clients) == 1  # only Alice's good login is cached
    assert PerUserFake.logins.count("bob@example.com") < 8  # throttled before every guess reached Kitsu
    assert (await call(server, alice, "whoami"))["id"] == ALICE


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
    import stat

    from kitsu_mcp import video

    fake.settings.video_cache_dir = tmp_path / "cache"
    assert video.cache_dir() == tmp_path / "cache"  # stdio: the server's own folder
    fake.credentials = Credentials("alice@example.com", "right")
    alice_dir = video.cache_dir()
    fake.credentials = Credentials("bob@example.com", "right")
    bob_dir = video.cache_dir()
    assert alice_dir != bob_dir and alice_dir.parent == bob_dir.parent == tmp_path / "cache" / "users"
    for folder in (tmp_path / "cache", alice_dir.parent, alice_dir):
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700

    (alice_dir / "old.mp4").write_bytes(b"x" * 600)
    (bob_dir / "new.mp4").write_bytes(b"x" * 600)
    import os

    os.utime(alice_dir / "old.mp4", (1, 1))
    fake.settings.video_cache_mb = 1000 / 2**20  # room for one movie, whoever it belongs to
    video.evict()
    assert not (alice_dir / "old.mp4").exists()
    assert (bob_dir / "new.mp4").exists()
