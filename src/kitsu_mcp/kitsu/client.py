"""Thin wrapper over gazu's raw HTTP client: lazy login, re-login on expiry, retries."""

import threading
import time
from pathlib import Path
from typing import Any

import gazu
import requests
from fastmcp.exceptions import ToolError
from gazu import client as raw
from gazu.exception import (
    AuthFailedException,
    GazuException,
    NotAllowedException,
    NotAuthenticatedException,
    ParameterException,
    PreviewFileProcessingException,
    RouteNotFoundException,
    ServerErrorException,
    ValidationException,
)

from kitsu_mcp.config import Settings, get_settings
from kitsu_mcp.kitsu.auth import Credentials, LoginThrottle, TTLCache, request_credentials

# requests.JSONDecodeError: a proxy answered 503/504 with an HTML page (gazu only raises on 500/502).
_TRANSIENT = (ServerErrorException, requests.ConnectionError, requests.Timeout, requests.JSONDecodeError)


class NotFoundError(ToolError):
    """Kitsu answered 404: wrong ID, or a route this instance does not have."""


class LoginRejected(ToolError):
    """Kitsu refused the email/password (not an outage): the only failure the login throttle counts."""


class FileTooLargeError(ToolError):
    """A download went past its size cap and was stopped."""


def size_guard(path: str, max_bytes: int | None):
    """Progress callback for downloads that stops them once they exceed `max_bytes`."""

    def check(bytes_read: int, total: int) -> None:
        if max_bytes is not None and max(bytes_read, total) > max_bytes:
            raise FileTooLargeError(f"{path} is larger than the {max_bytes / 2**20:.0f} MB download cap")

    return check


class KitsuClient:
    def __init__(self, settings: Settings, credentials: Credentials | None = None) -> None:
        """`credentials`: log in as this person instead of KITSU_USER / KITSU_PASSWORD (HTTP callers)."""
        self.settings = settings
        self.credentials = credentials
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
                # Mark the first login as in progress too, so a 401 on it does not trigger a second attempt.
                self._relogging.active = True
                try:
                    self._log_in(client)
                finally:
                    self._relogging.active = False
                self._raw = client
            return self._raw

    def connect(self) -> None:
        """Log in now (instead of on the first request), reporting a rejected login as a ToolError."""
        try:
            self._connect()
        except (NotAuthenticatedException, AuthFailedException) as error:
            raise LoginRejected(str(_tool_error(error, "POST", "auth/login"))) from error
        except (requests.ConnectionError, requests.Timeout, requests.JSONDecodeError, ServerErrorException) as error:
            raise ToolError(
                f"Could not log in: Kitsu is unreachable or unavailable ({error.__class__.__name__})"
            ) from error
        except (GazuException, requests.RequestException) as error:
            raise _tool_error(error, "POST", "auth/login") from error

    def _log_in(self, client: raw.KitsuClient) -> None:
        if self.credentials is not None:
            gazu.log_in(self.credentials.user, self.credentials.password, client=client)
            return
        if not self.settings.user or self.settings.password is None:
            raise RuntimeError("Missing configuration: KITSU_USER, KITSU_PASSWORD")
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

    def download(self, path: str, dest: Path, max_bytes: int | None = None) -> int:
        """Stream a file to `dest` (waiting for previews Kitsu is still processing); returns its size."""
        self._call("GET", path, raw.download, path, str(dest), progress_callback=size_guard(path, max_bytes))
        return dest.stat().st_size

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
        return NotFoundError(f"Not found: {path} (wrong ID, or the route does not exist)")
    if isinstance(error, PreviewFileProcessingException):
        return ToolError(f"Kitsu is still processing {path}; try again in a minute")
    if isinstance(error, NotAllowedException):
        return ToolError(f"Permission denied for {method} {path}")
    if isinstance(error, (NotAuthenticatedException, AuthFailedException)):
        return ToolError("Kitsu rejected the credentials; check the Kitsu email and password")
    if isinstance(error, (ParameterException, ValidationException)):
        return ToolError(f"Kitsu rejected {method} {path}: {error}")
    if isinstance(error, requests.JSONDecodeError | requests.ConnectionError | requests.Timeout) and method != "GET":
        # The request may have reached Zou before the proxy or connection gave up.
        return ToolError(
            f"No usable answer from Kitsu on {method} {path} ({error.__class__.__name__}); the change MAY have "
            "been applied. Check the current state (e.g. get_task) before retrying."
        )
    if isinstance(error, requests.JSONDecodeError):
        return ToolError(f"Kitsu returned a non-JSON response on {method} {path} (server or proxy unavailable?)")
    if isinstance(error, (requests.ConnectionError, requests.Timeout)):
        return ToolError(f"Could not reach Kitsu on {method} {path}: {error.__class__.__name__}")
    return ToolError(f"Kitsu error on {method} {path}: {error.__class__.__name__} {error}")


_override: KitsuClient | None = None
_server_client: KitsuClient | None = None
_server_lock = threading.Lock()
_user_clients: TTLCache[KitsuClient] = TTLCache(ttl=3600, max_size=256)
_logins = LoginThrottle()
_login_locks: TTLCache[threading.Lock] = TTLCache(ttl=3600, max_size=4096)
_login_locks_guard = threading.Lock()


def get_client() -> KitsuClient:
    """The Kitsu client for the current call.

    Over HTTP: the caller's own, from their `Authorization` header (never the server's login). Over stdio:
    the server's, logged in as KITSU_USER.
    """
    global _server_client
    if _override is not None:
        return _override
    credentials = request_credentials()
    if credentials is not None:
        return _user_client(credentials)
    with _server_lock:
        if _server_client is None:
            _server_client = KitsuClient(get_settings())
        return _server_client


def _user_client(credentials: Credentials) -> KitsuClient:
    """A caller's logged-in client. Only successful logins are cached, so wrong passwords cannot push real
    users out of the cache; repeated failures for one account are slowed down (LoginThrottle)."""
    cached = _user_clients.get(credentials.key)
    if cached is not None:
        return cached
    with _login_locks_guard:
        lock = _login_locks.get_or_create(credentials.user_key, threading.Lock)
    with lock:  # one login at a time per account; concurrent first calls reuse the winner's client
        cached = _user_clients.get(credentials.key)
        if cached is not None:
            return cached
        # A login Kitsu accepted recently skips the throttle: someone who only knows the email cannot lock
        # out the person who knows the password.
        if not _logins.known_good(credentials.key):
            _logins.check(credentials.user_key)
        client = KitsuClient(get_settings(), credentials)
        try:
            client.connect()
        except LoginRejected:
            _logins.failed(credentials.user_key)
            raise
        _logins.succeeded(credentials.user_key, credentials.key)
        _user_clients.put(credentials.key, client)
        return client


def set_client(client: KitsuClient | None) -> None:
    """Swap the shared client (used by tests); None goes back to the normal per-call choice."""
    global _override
    _override = client
