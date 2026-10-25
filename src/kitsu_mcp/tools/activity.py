"""What happened lately: a project's activity feed, the user's notifications, name search, timesheets."""

from collections import Counter, defaultdict
from datetime import date, timedelta

from fastmcp.exceptions import ToolError

from kitsu_mcp import production
from kitsu_mcp.app import READ_ONLY, tool
from kitsu_mcp.client import get_client
from kitsu_mcp.formatters import day
from kitsu_mcp.lookups import get_lookups
from kitsu_mcp.models import (
    Activity,
    ActivityItem,
    DayOff,
    Notification,
    Notifications,
    SearchHit,
    SearchResults,
    Timesheet,
    TimesheetDay,
    TimesheetTask,
)
from kitsu_mcp.validation import Limit, iso_date

_MAX_FEED_PAGES = 5


@tool(annotations=READ_ONLY, tags={"activity"})
def project_activity(
    project: str,
    since: str | None = None,
    task_type: str | None = None,
    person: str | None = None,
    status_changes_only: bool = False,
    entity_name_contains: str | None = None,
    limit: Limit = 50,
) -> Activity:
    """What changed on a project, newest first: comments, status changes and uploads, from Kitsu's activity feed.

    Answers "what happened since yesterday?" or "what did the animators do this week?". since: YYYY-MM-DD
    (default: the last 2 days). task_type: name or short name. person: who made the change (name, email or
    ID). status_changes_only keeps changes that set a new status. `authors` counts changes per person.
    Read a change's comment with get_task(task_id); uploads are also in recent_previews.
    """
    lookups = get_lookups()
    project_id = lookups.project(project)["id"]
    after = iso_date(since, "since") if since else (production.today() - timedelta(days=2)).isoformat()
    params: dict = {"after": after}
    if task_type:
        params["task_type_id"] = lookups.task_type(task_type)["id"]
    author_id = lookups.person(person)["id"] if person else None
    wanted = (entity_name_contains or "").lower()
    items: list[ActivityItem] = []
    total = 0
    # Person, status and name filters apply on our side, so read a few pages of the feed to fill `limit`.
    for page in range(1, _MAX_FEED_PAGES + 1):
        feed = get_client().get(f"data/projects/{project_id}/news", params={**params, "page": page, "limit": 100})
        total = feed.get("total") or total
        for item in feed.get("data") or []:
            if (
                (author_id and item.get("author_id") != author_id)
                or (status_changes_only and not item.get("change"))
                or (wanted and wanted not in (item.get("full_entity_name") or "").lower())
            ):
                continue
            items.append(
                ActivityItem(
                    date=item.get("created_at"),
                    entity=item.get("full_entity_name"),
                    task_id=item.get("task_id"),
                    task_type=lookups.name("task_types", item.get("task_type_id")),
                    status=lookups.name("task_statuses", item.get("task_status_id"), "short_name"),
                    status_changed=bool(item.get("change")),
                    author=lookups.person_name(item.get("author_id")),
                    comment_id=item.get("comment_id"),
                    preview_file_id=item.get("preview_file_id"),
                )
            )
            if len(items) == limit:
                break
        if len(items) == limit or page >= (feed.get("nb_pages") or 1):
            break
    authors = Counter(i.author or "unknown" for i in items)
    return Activity(total=total, authors=dict(authors.most_common()), items=items)


@tool(annotations=READ_ONLY, tags={"activity"})
def my_notifications(unread_only: bool = True, project: str | None = None, limit: Limit = 30) -> Notifications:
    """The logged-in user's Kitsu notifications (their inbox), newest first: comments and replies on their
    tasks, mentions, assignments. unread_only (default) keeps the unread ones. project: name or ID.
    Reading them here does not mark them as read in Kitsu."""
    lookups = get_lookups()
    project_id = lookups.project(project)["id"] if project else None
    raw = get_client().get("data/user/notifications")
    raw = [n for n in raw if not project_id or n.get("project_id") == project_id]
    unread = sum(1 for n in raw if not n.get("read"))
    if unread_only:
        raw = [n for n in raw if not n.get("read")]
    raw.sort(key=lambda n: n.get("created_at") or "", reverse=True)
    return Notifications(
        total=len(raw),
        unread=unread,
        notifications=[
            Notification(
                date=n.get("created_at"),
                type=n.get("notification_type"),
                read=bool(n.get("read")),
                project=n.get("project_name"),
                entity=n.get("full_entity_name"),
                task_id=n.get("task_id"),
                task_type=lookups.name("task_types", n.get("task_type_id")),
                status=lookups.name("task_statuses", n.get("task_status_id"), "short_name"),
                author=lookups.person_name(n.get("author_id")),
                text=n.get("reply_text") or n.get("comment_text") or None,
                comment_id=n.get("comment_id"),
            )
            for n in raw[:limit]
        ],
    )


_SEARCH_KINDS = ("asset", "shot", "sequence", "episode", "edit", "concept", "person")
_PROJECT_ROUTES = (("sequence", "sequences"), ("episode", "episodes"), ("edit", "edits"), ("concept", "concepts"))


@tool(annotations=READ_ONLY, tags={"core"})
def search(query: str, project: str | None = None, kinds: list[str] | None = None, limit: Limit = 30) -> SearchResults:
    """Find anything by name: assets, shots, sequences, episodes, edits, concepts and people.

    query: part of the name (case-insensitive). project: name or ID (default: every open project; people
    are studio-wide). kinds: limit to some of asset, shot, sequence, episode, edit, concept, person.
    Use the IDs with get_asset, get_shot, get_casting or search_tasks.
    """
    wanted = query.strip().lower()
    if not wanted:
        raise ToolError("query is empty")
    unknown = set(kinds or []) - set(_SEARCH_KINDS)
    if unknown:
        raise ToolError(f"Unknown kinds {sorted(unknown)}; use some of {', '.join(_SEARCH_KINDS)}")
    selected = set(kinds or _SEARCH_KINDS)
    lookups = get_lookups()
    client = get_client()
    projects = [lookups.project(project)] if project else client.get("data/projects/open")
    asset_types = {i: t["name"] for i, t in lookups.index("asset_types").items()}
    hits: list[SearchHit] = []

    def add(kind: str, record: dict, project_name: str | None, detail: str | None = None, label: str = "") -> None:
        if wanted in (record.get("name") or "").lower() and not record.get("canceled"):
            name = label or record["name"]
            hits.append(SearchHit(kind=kind, id=record["id"], name=name, project=project_name, detail=detail))

    for p in projects:
        params = {"project_id": p["id"]}
        if "asset" in selected:
            for a in client.get("data/assets", params=params):
                add("asset", a, p["name"], asset_types.get(a.get("entity_type_id")))
        if "shot" in selected:
            for s in client.get("data/shots", params=params):
                # Shot names repeat across sequences: name them as Kitsu does, "SQ010 / SH010".
                sequence = s.get("sequence_name") if s.get("sequence_name") not in (None, "", "None") else None
                add("shot", s, p["name"], sequence, f"{sequence} / {s['name']}" if sequence else s["name"])
        for kind, route in (
            ("sequence", "sequences"),
            ("episode", "episodes"),
            ("edit", "edits"),
            ("concept", "concepts"),
        ):
            if kind in selected:
                for record in client.get(f"data/projects/{p['id']}/{route}"):
                    add(kind, record, p["name"])
    if "person" in selected:
        for person in lookups.index("people").values():
            if not person.get("is_bot") and wanted in (person.get("full_name") or "").lower():
                hits.append(
                    SearchHit(kind="person", id=person["id"], name=person["full_name"], detail=person.get("role"))
                )

    # Exact and prefix matches first, then by name.
    def rank(hit: SearchHit) -> tuple:
        name = hit.name.rsplit(" / ", 1)[-1].lower()
        return (name != wanted, not name.startswith(wanted), hit.name.lower())

    hits.sort(key=rank)
    return SearchResults(total=len(hits), hits=hits[:limit])


@tool(annotations=READ_ONLY, tags={"planning"})
def timesheet(person: str | None = None, start: str | None = None, end: str | None = None) -> Timesheet:
    """Time a person logged over a period, in minutes: per day and per task, with their days off.

    person: name, email or ID (default: the logged-in user). start / end: YYYY-MM-DD (default: the last 7
    days, today included). For time logged on a single task, see get_task (duration).
    """
    lookups = get_lookups()
    client = get_client()
    record = lookups.person(person) if person else None
    person_id = record["id"] if record else client.user_id()
    end_day = iso_date(end, "end") if end else production.today().isoformat()
    start_day = iso_date(start, "start") if start else (date.fromisoformat(end_day) - timedelta(days=6)).isoformat()
    if start_day > end_day:
        raise ToolError(f"start ({start_day}) is after end ({end_day})")
    entries = client.get(f"data/persons/{person_id}/time-spents", params={"start_date": start_day, "end_date": end_day})
    by_day: dict[str, float] = defaultdict(float)
    by_task: dict[str, float] = defaultdict(float)
    for entry in entries:
        by_day[day(entry.get("date")) or "?"] += entry.get("duration") or 0
        by_task[entry["task_id"]] += entry.get("duration") or 0
    tasks = []
    for task_id, minutes in sorted(by_task.items(), key=lambda kv: -kv[1]):
        task = client.get(f"data/tasks/{task_id}/full")
        tasks.append(
            TimesheetTask(
                task_id=task_id,
                project=(task.get("project") or {}).get("name"),
                entity=(task.get("entity") or {}).get("name"),
                task_type=(task.get("task_type") or {}).get("name"),
                minutes=minutes,
            )
        )
    days_off = [
        DayOff(start=day(d.get("date")), end=day(d.get("end_date")), description=d.get("description") or None)
        for d in client.get(f"data/persons/{person_id}/day-offs")
        if (day(d.get("date")) or "") <= end_day and (day(d.get("end_date") or d.get("date")) or "") >= start_day
    ]
    return Timesheet(
        person=lookups.person_name(person_id),
        start=start_day,
        end=end_day,
        total_minutes=sum(by_day.values()),
        by_day=[TimesheetDay(date=d, minutes=m) for d, m in sorted(by_day.items())],
        by_task=tasks,
        days_off=sorted(days_off, key=lambda d: d.start or ""),
    )
