from collections import defaultdict

from kitsu_mcp.app import READ_ONLY, tool
from kitsu_mcp.client import get_client
from kitsu_mcp.lookups import get_lookups
from kitsu_mcp.models import PeopleList, Person, PersonTask, PersonTaskBrief, PersonTaskList, Workload
from kitsu_mcp.production import assigned_tasks, day, project_tasks
from kitsu_mcp.validation import Detail, Limit, Offset


def _person(p: dict, departments: dict[str, str], with_email: bool) -> Person:
    return Person(
        id=p["id"],
        full_name=p.get("full_name"),
        email=p.get("email") if with_email else None,
        role=p.get("role"),
        position=p.get("position"),
        departments=[departments.get(d) or d for d in p.get("departments") or []],
    )


@tool(annotations=READ_ONLY, tags={"people"})
def list_people(
    project: str | None = None,
    include_inactive: bool = False,
    include_email: bool = False,
    limit: Limit = 100,
    offset: Offset = 0,
) -> PeopleList:
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
    departments = {i: d["name"] for i, d in lookups.index("departments").items()}
    found = sorted(
        (
            _person(p, departments, include_email)
            for p in people
            if not p.get("is_bot") and (include_inactive or p.get("active", True))
        ),
        key=lambda p: (p.full_name or "").lower(),
    )
    return PeopleList(total=len(found), people=found[offset : offset + limit])


@tool(annotations=READ_ONLY, tags={"people", "tasks"})
def get_person_tasks(
    person: str | None = None,
    done: bool = False,
    project: str | None = None,
    detail: Detail = "compact",
    limit: Limit = 50,
    offset: Offset = 0,
) -> PersonTaskList:
    """List the tasks assigned to a person (name, email or ID; default: the logged-in user, i.e. "my tasks"):
    open ones, or done ones with done=True.

    Open and done follow the status roles (list_task_statuses), like workload and project_overview:
    omitted tasks are in neither list. Open tasks are sorted by due date; done tasks most
    recent first. `total` counts all of them; limit/offset page through. detail="compact" (default)
    leaves out sequence, estimate, time logged and last comment date; detail="full" includes them.
    """
    lookups = get_lookups()
    client = get_client()
    person_id = lookups.person(person)["id"] if person else client.user_id()
    project_id = lookups.project(project)["id"] if project else None
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
        for t in assigned_tasks(client, lookups, person_id, done)
        if project_id is None or t.get("project_id") == project_id
    ]
    if done:
        tasks.sort(key=lambda t: t.last_comment_date or "", reverse=True)
    else:
        tasks.sort(key=lambda t: (t.due_date is None, t.due_date or "", t.entity or ""))
    page = tasks[offset : offset + limit]
    rows: list[PersonTask | PersonTaskBrief] = (
        [PersonTaskBrief(**t.model_dump(include=set(PersonTaskBrief.model_fields))) for t in page]
        if detail == "compact"
        else list(page)
    )
    return PersonTaskList(total=len(tasks), tasks=rows)


@tool(annotations=READ_ONLY, tags={"people", "tasks", "reporting"})
def workload(project: str, task_types: list[str] | None = None, departments: list[str] | None = None) -> list[Workload]:
    """Open tasks per person on a project: counts, overdue, waiting for review, retakes, on hold,
    estimate vs. logged.

    Open = not done and not omitted (status roles: see list_task_statuses); on-hold tasks are open but
    never overdue. Sorted by number of open tasks. Unassigned open tasks are reported as "(unassigned)".
    task_types: names or short names. departments: names or IDs; counts only tasks whose task type belongs to
    one of them (the same filter as search_tasks and project_overview).
    """
    lookups = get_lookups()
    project_id = lookups.project(project)["id"]
    type_ids = {lookups.task_type(t)["id"] for t in task_types or []}
    department_types = lookups.department_task_types(departments)
    by_person: dict[str | None, list] = defaultdict(list)
    for record in project_tasks(get_client(), lookups, project_id):
        type_id = record.raw.get("task_type_id")
        if not record.is_open(lookups) or (type_ids and type_id not in type_ids):
            continue
        if department_types is not None and type_id not in department_types:
            continue
        for person_id in record.raw.get("assignees") or [None]:
            by_person[person_id].append(record)

    rows = []
    for person_id, records in by_person.items():
        dues = sorted(d for r in records if (d := day(r.raw.get("due_date"))))
        roles = [r.role(lookups) for r in records]
        rows.append(
            Workload(
                person=lookups.person_name(person_id) or "(unassigned)",
                open_tasks=len(records),
                overdue=sum(r.is_overdue(lookups) for r in records),
                waiting_feedback=roles.count("waiting_review"),
                retakes=roles.count("retake"),
                on_hold=roles.count("on_hold"),
                estimation=sum(r.raw.get("estimation") or 0 for r in records),
                logged=sum(r.raw.get("duration") or 0 for r in records),
                next_due=dues[0] if dues else None,
            )
        )
    return sorted(rows, key=lambda w: (-w.open_tasks, w.person))
