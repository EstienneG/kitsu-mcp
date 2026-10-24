"""Per-caller Kitsu credentials for the HTTP transport.

Over stdio the server logs in with KITSU_USER / KITSU_PASSWORD. Over HTTP (a hosted server used as a Le Chat or
AI Studio connector) each caller sends their own Kitsu login in the `Authorization` header, and every tool call
runs as that person. The server's own login is never used for HTTP calls.
"""

import base64
import binascii
import hashlib
import hmac
import secrets
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


# Keys derived from credentials are HMACs under a secret that only lives in this process, so a key seen
# elsewhere (a cache folder name, a dump) cannot be checked against password guesses offline.
_SECRET = secrets.token_bytes(32)


def keyed_hash(value: str) -> str:
    return hmac.new(_SECRET, value.encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class Credentials:
    user: str
    password: str

    @property
    def key(self) -> str:
        """Cache key for this login (user and password), so passwords never sit in the cache as dict keys."""
        return keyed_hash(f"{self.user}\0{self.password}")

    @property
    def user_key(self) -> str:
        """Key of the user alone, e.g. for their video cache folder (Kitsu authorizes every cache hit)."""
        return keyed_hash(self.user.lower())

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
        found = self.get(key)
        if found is not None:
            return found
        value = create()
        self.put(key, value)
        return value

    def get(self, key: str) -> T | None:
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            if key not in self._items:
                return None
            value = self._items.pop(key)[1]
            self._items[key] = (now, value)
            return value

    def put(self, key: str, value: T) -> None:
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            self._items.pop(key, None)
            self._items[key] = (now, value)
            while len(self._items) > self.max_size:
                self._items.popitem(last=False)

    def _expire(self, now: float) -> None:
        for stale in [k for k, (used, _) in self._items.items() if now - used > self.ttl]:
            del self._items[stale]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        return len(self._items)


class LoginThrottle:
    """Slows down repeated failed logins per user, so the server is not an unthrottled password relay to Kitsu.

    Only rejected credentials count (an unreachable Kitsu does not). A login Kitsu accepted in the last
    `remember` seconds skips the check, so guessing at someone's email cannot lock them out. Spraying many
    emails from one address is not throttled here. The first `free` failures in a row cost nothing; after
    that, the next attempt must wait 2**(failures - free) seconds (capped) since the last failure. A success
    resets the count. Bounded: the oldest users are forgotten past `max_users`.
    """

    def __init__(self, free: int = 5, cap: float = 60, max_users: int = 4096, remember: float = 24 * 3600) -> None:
        self.free = free
        self.cap = cap
        self.max_users = max_users
        self._failures: OrderedDict[str, tuple[int, float]] = OrderedDict()
        # Keys (HMACs) of logins Kitsu accepted in the last `remember` seconds: they bypass the throttle.
        self._good: TTLCache[bool] = TTLCache(ttl=remember, max_size=max_users)
        self._lock = threading.Lock()

    def known_good(self, login_key: str) -> bool:
        return self._good.get(login_key) is not None

    def check(self, user_key: str) -> None:
        with self._lock:
            count, last = self._failures.get(user_key, (0, 0.0))
        if count <= self.free:
            return
        wait = min(self.cap, 2 ** (count - self.free)) - (time.monotonic() - last)
        if wait > 0:
            raise ToolError(f"Too many failed Kitsu logins for this account; try again in {wait:.0f} s")

    def failed(self, user_key: str) -> None:
        with self._lock:
            count, _ = self._failures.pop(user_key, (0, 0.0))
            self._failures[user_key] = (count + 1, time.monotonic())
            while len(self._failures) > self.max_users:
                self._failures.popitem(last=False)

    def succeeded(self, user_key: str, login_key: str) -> None:
        with self._lock:
            self._failures.pop(user_key, None)
        self._good.put(login_key, True)
