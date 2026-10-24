from collections import Counter, defaultdict

from fastmcp.exceptions import ToolError

from kitsu_mcp.app import READ_ONLY, tool
from kitsu_mcp.client import get_client
from kitsu_mcp.lookups import get_lookups
from kitsu_mcp.models import (
    Named,
    Project,
    ProjectOverview,
    StatusCount,
    TaskStatus,
    TaskStatuses,
    TaskType,
    TaskTypeProgress,
)
from kitsu_mcp.production import TaskRecord, day, project_entities, project_tasks


@tool(annotations=READ_ONLY, tags={"projects"})
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


@tool(annotations=READ_ONLY, tags={"projects"})
def list_task_types(project: str | None = None) -> list[TaskType]:
    """List task types (Modelling, Animation, ...) with the entity kind they apply to.

    project (name or ID): only the task types that production declares or has tasks of; otherwise the
    whole studio's.
    """
    lookups = get_lookups()
    used: set[str] | None = None
    if project:
        client = get_client()
        project_id = lookups.project(project)["id"]
        # A project's declared list can miss types it has tasks of, so add those.
        used = set(client.get(f"data/projects/{project_id}").get("task_types") or [])
        used |= {tt for t in project_tasks(client, lookups, project_id) if (tt := t.raw.get("task_type_id"))}
    return [
        TaskType(id=t["id"], name=t["name"], short_name=t.get("short_name"), for_entity=t.get("for_entity"))
        for t in lookups.index("task_types").values()
        if not t.get("archived") and (used is None or t["id"] in used)
    ]


@tool(annotations=READ_ONLY, tags={"projects"})
def list_task_statuses() -> TaskStatuses:
    """List task statuses with their short names (wip, wfa, done, ...), Kitsu flags and role.

    The role is what the other tools count a status as: omitted, done, on_hold, retake, waiting_review,
    wip or todo. It comes from the KITSU_*_STATUSES settings when a status is listed there (role_source
    names the setting), else from Kitsu's flags. unmatched_settings lists configured names that match no
    status.
    """
    lookups = get_lookups()
    statuses = []
    for s in lookups.index("task_statuses").values():
        if s.get("archived"):
            continue
        role, source = lookups.role_and_source(s["id"])
        statuses.append(
            TaskStatus(
                id=s["id"],
                name=s["name"],
                short_name=s["short_name"],
                role=role,
                role_source=source,
                is_done=s.get("is_done"),
                is_wip=s.get("is_wip"),
                is_retake=s.get("is_retake"),
                is_feedback_request=s.get("is_feedback_request"),
            )
        )
    return TaskStatuses(statuses=statuses, unmatched_settings=lookups.unmatched_role_names())


@tool(annotations=READ_ONLY, tags={"projects", "assets"})
def list_asset_types(project: str) -> list[Named]:
    """List asset types used in a project (name or ID)."""
    project_id = get_lookups().project(project)["id"]
    return [Named(id=t["id"], name=t["name"]) for t in get_client().get(f"data/projects/{project_id}/asset-types")]


def _number(value) -> float | None:
    """Zou stores fps as text ("23", "23.976")."""
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _status_names(records: list[TaskRecord], lookups) -> list[str]:
    """Distinct status short names of some tasks, for showing what a count was made of."""
    return sorted({lookups.name("task_statuses", r.raw.get("task_status_id"), "short_name") or "?" for r in records})


def _ratio(part: int, total: int) -> float:
    return round(part / total, 3) if total else 0.0


@tool(annotations=READ_ONLY, tags={"projects", "reporting"})
def project_overview(
    project: str,
    task_types: list[str] | None = None,
    exclude_task_types: list[str] | None = None,
    departments: list[str] | None = None,
) -> ProjectOverview:
    """Where a production stands: entity and task counts, completion per task type, overdue tasks,
    tasks waiting for review, retakes, on hold, unassigned work and time logged vs. estimated.

    Counts follow each status's role (list_task_statuses shows them). Omitted tasks (OMIT, N/A, ...)
    are counted apart and left out of done_ratio, so dropped work does not inflate progress.
    done_improvable counts tasks whose status is done by role but not flagged done in Kitsu (statuses
    the studio set as done, such as a "could be better" status), with those statuses.
    task_types / exclude_task_types (names or short names) limit the task counts and ratios, e.g.
    exclude_task_types=["Animatic"] to leave admin or pre-production work out of progress. departments
    (names or IDs) keeps tasks whose task type belongs to one of them, as in search_tasks and workload.
    Entity counts (assets, shots) are unaffected by these filters."""
    client = get_client()
    lookups = get_lookups()
    info = client.get(f"data/projects/{lookups.project(project)['id']}")
    keep = {lookups.task_type(t)["id"] for t in task_types or []}
    drop = {lookups.task_type(t)["id"] for t in exclude_task_types or []}
    if keep and keep <= drop:
        raise ToolError("task_types and exclude_task_types cancel out: nothing would be counted")
    department_types = lookups.department_task_types(departments)
    entities = project_entities(client, lookups, info["id"])
    records = [
        task
        for entity in entities
        for task in entity.tasks()
        if (not keep or task.raw.get("task_type_id") in keep)
        and task.raw.get("task_type_id") not in drop
        and (department_types is None or task.raw.get("task_type_id") in department_types)
    ]

    def status_of(r: TaskRecord) -> str | None:
        return r.raw.get("task_status_id")

    roles = {id(r): r.role(lookups) for r in records}
    omitted = [r for r in records if roles[id(r)] == "omitted"]
    done_records = [r for r in records if roles[id(r)] == "done"]
    open_records = [r for r in records if r.is_open(lookups)]
    # Done by role but not by Kitsu's own flag: finished, could still be improved (e.g. a "could be better").
    kitsu_done = {i for i, s in lookups.index("task_statuses").items() if s.get("is_done")}
    improvable = [r for r in done_records if status_of(r) not in kitsu_done]
    by_type: dict[str, list[TaskRecord]] = defaultdict(list)
    for r in records:
        by_type[lookups.name("task_types", r.raw.get("task_type_id")) or "?"].append(r)

    progress = []
    for task_type, group in sorted(by_type.items()):
        counts = Counter(lookups.name("task_statuses", status_of(r), "short_name") or "?" for r in group)
        dropped = sum(roles[id(r)] == "omitted" for r in group)
        done = sum(roles[id(r)] == "done" for r in group)
        progress.append(
            TaskTypeProgress(
                task_type=task_type,
                total=len(group),
                done=done,
                omitted=dropped,
                done_ratio=_ratio(done, len(group) - dropped),
                statuses=[StatusCount(status=s, count=n) for s, n in counts.most_common()],
            )
        )

    return ProjectOverview(
        project=info["name"],
        production_type=info.get("production_type"),
        start_date=day(info.get("start_date")),
        end_date=day(info.get("end_date")),
        fps=_number(info.get("fps")),
        resolution=info.get("resolution"),
        assets=sum(e.kind == "asset" for e in entities),
        shots=sum(e.kind == "shot" for e in entities),
        tasks=len(records),
        omitted=len(omitted),
        omitted_statuses=_status_names(omitted, lookups),
        done_ratio=_ratio(len(done_records), len(records) - len(omitted)),
        done_improvable=len(improvable),
        done_improvable_statuses=_status_names(improvable, lookups),
        overdue=sum(r.is_overdue(lookups) for r in open_records),
        waiting_feedback=sum(roles[id(r)] == "waiting_review" for r in open_records),
        retakes=sum(roles[id(r)] == "retake" for r in open_records),
        on_hold=sum(roles[id(r)] == "on_hold" for r in open_records),
        unassigned_open=sum(not r.raw.get("assignees") for r in open_records),
        estimation=sum(r.raw.get("estimation") or 0 for r in records),
        logged=sum(r.raw.get("duration") or 0 for r in records),
        by_task_type=progress,
    )
