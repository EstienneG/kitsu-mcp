"""Per-caller Kitsu credentials for the HTTP transport.

Over stdio the server logs in with KITSU_USER / KITSU_PASSWORD. Over HTTP (a hosted server used as a Le Chat or
AI Studio connector) each caller sends their own Kitsu login in the `Authorization` header, and every tool call
runs as that person. The server's own login is never used for HTTP calls.
"""

import base64
import binascii
import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request

AUTH_HELP = (
    "Kitsu login missing: set the connector's authentication to Basic with your Kitsu email and password "
    "(or a Bearer token of the form email:password)."
)


@dataclass(frozen=True)
class Credentials:
    user: str
    password: str

    @property
    def key(self) -> str:
        """Cache key: a hash, so passwords never sit in the cache as dict keys."""
        return hashlib.sha256(f"{self.user}\0{self.password}".encode()).hexdigest()

    def __repr__(self) -> str:
        return f"Credentials(user={self.user!r}, password='***')"


def parse_authorization(header: str) -> Credentials | None:
    """Kitsu email and password from `Basic base64(email:password)` or `Bearer email:password`."""
    scheme, _, value = header.strip().partition(" ")
    value = value.strip()
    if scheme.lower() == "basic":
        try:
            value = base64.b64decode(value, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return None
    elif scheme.lower() != "bearer":
        return None
    user, sep, password = value.partition(":")
    if not sep or not user or not password:
        return None
    return Credentials(user.strip(), password)


def request_credentials() -> Credentials | None:
    """The caller's credentials when the current call came over HTTP; None over stdio (no HTTP request).

    Raises when the call came over HTTP without usable credentials, so it can never fall back to the
    server's own login.
    """
    try:
        request = get_http_request()
    except RuntimeError:
        return None
    credentials = parse_authorization(request.headers.get("authorization", ""))
    if credentials is None:
        raise ToolError(AUTH_HELP)
    return credentials


class TTLCache[T]:
    """A small thread-safe LRU cache whose entries expire `ttl` seconds after they were last used."""

    def __init__(self, ttl: float, max_size: int) -> None:
        self.ttl = ttl
        self.max_size = max_size
        self._items: OrderedDict[str, tuple[float, T]] = OrderedDict()
        self._lock = threading.Lock()

    def get_or_create(self, key: str, create) -> T:
        now = time.monotonic()
        with self._lock:
            for stale in [k for k, (used, _) in self._items.items() if now - used > self.ttl]:
                del self._items[stale]
            value = self._items.pop(key)[1] if key in self._items else create()
            self._items[key] = (now, value)
            while len(self._items) > self.max_size:
                self._items.popitem(last=False)
            return value

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        return len(self._items)
