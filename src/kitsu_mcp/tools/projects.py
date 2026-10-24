from collections import Counter, defaultdict

from kitsu_mcp.app import READ_ONLY, mcp
from kitsu_mcp.client import get_client
from kitsu_mcp.lookups import get_lookups
from kitsu_mcp.models import (
    Named,
    Project,
    ProjectOverview,
    StatusCount,
    TaskStatus,
    TaskType,
    TaskTypeProgress,
)
from kitsu_mcp.production import TaskRecord, day, project_entities


@mcp.tool(annotations=READ_ONLY, tags={"projects"})
def list_projects(include_closed: bool = False) -> list[Project]:
    """List productions (open ones by default)."""
    lookups = get_lookups()
    projects = get_client().get("data/projects" if include_closed else "data/projects/open")
    return [
        Project(
            id=p["id"],
            name=p["name"],
            production_type=p.get("production_type"),
            status=lookups.name("project_statuses", p.get("project_status_id")),
        )
        for p in projects
    ]


@mcp.tool(annotations=READ_ONLY, tags={"projects"})
def list_task_types() -> list[TaskType]:
    """List task types (Modelling, Animation, ...) with the entity kind they apply to."""
    return [
        TaskType(id=t["id"], name=t["name"], short_name=t.get("short_name"), for_entity=t.get("for_entity"))
        for t in get_lookups().index("task_types").values()
        if not t.get("archived")
    ]


@mcp.tool(annotations=READ_ONLY, tags={"projects"})
def list_task_statuses() -> list[TaskStatus]:
    """List task statuses with their short names (wip, wfa, done, ...) and flags."""
    return [
        TaskStatus(
            id=s["id"],
            name=s["name"],
            short_name=s["short_name"],
            is_done=s.get("is_done"),
            is_wip=s.get("is_wip"),
            is_retake=s.get("is_retake"),
            is_feedback_request=s.get("is_feedback_request"),
        )
        for s in get_lookups().index("task_statuses").values()
        if not s.get("archived")
    ]


@mcp.tool(annotations=READ_ONLY, tags={"projects", "assets"})
def list_asset_types(project: str) -> list[Named]:
    """List asset types used in a project (name or ID)."""
    project_id = get_lookups().project(project)["id"]
    return [Named(id=t["id"], name=t["name"]) for t in get_client().get(f"data/projects/{project_id}/asset-types")]


def _ratio(part: int, total: int) -> float:
    return round(part / total, 3) if total else 0.0


@mcp.tool(annotations=READ_ONLY, tags={"projects", "reporting"})
def project_overview(project: str) -> ProjectOverview:
    """Where a production stands: entity and task counts, completion per task type, overdue tasks,
    tasks waiting for feedback, retakes, unassigned work and time logged vs. estimated."""
    client = get_client()
    lookups = get_lookups()
    info = client.get(f"data/projects/{lookups.project(project)['id']}")
    entities = project_entities(client, lookups, info["id"])
    records = [task for entity in entities for task in entity.tasks()]

    def status_of(r: TaskRecord) -> str | None:
        return r.raw.get("task_status_id")

    open_records = [r for r in records if not r.is_done(lookups)]
    by_type: dict[str, list[TaskRecord]] = defaultdict(list)
    for r in records:
        by_type[lookups.name("task_types", r.raw.get("task_type_id")) or "?"].append(r)

    progress = []
    for task_type, group in sorted(by_type.items()):
        counts = Counter(lookups.name("task_statuses", status_of(r), "short_name") or "?" for r in group)
        done = sum(r.is_done(lookups) for r in group)
        progress.append(
            TaskTypeProgress(
                task_type=task_type,
                total=len(group),
                done=done,
                done_ratio=_ratio(done, len(group)),
                statuses=[StatusCount(status=s, count=n) for s, n in counts.most_common()],
            )
        )

    done_total = len(records) - len(open_records)
    return ProjectOverview(
        project=info["name"],
        production_type=info.get("production_type"),
        start_date=day(info.get("start_date")),
        end_date=day(info.get("end_date")),
        fps=info.get("fps"),
        resolution=info.get("resolution"),
        assets=sum(e.kind == "asset" for e in entities),
        shots=sum(e.kind == "shot" for e in entities),
        tasks=len(records),
        done_ratio=_ratio(done_total, len(records)),
        overdue=sum(r.is_overdue(lookups) for r in open_records),
        waiting_feedback=sum(lookups.status_flag(status_of(r), "is_feedback_request") for r in open_records),
        retakes=sum(lookups.status_flag(status_of(r), "is_retake") for r in open_records),
        unassigned_open=sum(not r.raw.get("assignees") for r in open_records),
        estimation=sum(r.raw.get("estimation") or 0 for r in records),
        logged=sum(r.raw.get("duration") or 0 for r in records),
        by_task_type=progress,
    )
