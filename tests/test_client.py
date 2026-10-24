import pytest
from fastmcp.exceptions import ToolError
from gazu import client as raw
from gazu.exception import NotAllowedException, RouteNotFoundException, ServerErrorException

from kitsu_mcp import client as client_module
from kitsu_mcp.client import KitsuClient
from kitsu_mcp.config import Settings


@pytest.fixture
def kitsu(monkeypatch):
    monkeypatch.setattr(client_module.time, "sleep", lambda _: None)
    client = KitsuClient(Settings(host="http://kitsu.test/api", user="u", password="p", max_retries=3))  # type: ignore[arg-type]
    monkeypatch.setattr(client, "_connect", lambda: object())
    return client


def test_get_retries_transient_errors(kitsu, monkeypatch):
    attempts = []

    def flaky(path, params=None, client=None):
        attempts.append(path)
        if len(attempts) < 3:
            raise ServerErrorException(path)
        return {"ok": True}

    monkeypatch.setattr(raw, "get", flaky)
    assert kitsu.get("data/x") == {"ok": True}
    assert len(attempts) == 3


def test_get_gives_up_after_max_retries(kitsu, monkeypatch):
    def down(path, params=None, client=None):
        raise ServerErrorException(path)

    monkeypatch.setattr(raw, "get", down)
    with pytest.raises(ToolError, match="ServerErrorException"):
        kitsu.get("data/x")


def test_post_is_not_retried(kitsu, monkeypatch):
    attempts = []

    def down(path, data, client=None):
        attempts.append(path)
        raise ServerErrorException(path)

    monkeypatch.setattr(raw, "post", down)
    with pytest.raises(ToolError):
        kitsu.post("actions/x", {})
    assert len(attempts) == 1


@pytest.mark.parametrize(
    "error, message", [(RouteNotFoundException, "Not found"), (NotAllowedException, "Permission denied")]
)
def test_errors_are_readable(kitsu, monkeypatch, error, message):
    def fail(path, params=None, client=None):
        raise error(path)

    monkeypatch.setattr(raw, "get", fail)
    with pytest.raises(ToolError, match=message):
        kitsu.get("data/x")


def test_relogin_callback_logs_in_again(monkeypatch):
    calls = []
    monkeypatch.setattr(client_module.gazu, "log_in", lambda user, password, client: calls.append((user, password)))
    client = KitsuClient(Settings(host="http://kitsu.test/api", user="u", password="secret"))  # type: ignore[arg-type]
    assert client._relogin(object(), "data/x") is True  # type: ignore[arg-type]
    assert calls == [("u", "secret")]


def test_missing_config_is_reported(monkeypatch):
    from kitsu_mcp import config

    for var in ("KITSU_HOST", "KITSU_USER", "KITSU_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir("/")
    config.get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="Missing configuration: KITSU_HOST, KITSU_USER, KITSU_PASSWORD"):
            config.get_settings()
    finally:
        config.get_settings.cache_clear()
