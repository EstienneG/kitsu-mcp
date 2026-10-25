"""A real HTTP server for tests: each caller logs in to a fake Kitsu with their own credentials.

The `server` fixture (conftest.py) starts it; `basic()` builds a caller's Authorization header.
"""

import base64

from fastmcp.exceptions import ToolError

from kitsu_mcp.kitsu.client import LoginRejected
from tests.fakes import ALICE, BOB, FakeClient


def basic(user: str, password: str) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


REQUESTS: list[tuple[str, str]] = []
"""(login the request was made with, path) of every request the fake Kitsu received."""


class PerUserFake(FakeClient):
    """A fake Kitsu client: logs in like the real one (wrong password rejected on connect) and records which
    login each request was made with, the way a real Zou would see its bearer token."""

    people = {"alice@example.com": ALICE, "bob@example.com": BOB}
    logins: list[str] = []
    kitsu_down = False

    def __init__(self, settings, credentials=None):
        super().__init__()
        self.settings = settings
        self.credentials = credentials
        self.data["me"] = self.people.get(credentials.user) if credentials else None

    def connect(self) -> None:
        PerUserFake.logins.append(self.credentials.user)
        if PerUserFake.kitsu_down:
            raise ToolError("Could not reach Kitsu on POST auth/login: ConnectionError")
        if self.credentials.user not in self.people or self.credentials.password != "right":
            raise LoginRejected("Kitsu rejected the credentials; check the Kitsu email and password")

    def get(self, path, params=None):
        REQUESTS.append((self.credentials.user, path))
        return super().get(path, params)
