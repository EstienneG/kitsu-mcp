"""Flattened views over a project's assets and shots, shared by search and reporting tools."""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from kitsu_mcp.client import KitsuClient
from kitsu_mcp.lookups import DUE_ROLES, OPEN_ROLES, Lookups, Role
from kitsu_mcp.models import TaskRow

EntityKind = Literal["asset", "shot", "any"]


def today() -> date:
    """Indirection so tests can pin the date."""
    return date.today()


def day(value: str | None) -> str | None:
    """Zou dates come as `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS`; keep the day."""
    return value[:10] if value else None


@dataclass
class TaskRecord:
    """A task with its entity context and resolved reference data."""

    raw: dict
    entity: dict
    entity_kind: Literal["asset", "shot"]
    group: str | None
    """Asset type for assets, sequence (with episode) for shots."""

    def row(self, lookups: Lookups) -> TaskRow:
        task = self.raw
        return TaskRow(
            id=task["id"],
            entity_id=self.entity["id"],
            entity=self.entity.get("name"),
            entity_kind=self.entity_kind,
            group=self.group,
            task_type=lookups.name("task_types", task.get("task_type_id")),
            status=lookups.name("task_statuses", task.get("task_status_id"), "short_name"),
            assignees=[lookups.person_name(a) or a for a in task.get("assignees") or []],
            due_date=day(task.get("due_date")),
            estimation=task.get("estimation"),
            duration=task.get("duration"),
            retake_count=task.get("retake_count"),
            last_comment_date=task.get("last_comment_date"),
            last_preview_file_id=task.get("last_preview_file_id"),
        )

    def role(self, lookups: Lookups) -> Role:
        return lookups.role(self.raw.get("task_status_id"))

    def is_open(self, lookups: Lookups) -> bool:
        """Still to do: not done and not omitted (on-hold tasks are open)."""
        return self.role(lookups) in OPEN_ROLES

    def is_overdue(self, lookups: Lookups) -> bool:
        """Due date passed on a task still being worked on (not done, omitted or on hold)."""
        due = day(self.raw.get("due_date"))
        return due is not None and due < today().isoformat() and self.role(lookups) in DUE_ROLES


@dataclass
class EntityRecord:
    """A non-canceled asset or shot, with its tasks as returned by the `with-tasks` routes."""

    raw: dict
    kind: Literal["asset", "shot"]
    group: str | None
    """Asset type for assets, episode/sequence for shots."""

    def tasks(self) -> list[TaskRecord]:
        return [TaskRecord(t, self.raw, self.kind, self.group) for t in self.raw.get("tasks") or []]


def project_entities(
    client: KitsuClient, lookups: Lookups, project_id: str, kind: EntityKind = "any"
) -> list[EntityRecord]:
    """A project's non-canceled assets and/or shots, including those without tasks."""
    entities: list[EntityRecord] = []
    if kind in ("asset", "any"):
        for asset in client.get("data/assets/with-tasks", params={"project_id": project_id}):
            if not asset.get("canceled"):
                group = asset.get("asset_type_name") or lookups.name("asset_types", asset.get("entity_type_id"))
                entities.append(EntityRecord(asset, "asset", group))
    if kind in ("shot", "any"):
        for shot in client.get("data/shots/with-tasks", params={"project_id": project_id}):
            if not shot.get("canceled"):
                group = "/".join(p for p in (shot.get("episode_name"), shot.get("sequence_name")) if p) or None
                entities.append(EntityRecord(shot, "shot", group))
    return entities


def project_tasks(client: KitsuClient, lookups: Lookups, project_id: str, kind: EntityKind = "any") -> list[TaskRecord]:
    """All tasks on a project's (non-canceled) assets and/or shots."""
    return [task for entity in project_entities(client, lookups, project_id, kind) for task in entity.tasks()]
