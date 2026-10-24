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

_TRANSIENT = (ServerErrorException, requests.ConnectionError, requests.Timeout)


class KitsuClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._raw: raw.KitsuClient | None = None
        self._lock = threading.Lock()

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
        """gazu callback when the access and refresh tokens are both rejected."""
        try:
            self._log_in(client)
        except GazuException:
            return False
        return True

    def _call(self, fn, *args, retry: bool = True, **kwargs) -> Any:
        attempts = self.settings.max_retries if retry else 1
        for attempt in range(attempts):
            try:
                return fn(*args, client=self._connect(), **kwargs)
            except _TRANSIENT:
                if attempt == attempts - 1:
                    raise
                time.sleep(0.5 * 2**attempt)
        raise AssertionError("unreachable")

    def get(self, path: str, params: dict | None = None) -> Any:
        try:
            return self._call(raw.get, path, params=params)
        except GazuException as error:
            raise _tool_error(error, "GET", path) from error

    def get_bytes(self, path: str) -> bytes:
        try:
            return self._call(raw.get_file_data_from_url, path)
        except GazuException as error:
            raise _tool_error(error, "GET", path) from error

    def post(self, path: str, data: Any) -> Any:
        try:
            return self._call(raw.post, path, data, retry=False)
        except GazuException as error:
            raise _tool_error(error, "POST", path) from error

    def put(self, path: str, data: dict) -> Any:
        try:
            return self._call(raw.put, path, data, retry=False)
        except GazuException as error:
            raise _tool_error(error, "PUT", path) from error

    def user_id(self) -> str:
        return self.get("auth/authenticated")["user"]["id"]


def _apply_timeout(session: requests.Session, timeout: float) -> None:
    request = session.request

    def request_with_timeout(method, url, **kwargs):
        kwargs.setdefault("timeout", timeout)
        return request(method, url, **kwargs)

    session.request = request_with_timeout  # type: ignore[method-assign]


def _tool_error(error: GazuException, method: str, path: str) -> ToolError:
    if isinstance(error, RouteNotFoundException):
        return ToolError(f"Not found: {path} (wrong ID, or the route does not exist)")
    if isinstance(error, NotAllowedException):
        return ToolError(f"Permission denied for {method} {path}")
    if isinstance(error, NotAuthenticatedException):
        return ToolError("Kitsu rejected the credentials; check KITSU_USER / KITSU_PASSWORD")
    if isinstance(error, (ParameterException, ValidationException)):
        return ToolError(f"Kitsu rejected {method} {path}: {error}")
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
