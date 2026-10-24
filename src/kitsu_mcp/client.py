"""Thin wrapper over gazu's raw HTTP client: lazy login, re-login on expiry, retries."""

import threading
import time
from typing import Any

import gazu
import requests
from fastmcp.exceptions import ToolError
from gazu import client as raw
from gazu.exception import (
    GazuException,
    NotAllowedException,
    NotAuthenticatedException,
    ParameterException,
    RouteNotFoundException,
    ServerErrorException,
    ValidationException,
)

from kitsu_mcp.config import Settings, get_settings

# requests.JSONDecodeError: a proxy answered 503/504 with an HTML page (gazu only raises on 500/502).
_TRANSIENT = (ServerErrorException, requests.ConnectionError, requests.Timeout, requests.JSONDecodeError)


class KitsuClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._raw: raw.KitsuClient | None = None
        self._lock = threading.Lock()
        self._relogging = threading.local()

    def _connect(self) -> raw.KitsuClient:
        with self._lock:
            if self._raw is None:
                client = raw.create_client(
                    self.settings.host,
                    use_refresh_token=True,
                    callback_not_authenticated=self._relogin,
                )
                _apply_timeout(client.session, self.settings.timeout)
                self._log_in(client)
                self._raw = client
            return self._raw

    def _log_in(self, client: raw.KitsuClient) -> None:
        gazu.log_in(self.settings.user, self.settings.password.get_secret_value(), client=client)

    def _relogin(self, client: raw.KitsuClient, _path: str) -> bool:
        """gazu callback when the access and refresh tokens are both rejected.

        The login request goes through the same client, so a 401 on `auth/login` would call back
        here again; the guard makes that nested call give up instead of recursing.
        """
        if getattr(self._relogging, "active", False):
            return False
        self._relogging.active = True
        try:
            self._log_in(client)
        except GazuException:
            return False
        finally:
            self._relogging.active = False
        return True

    def _call(self, method: str, path: str, fn, *args, retry: bool = True, **kwargs) -> Any:
        """Run a gazu request; reads retry transient failures, writes never do (they may have landed)."""
        attempts = self.settings.max_retries if retry else 1
        for attempt in range(attempts):
            try:
                return fn(*args, client=self._connect(), **kwargs)
            except _TRANSIENT as error:
                if attempt == attempts - 1:
                    raise _tool_error(error, method, path) from error
                time.sleep(0.5 * 2**attempt)
            except (GazuException, requests.RequestException) as error:
                raise _tool_error(error, method, path) from error
        raise AssertionError("unreachable: max_retries >= 1")

    def get(self, path: str, params: dict | None = None) -> Any:
        return self._call("GET", path, raw.get, path, params=params)

    def get_bytes(self, path: str) -> bytes:
        return self._call("GET", path, raw.get_file_data_from_url, path)

    def post(self, path: str, data: Any) -> Any:
        return self._call("POST", path, raw.post, path, data, retry=False)

    def put(self, path: str, data: dict) -> Any:
        return self._call("PUT", path, raw.put, path, data, retry=False)

    def user_id(self) -> str:
        return self.get("auth/authenticated")["user"]["id"]


def _apply_timeout(session: requests.Session, timeout: float) -> None:
    request = session.request

    def request_with_timeout(method, url, **kwargs):
        kwargs.setdefault("timeout", timeout)
        return request(method, url, **kwargs)

    session.request = request_with_timeout  # type: ignore[method-assign]


def _tool_error(error: Exception, method: str, path: str) -> ToolError:
    if isinstance(error, RouteNotFoundException):
        return ToolError(f"Not found: {path} (wrong ID, or the route does not exist)")
    if isinstance(error, NotAllowedException):
        return ToolError(f"Permission denied for {method} {path}")
    if isinstance(error, NotAuthenticatedException):
        return ToolError("Kitsu rejected the credentials; check KITSU_USER / KITSU_PASSWORD")
    if isinstance(error, (ParameterException, ValidationException)):
        return ToolError(f"Kitsu rejected {method} {path}: {error}")
    if isinstance(error, requests.JSONDecodeError):
        return ToolError(f"Kitsu returned a non-JSON response on {method} {path} (server or proxy unavailable?)")
    if isinstance(error, (requests.ConnectionError, requests.Timeout)):
        return ToolError(f"Could not reach Kitsu on {method} {path}: {error.__class__.__name__}")
    return ToolError(f"Kitsu error on {method} {path}: {error.__class__.__name__} {error}")


_client: KitsuClient | None = None


def get_client() -> KitsuClient:
    global _client
    if _client is None:
        _client = KitsuClient(get_settings())
    return _client


def set_client(client: KitsuClient | None) -> None:
    """Swap the shared client (used by tests)."""
    global _client
    _client = client
