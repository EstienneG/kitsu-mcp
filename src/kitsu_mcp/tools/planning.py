"""Producer views: quotas, the production schedule and the budget (the `planning` group, with workload and
timesheet)."""

from collections import defaultdict
from datetime import date
from typing import Literal

from fastmcp.exceptions import ToolError

from kitsu_mcp.kitsu import production
from kitsu_mcp.kitsu.client import get_client
from kitsu_mcp.kitsu.formatters import day
from kitsu_mcp.kitsu.lookups import get_lookups
from kitsu_mcp.kitsu.models import (
    Budget,
    BudgetLine,
    Milestone,
    PersonQuota,
    Quotas,
    Schedule,
    ScheduleSpan,
)
from kitsu_mcp.kitsu.production import project_tasks
from kitsu_mcp.kitsu.validation import iso_date
from kitsu_mcp.server.app import READ_ONLY, tool

PLANNING = {"planning"}
Period = Literal["day", "week", "month"]
# Zou's modes (Kitsu's Quotas page): a shot counts on the day it was first sent for review ("feedback") or
# approved ("done"); the weighted modes spread it over the days time was logged on it instead.
CountMode = Literal["feedback", "done", "weighted", "weighteddone"]


@tool(annotations=READ_ONLY, tags=PLANNING)
def quotas(
    project: str,
    task_type: str,
    period: Period = "week",
    count_mode: CountMode = "done",
    person: str | None = None,
    since: str | None = None,
) -> Quotas:
    """Output per artist for one task type, as Kitsu's Quotas page: shots (and frames, seconds and
    drawings when the shots have them) per day, week or month.

    count_mode: "done" (default) counts a shot on the day it was approved; "feedback" on the day it was
    first sent for review; "weighted" / "weighteddone" spread it (by feedback / approval date) over the days
    time was logged on it, as Kitsu's "weighted" options do. since: YYYY-MM-DD,
    keeps periods from that date on (default: all). person: name, email or ID. Periods are "YYYY-MM-DD"
    (day), "YYYY-WW" (ISO week) or "YYYY-MM" (month); people are sorted by total shots.
    """
    lookups = get_lookups()
    project_id = lookups.project(project)["id"]
    task_type_record = lookups.task_type(task_type)
    person_id = lookups.person(person)["id"] if person else None
    raw = get_client().get(f"data/projects/{project_id}/quotas/{task_type_record['id']}", {"count_mode": count_mode})
    start = _period_key(since, period) if since else None
    rows = []
    for pid, by_period in (raw or {}).items():
        # Zou adds a "total" entry, everyone summed, next to the people.
        if pid == "total" or (person_id and pid != person_id):
            continue
        measures = by_period.get(period) or {}
        shots = _since(measures.get("count") or {}, start)
        if not any(shots.values()):
            continue
        frames = _since(measures.get("frames") or {}, start)
        seconds = _since(measures.get("seconds") or {}, start)
        drawings = _since(measures.get("drawings") or {}, start)
        rows.append(
            PersonQuota(
                person=lookups.person_name(pid) or pid,
                total_shots=round(sum(shots.values()), 2),
                total_frames=sum(frames.values()) or None,
                total_seconds=round(sum(seconds.values()), 2) or None,
                total_drawings=sum(drawings.values()) or None,
                shots={k: round(v, 2) for k, v in sorted(shots.items(), key=lambda kv: _key(kv[0])) if v},
                frames={k: v for k, v in sorted(frames.items(), key=lambda kv: _key(kv[0])) if v} or None,
            )
        )
    rows.sort(key=lambda r: -r.total_shots)
    return Quotas(task_type=task_type_record["name"], period=period, count_mode=count_mode, since=since, people=rows)


def _period_key(value: str, period: Period) -> tuple[int, ...]:
    when = date.fromisoformat(iso_date(value, "since"))
    if period == "day":
        return (when.year, when.month, when.day)
    if period == "month":
        return (when.year, when.month)
    year, week, _ = when.isocalendar()
    return (year, week)


def _key(period_key: str) -> tuple[int, ...]:
    """Zou's period keys as numbers: "2026-10-15", "2026-10", or ISO weeks unpadded ("2026-7", "2026-37")."""
    return tuple(int(part) for part in period_key.split("-"))


def _since(values: dict[str, float], start: tuple[int, ...] | None) -> dict[str, float]:
    return {k: v or 0 for k, v in values.items() if start is None or _key(k) >= start}


@tool(annotations=READ_ONLY, tags=PLANNING)
def production_schedule(project: str, task_types: list[str] | None = None) -> Schedule:
    """A production's planned schedule, as Kitsu's Schedule page: each task type's planned start and end
    (and man-days when set), with the actual first and last due dates of its tasks, plus milestones.

    task_types: names or short names (default: all scheduled). `late` lists task types whose planned end
    has passed while tasks are still open; get one with search_tasks(task_types=[...], overdue=True).
    Task types nobody scheduled in Kitsu are left out (`unscheduled` names those with tasks).
    """
    client = get_client()
    lookups = get_lookups()
    # The full record: the cached project list does not say which task types the project declares.
    info = client.get(f"data/projects/{lookups.project(project)['id']}")
    project_id = info["id"]
    wanted = {lookups.task_type(t)["id"] for t in task_types or []}
    # The project's items as stored: Kitsu's schedule page route (schedule-items/task-types) creates missing
    # items as it reads, and the generic data/schedule-items/ list is for admins only.
    declared = set(info.get("task_types") or [])
    items = [
        i
        for i in client.get(f"data/projects/{project_id}/schedule-items")
        if not i.get("object_id") and i.get("task_type_id") and (not declared or i["task_type_id"] in declared)
    ]
    open_by_type: dict[str, int] = defaultdict(int)
    dues: dict[str, list[str]] = defaultdict(list)
    for record in project_tasks(client, lookups, project_id):
        type_id = record.raw.get("task_type_id") or ""
        if record.is_open(lookups):
            open_by_type[type_id] += 1
        if due := day(record.raw.get("due_date")):
            dues[type_id].append(due)
    now = production.today().isoformat()
    spans = []
    for item in items:
        type_id = item.get("task_type_id")
        if not type_id or (wanted and type_id not in wanted):
            continue
        end = day(item.get("end_date"))
        spans.append(
            ScheduleSpan(
                task_type=lookups.name("task_types", type_id) or type_id,
                start=day(item.get("start_date")),
                end=end,
                man_days=item.get("man_days"),
                open_tasks=open_by_type.get(type_id, 0),
                first_due=min(dues[type_id], default=None),
                last_due=max(dues[type_id], default=None),
                late=bool(end and end < now and open_by_type.get(type_id)),
            )
        )
    spans.sort(key=lambda s: (s.start or "", s.task_type))
    milestones = [
        Milestone(
            date=day(m.get("date")),
            name=m.get("name"),
            task_type=lookups.name("task_types", m.get("task_type_id")),
        )
        for m in client.get(f"data/projects/{project_id}/milestones")
        if not wanted or not m.get("task_type_id") or m.get("task_type_id") in wanted
    ]
    milestones.sort(key=lambda m: m.date or "")
    scheduled = {i["task_type_id"] for i in items}
    unscheduled = sorted(
        lookups.name("task_types", t) or t
        for t in set(dues) | set(open_by_type)
        if t and t not in scheduled and (not wanted or t in wanted) and (not declared or t in declared)
    )
    return Schedule(
        project=info["name"],
        start=day(info.get("start_date")),
        end=day(info.get("end_date")),
        task_types=spans,
        late=[s.task_type for s in spans if s.late],
        unscheduled=unscheduled,
        milestones=milestones,
    )


@tool(annotations=READ_ONLY, tags=PLANNING)
def budget(project: str, budget: str | None = None) -> Budget:
    """A production's planned salary budget, as Kitsu's Budget page: one line per person (department,
    position, seniority, months planned, daily rate, cost), with totals per department and overall.

    budget: name or ID when the project has several versions (default: the latest revision). Costs follow
    Kitsu: a month costs 20 days at the daily rate, unless the budget sets that month's cost apart. Amounts
    are in the budget's currency. Kitsu shows budgets to producers and admins; other roles get its error.
    """
    client = get_client()
    lookups = get_lookups()
    info = lookups.project(project)
    budgets = client.get(f"data/projects/{info['id']}/budgets")
    if not budgets:
        raise ToolError(f"{info['name']} has no budget in Kitsu")
    if budget:
        match = [b for b in budgets if budget == b["id"] or (b.get("name") or "").lower() == budget.lower()]
        if not match:
            names = ", ".join(f"{b.get('name')} (revision {b.get('revision')})" for b in budgets)
            raise ToolError(f"No budget '{budget}' in {info['name']}; it has: {names}")
        chosen = match[0]
    else:
        chosen = max(budgets, key=lambda b: b.get("revision") or 0)
    entries = client.get(f"data/projects/{info['id']}/budgets/{chosen['id']}/entries")
    departments = {i: d["name"] for i, d in lookups.index("departments").items()}
    lines = []
    for e in entries:
        months = e.get("months_duration") or 0
        rate = e.get("daily_salary") or 0
        cost = sum(_month_costs(e).values())
        lines.append(
            BudgetLine(
                person=lookups.person_name(e.get("person_id")),
                department=departments.get(e.get("department_id") or ""),
                position=e.get("position"),
                seniority=e.get("seniority"),
                start=day(e.get("start_date")),
                months=months,
                daily_rate=rate,
                cost=round(cost, 2),
            )
        )
    by_department: dict[str, float] = defaultdict(float)
    for line in lines:
        by_department[line.department or "(none)"] += line.cost
    return Budget(
        project=info["name"],
        name=chosen.get("name"),
        revision=chosen.get("revision"),
        currency=chosen.get("currency"),
        total=round(sum(line.cost for line in lines), 2),
        by_department={k: round(v, 2) for k, v in sorted(by_department.items(), key=lambda kv: -kv[1])},
        lines=sorted(lines, key=lambda line: (line.department or "", line.person or "")),
    )


DAYS_PER_MONTH = 20
"""Kitsu's budget page counts a month as 20 days at the daily rate."""


def _month_costs(entry: dict) -> dict[str, float]:
    """Cost per month (YYYY-MM) over the months an entry covers, as Kitsu's budget page computes it: a
    month's exception (its whole cost, set by hand) wins over the daily rate times 20."""
    start = date.fromisoformat(day(entry.get("start_date")) or "1970-01-01")
    monthly = (entry.get("daily_salary") or 0) * DAYS_PER_MONTH
    exceptions = entry.get("exceptions") or {}
    costs = {}
    for i in range(entry.get("months_duration") or 0):
        year, month = divmod(start.month - 1 + i, 12)
        key = f"{start.year + year}-{month + 1:02d}"
        costs[key] = _number(exceptions.get(key)) or monthly
    return costs


def _number(value) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
