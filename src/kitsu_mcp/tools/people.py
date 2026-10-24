from collections import defaultdict

from kitsu_mcp.app import READ_ONLY, mcp
from kitsu_mcp.client import get_client
from kitsu_mcp.lookups import get_lookups
from kitsu_mcp.models import Person, PersonTask, Workload
from kitsu_mcp.production import day, project_tasks
from kitsu_mcp.validation import Limit


def _person(p: dict, departments: dict[str, str], with_email: bool) -> Person:
    return Person(
        id=p["id"],
        full_name=p.get("full_name"),
        email=p.get("email") if with_email else None,
        role=p.get("role"),
        position=p.get("position"),
        departments=[departments.get(d) or d for d in p.get("departments") or []],
    )


@mcp.tool(annotations=READ_ONLY, tags={"people"})
def list_people(
    project: str | None = None, include_inactive: bool = False, include_email: bool = False
) -> list[Person]:
    """List people: the whole studio, or a project's team (project name or ID).

    Bots are left out; inactive accounts only with include_inactive. Emails are left out unless
    include_email=True (tools that take a person accept their name).
    """
    client = get_client()
    lookups = get_lookups()
    if project:
        people = client.get(f"data/projects/{lookups.project(project)['id']}/team")
    else:
        people = list(lookups.index("people").values())
    departments = {d["id"]: d["name"] for d in client.get("data/departments")}
    return sorted(
        (
            _person(p, departments, include_email)
            for p in people
            if not p.get("is_bot") and (include_inactive or p.get("active", True))
        ),
        key=lambda p: (p.full_name or "").lower(),
    )


@mcp.tool(annotations=READ_ONLY, tags={"people", "tasks"})
def get_person_tasks(
    person: str, done: bool = False, project: str | None = None, limit: Limit = 50
) -> list[PersonTask]:
    """List the tasks assigned to a person (name, email or ID): open ones, or done ones with done=True.

    Open tasks are sorted by due date; done tasks most recent first. At most `limit` (default 50).
    """
    lookups = get_lookups()
    person_id = lookups.person(person)["id"]
    project_id = lookups.project(project)["id"] if project else None
    route = "done-tasks" if done else "tasks"
    tasks = [
        PersonTask(
            id=t["id"],
            project=t.get("project_name"),
            entity=t.get("entity_name"),
            entity_type=t.get("entity_type_name"),
            sequence=t.get("sequence_name"),
            task_type=t.get("task_type_name"),
            status=t.get("task_status_short_name"),
            due_date=day(t.get("due_date")),
            estimation=t.get("estimation"),
            duration=t.get("duration"),
            last_comment_date=t.get("last_comment_date"),
        )
        for t in get_client().get(f"data/persons/{person_id}/{route}")
        if project_id is None or t.get("project_id") == project_id
    ]
    if done:
        tasks.sort(key=lambda t: t.last_comment_date or "", reverse=True)
    else:
        tasks.sort(key=lambda t: (t.due_date is None, t.due_date or "", t.entity or ""))
    return tasks[:limit]


@mcp.tool(annotations=READ_ONLY, tags={"people", "tasks", "reporting"})
def workload(project: str, task_types: list[str] | None = None) -> list[Workload]:
    """Open (not done) tasks per person on a project: counts, overdue, waiting feedback, estimate vs. logged.

    Sorted by number of open tasks. Unassigned open tasks are reported as person "(unassigned)".
    """
    lookups = get_lookups()
    project_id = lookups.project(project)["id"]
    type_ids = {lookups.task_type(t)["id"] for t in task_types or []}
    by_person: dict[str | None, list] = defaultdict(list)
    for record in project_tasks(get_client(), lookups, project_id):
        if record.is_done(lookups) or (type_ids and record.raw.get("task_type_id") not in type_ids):
            continue
        for person_id in record.raw.get("assignees") or [None]:
            by_person[person_id].append(record)

    rows = []
    for person_id, records in by_person.items():
        dues = sorted(d for r in records if (d := day(r.raw.get("due_date"))))
        status_ids = [r.raw.get("task_status_id") for r in records]
        rows.append(
            Workload(
                person=lookups.person_name(person_id) or "(unassigned)",
                open_tasks=len(records),
                overdue=sum(r.is_overdue(lookups) for r in records),
                waiting_feedback=sum(lookups.status_flag(s, "is_feedback_request") for s in status_ids),
                retakes=sum(lookups.status_flag(s, "is_retake") for s in status_ids),
                estimation=sum(r.raw.get("estimation") or 0 for r in records),
                logged=sum(r.raw.get("duration") or 0 for r in records),
                next_due=dues[0] if dues else None,
            )
        )
    return sorted(rows, key=lambda w: (-w.open_tasks, w.person))
