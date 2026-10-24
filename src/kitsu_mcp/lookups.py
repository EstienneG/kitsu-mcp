"""Cached reference data (task types, statuses, people, ...) and name → record resolvers."""

import threading
import time
from typing import Any

from fastmcp.exceptions import ToolError

from kitsu_mcp.client import KitsuClient, get_client
from kitsu_mcp.config import get_settings

Record = dict[str, Any]

_SOURCES = {
    "projects": "data/projects",
    "project_statuses": "data/project-status",
    "task_types": "data/task-types",
    "task_statuses": "data/task-status",
    "people": "data/persons",
    "asset_types": "data/asset-types",
}

_LABELS = {
    "projects": "project",
    "project_statuses": "project status",
    "task_types": "task type",
    "task_statuses": "task status",
    "people": "person",
    "asset_types": "asset type",
}


class Lookups:
    def __init__(self, client: KitsuClient, ttl: float) -> None:
        self.client = client
        self.ttl = ttl
        self._cache: dict[str, tuple[float, dict[str, Record]]] = {}
        self._lock = threading.Lock()

    def index(self, kind: str) -> dict[str, Record]:
        """All records of a kind, keyed by ID."""
        with self._lock:
            cached = self._cache.get(kind)
            if cached and time.monotonic() - cached[0] < self.ttl:
                return cached[1]
        records = {r["id"]: r for r in self.client.get(_SOURCES[kind])}
        with self._lock:
            self._cache[kind] = (time.monotonic(), records)
        return records

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def name(self, kind: str, record_id: str | None, field: str = "name") -> str | None:
        if not record_id:
            return None
        return self.index(kind).get(record_id, {}).get(field)

    def status_flag(self, status_id: str | None, flag: str) -> bool:
        """A boolean flag of a task status: is_done, is_wip, is_retake, is_feedback_request."""
        if not status_id:
            return False
        return bool(self.index("task_statuses").get(status_id, {}).get(flag))

    def person_name(self, person_id: str | None) -> str | None:
        if not person_id:
            return None
        return self.index("people").get(person_id, {}).get("full_name", person_id)

    def resolve(self, kind: str, ref: str, fields: tuple[str, ...] = ("name",)) -> Record:
        """Find a record by ID or by (case-insensitive) value of one of `fields`."""
        records = self.index(kind)
        if ref in records:
            return records[ref]
        wanted = ref.strip().lower()
        matches = [r for r in records.values() if any(str(r.get(f) or "").lower() == wanted for f in fields)]
        if len(matches) == 1:
            return matches[0]
        label = _LABELS[kind]
        if matches:
            raise ToolError(f"Ambiguous {label} '{ref}': matches IDs {', '.join(m['id'] for m in matches)}")
        options = sorted({str(r.get(fields[0])) for r in records.values() if r.get(fields[0])})
        shown = ", ".join(options[:50]) + (" ..." if len(options) > 50 else "")
        raise ToolError(f"Unknown {label} '{ref}'. Valid values: {shown}")

    def project(self, ref: str) -> Record:
        return self.resolve("projects", ref)

    def task_type(self, ref: str) -> Record:
        return self.resolve("task_types", ref, ("name", "short_name"))

    def task_status(self, ref: str) -> Record:
        return self.resolve("task_statuses", ref, ("short_name", "name"))

    def person(self, ref: str) -> Record:
        return self.resolve("people", ref, ("full_name", "email", "desktop_login"))

    def asset_type(self, ref: str) -> Record:
        return self.resolve("asset_types", ref)


_lookups: Lookups | None = None


def get_lookups() -> Lookups:
    global _lookups
    if _lookups is None:
        _lookups = Lookups(get_client(), get_settings().cache_ttl)
    return _lookups


def set_lookups(lookups: Lookups | None) -> None:
    """Swap the shared lookups (used by tests)."""
    global _lookups
    _lookups = lookups
