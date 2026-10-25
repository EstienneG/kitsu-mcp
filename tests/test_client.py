import pytest
import requests
from fastmcp.exceptions import ToolError
from gazu import client as raw
from gazu.exception import (
    NotAllowedException,
    NotAuthenticatedException,
    RouteNotFoundException,
    ServerErrorException,
)
from pydantic import ValidationError

from kitsu_mcp.config import Settings
from kitsu_mcp.kitsu import client as client_module
from kitsu_mcp.kitsu.client import KitsuClient


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
        with pytest.raises(RuntimeError, match="Missing configuration: KITSU_HOST$"):
            config.get_settings()
    finally:
        config.get_settings.cache_clear()


def test_stdio_requires_a_login():
    """The login is optional in Settings (HTTP callers bring their own) but required over stdio."""
    from kitsu_mcp.config import require_login

    with pytest.raises(RuntimeError, match="Missing configuration: KITSU_USER, KITSU_PASSWORD"):
        require_login(Settings(host="http://kitsu.test/api"))  # type: ignore[arg-type]
    require_login(Settings(host="http://kitsu.test/api", user="u", password="p"))  # type: ignore[arg-type]


def test_relogin_does_not_recurse_when_login_itself_is_rejected(monkeypatch):
    """A 401 on auth/login makes gazu call the not-authenticated callback again, from inside log_in."""
    client = KitsuClient(Settings(host="http://kitsu.test/api", user="u", password="p"))  # type: ignore[arg-type]
    calls = []

    def log_in(user, password, client):
        calls.append(user)
        # gazu would invoke the callback here on a 401; it must refuse instead of logging in again.
        assert kitsu_client._relogin(client, "auth/login") is False
        raise NotAuthenticatedException("auth/login")

    kitsu_client = client
    monkeypatch.setattr(client_module.gazu, "log_in", log_in)
    assert client._relogin(object(), "data/x") is False  # type: ignore[arg-type]
    assert calls == ["u"]
    # The guard is released afterwards, so a later expiry can log in again.
    monkeypatch.setattr(client_module.gazu, "log_in", lambda user, password, client: None)
    assert client._relogin(object(), "data/x") is True  # type: ignore[arg-type]


def test_non_json_response_is_retried_then_readable(kitsu, monkeypatch):
    attempts = []

    def proxy_error(path, params=None, client=None):
        attempts.append(path)
        raise requests.JSONDecodeError("Expecting value", "<html>503</html>", 0)

    monkeypatch.setattr(raw, "get", proxy_error)
    with pytest.raises(ToolError, match="non-JSON response"):
        kitsu.get("data/x")
    assert len(attempts) == 3


def test_network_error_after_retries_is_a_tool_error(kitsu, monkeypatch):
    def offline(path, params=None, client=None):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(raw, "get", offline)
    with pytest.raises(ToolError, match="Could not reach Kitsu"):
        kitsu.get("data/x")


def test_max_retries_must_be_positive():
    with pytest.raises(ValidationError):
        Settings(host="h", user="u", password="p", max_retries=0)  # type: ignore[arg-type]


def test_failed_first_login_is_attempted_once_and_readable(monkeypatch):
    """With a wrong password, the initial login must not be retried through the re-login callback."""
    client = KitsuClient(Settings(host="http://kitsu.test/api", user="u", password="bad"))  # type: ignore[arg-type]
    attempts = []

    def log_in(user, password, client):
        attempts.append(user)
        # gazu calls the not-authenticated callback when auth/login answers 401
        assert client.callback_not_authenticated(client, "auth/login") is False
        raise client_module.AuthFailedException("auth/login")

    monkeypatch.setattr(client_module.gazu, "log_in", log_in)
    with pytest.raises(ToolError, match="rejected the credentials"):
        client.get("data/x")
    assert attempts == ["u"]


@pytest.mark.parametrize("error", [requests.Timeout("slow"), requests.JSONDecodeError("x", "<html>", 0)])
def test_write_without_answer_says_it_may_have_landed(kitsu, monkeypatch, error):
    def post(path, data, client=None):
        raise error

    monkeypatch.setattr(raw, "post", post)
    with pytest.raises(ToolError, match="MAY have been applied"):
        kitsu.post("actions/tasks/t/comment", {})
