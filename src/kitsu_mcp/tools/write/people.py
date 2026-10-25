"""People and the studio: accounts and departments, days off, playlists, the user's notifications, and setting
or deleting time logs.

Checked on a throwaway Zou: person and day-off updates keep what they leave out; a playlist's entries are its
`shots` list, which a PUT replaces whole (so removing one entry sends the others back); inviting a person is a
GET that sends an email; and Zou takes time logged only by someone assigned to the task, whatever their role.
"""

from datetime import date
from typing import Any, Literal

from fastmcp.exceptions import ToolError

from kitsu_mcp.kitsu.client import get_client
from kitsu_mcp.kitsu.lookups import get_lookups
from kitsu_mcp.kitsu.models import DryRunResult, EntityWriteResult
from kitsu_mcp.kitsu.plans import Plan, current_user
from kitsu_mcp.kitsu.validation import iso_date, object_id
from kitsu_mcp.server.app import tool
from kitsu_mcp.tools.write.common import (
    ADDITIVE,
    MANAGE,
    WRITE,
    assignees_of,
    fetch_task_full,
    require_confirm,
    send_entity_write,
    task_label,
)

ADMIN = WRITE | {"admin"}
Result = EntityWriteResult | DryRunResult
Role = Literal["user", "supervisor", "manager", "admin", "client", "vendor"]


def _done(plan: Plan, dry_run: bool, reload=None) -> Result:
    result = send_entity_write(plan, dry_run, reload=reload)
    if not dry_run:
        get_lookups().clear()  # people and departments are cached
    return result


@tool(annotations=MANAGE, tags=ADMIN)
def manage_person(
    action: Literal["create", "update", "deactivate", "reactivate", "invite", "add_department", "remove_department"],
    person: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    email: str | None = None,
    role: Role | None = None,
    position: str | None = None,
    department: str | None = None,
    dry_run: bool = False,
) -> Result:
    """Manage studio accounts: create one, update it, deactivate or reactivate it, send the invitation email,
    or add / remove a department.

    create: first_name, last_name, email; optional role (user = artist, the default; supervisor, manager,
    admin, client, vendor), position and department. update: person (name, email or ID) and what changes.
    invite: emails the person a link to set their password. Kitsu lets only admins manage accounts.
    Deactivating keeps the person's tasks and history. dry_run=True: show the plan without writing; show it to
    the user first.
    """
    lookups = get_lookups()
    plan = Plan("manage_person", would="")
    if current_user().get("role") != "admin":
        plan.fail("Kitsu lets only admins manage accounts; ask an admin.")
    if action == "create":
        if not (first_name and last_name and email):
            raise ToolError("create needs first_name, last_name and email")
        if any((p.get("email") or "").lower() == email.strip().lower() for p in lookups.index("people").values()):
            raise ToolError(f"An account already uses {email}")
        payload: dict[str, Any] = {
            "first_name": first_name.strip(),
            "last_name": last_name.strip(),
            "email": email.strip(),
            "role": role or "user",
            "active": True,
            "departments": [],
        }
        if position:
            payload["position"] = position
        if department:
            payload["departments"] = [lookups.resolve("departments", department)["id"]]
        plan.request("POST", "data/persons", payload)
        plan.would = f"Create {payload['role']} account {first_name} {last_name} <{email}>"
        plan.message = "Account created; use action='invite' to email them a link to set their password."
        plan.after = {k: v for k, v in payload.items() if k != "departments"}
        return _done(plan, dry_run)
    if not person:
        raise ToolError(f"{action} needs person")
    record = lookups.person(person)
    name = record.get("full_name") or record["id"]
    if action == "update":
        changes = {"first_name": first_name, "last_name": last_name, "email": email, "role": role, "position": position}
        changes = {k: v for k, v in changes.items() if v is not None and v != record.get(k)}
        if not changes:
            raise ToolError("Nothing to update: pass first_name, last_name, email, role or position")
        plan.request("PUT", f"data/persons/{record['id']}", changes)
        plan.would, plan.message = f"Update {name}: {', '.join(changes)}", f"Updated {name}."
        plan.before, plan.after = {k: record.get(k) for k in changes}, changes
        if "role" in changes:
            plan.warnings.append(f"Changes what {name} may see and do in Kitsu ({record.get('role')} -> {role}).")
    elif action in ("deactivate", "reactivate"):
        active = action == "reactivate"
        if bool(record.get("active", True)) == active:
            raise ToolError(f"{name} is already {'active' if active else 'inactive'}")
        plan.request("PUT", f"data/persons/{record['id']}", {"active": active})
        plan.would = f"{action.capitalize()} {name}"
        plan.message = f"{name} is now {'active' if active else 'inactive'}."
        plan.before, plan.after = {"active": not active}, {"active": active}
        if not active:
            plan.warnings.append(f"{name} can no longer log in; their tasks and history stay.")
    elif action == "invite":
        # Zou sends the email on a GET: never put this behind a read-only path.
        plan.request("POST", f"actions/persons/{record['id']}/invite")
        plan.would = f"Email {name} <{record.get('email')}> an invitation to set their password"
        plan.message = f"Invitation sent to {record.get('email')}."
        plan.warnings.append("This sends a real email.")
    else:
        if not department:
            raise ToolError(f"{action} needs department")
        dep = lookups.resolve("departments", department)
        current = record.get("departments") or []
        if action == "add_department":
            if dep["id"] in current:
                raise ToolError(f"{name} is already in {dep['name']}")
            plan.request("POST", f"actions/persons/{record['id']}/departments/add", {"department_id": dep["id"]})
        else:
            if dep["id"] not in current:
                raise ToolError(f"{name} is not in {dep['name']}")
            plan.request("DELETE", f"actions/persons/{record['id']}/departments/{dep['id']}")
        verb = "Add" if action == "add_department" else "Remove"
        plan.would = f"{verb} {name} {'to' if verb == 'Add' else 'from'} {dep['name']}"
        plan.message = f"{name}: department {dep['name']} {'added' if verb == 'Add' else 'removed'}."
    return _done(plan, dry_run)


@tool(annotations=MANAGE, tags=ADMIN)
def manage_day_off(
    action: Literal["add", "update", "delete"],
    person: str | None = None,
    start: str | None = None,
    end: str | None = None,
    description: str | None = None,
    day_off_id: str | None = None,
    confirm: bool = False,
    dry_run: bool = False,
) -> Result:
    """Add, change or delete days off (a holiday, sick leave). add: person (default: the logged-in user),
    start (YYYY-MM-DD), optional end (default: start) and description. update / delete: day_off_id (timesheet
    lists a person's days off) and what changes. delete needs confirm=True. dry_run=True: show the plan without
    writing; show it to the user first.
    """
    lookups = get_lookups()
    client = get_client()
    require_confirm(action, confirm, dry_run, "days off")
    plan = Plan("manage_day_off", would="")
    if action == "add":
        if not start:
            raise ToolError("add needs start")
        who = lookups.person(person) if person else current_user()
        first = iso_date(start, "start")
        last = iso_date(end, "end") if end else first
        if first > last:
            raise ToolError("start is after end")
        overlap = [
            d
            for d in client.get(f"data/persons/{who['id']}/day-offs") or []
            if str(d.get("date"))[:10] <= last and str(d.get("end_date") or d.get("date"))[:10] >= first
        ]
        payload: dict[str, Any] = {"person_id": who["id"], "date": first, "end_date": last}
        if description:
            payload["description"] = description
        plan.request("POST", "data/day-offs", payload)
        plan.would = f"Add days off for {who.get('full_name')}: {first}" + (f" to {last}" if last != first else "")
        plan.message = "Days off added."
        plan.after = payload
        if overlap:
            plan.warnings.append(f"Overlaps {len(overlap)} day(s) off already set.")
        if who["id"] != current_user()["id"] and current_user().get("role") not in ("admin", "manager", "supervisor"):
            plan.warnings.append("Kitsu may refuse: your role usually cannot set someone else's days off.")
        return send_entity_write(plan, dry_run)
    if not day_off_id:
        raise ToolError(f"{action} needs day_off_id (timesheet lists days off)")
    day_off_id = object_id(day_off_id, "day off", "timesheet")
    if action == "delete":
        plan.request("DELETE", f"data/day-offs/{day_off_id}")
        plan.would, plan.message = "Delete these days off", "Days off deleted."
    else:
        changes = {
            k: v
            for k, v in (
                ("date", iso_date(start, "start") if start else None),
                ("end_date", iso_date(end, "end") if end else None),
                ("description", description),
            )
            if v is not None
        }
        if not changes:
            raise ToolError("Nothing to update: pass start, end or description")
        plan.request("PUT", f"data/day-offs/{day_off_id}", changes)
        plan.would, plan.message = f"Update days off: {', '.join(changes)}", "Days off updated."
        plan.after = changes
    return send_entity_write(plan, dry_run, reload=lambda _: None)


@tool(annotations=MANAGE, tags=WRITE)
def manage_playlist(
    playlist_id: str,
    action: Literal["rename", "remove_entry", "set_preview", "delete"],
    name: str | None = None,
    entity_id: str | None = None,
    preview_file_id: str | None = None,
    confirm: bool = False,
    dry_run: bool = False,
) -> Result:
    """Change a review playlist: rename it, take an entity out of it, choose which preview an entry shows
    (preview_file_id, e.g. an earlier revision from get_task(include_previews=True)), or delete it (needs
    confirm=True). Add entries with add_to_playlist. dry_run=True: show the plan without writing; show it to
    the user first.
    """
    client = get_client()
    playlist_id = object_id(playlist_id, "playlist", "list_playlists")
    require_confirm(action, confirm, dry_run, "a playlist")
    playlist = client.get(f"data/playlists/{playlist_id}")
    label = f"playlist '{playlist.get('name')}'"
    entries = playlist.get("shots") or []
    plan = Plan("manage_playlist", would="")
    if action == "rename":
        if not (name and name.strip()):
            raise ToolError("rename needs name")
        plan.request("PUT", f"data/playlists/{playlist_id}", {"name": name.strip()})
        plan.would, plan.message = f"Rename {label} to '{name.strip()}'", "Playlist renamed."
        plan.before, plan.after = {"name": playlist.get("name")}, {"name": name.strip()}
    elif action == "delete":
        plan.request("DELETE", f"data/playlists/{playlist_id}")
        plan.would, plan.message = f"Delete {label} ({len(entries)} entries)", "Playlist deleted."
    else:
        if not entity_id:
            raise ToolError(f"{action} needs entity_id")
        if not any(e.get("entity_id") == entity_id for e in entries):
            raise ToolError(f"That entity is not in {label} (get_playlist lists its entries)")
        # Zou replaces the whole entry list on a PUT: send it back with the one change.
        if action == "remove_entry":
            new = [e for e in entries if e.get("entity_id") != entity_id]
            plan.would, plan.message = f"Take an entry out of {label}", "Entry removed."
        else:
            if not preview_file_id:
                raise ToolError("set_preview needs preview_file_id")
            preview = client.get(f"data/preview-files/{object_id(preview_file_id, 'preview file', 'get_task')}")
            new = [{**e, "preview_file_id": preview["id"]} if e.get("entity_id") == entity_id else e for e in entries]
            plan.would = f"Show revision {preview.get('revision')} for that entry of {label}"
            plan.message = "Entry preview changed."
        plan.request("PUT", f"data/playlists/{playlist_id}", {"shots": new})
        plan.before, plan.after = {"entries": len(entries)}, {"entries": len(new)}
    return send_entity_write(plan, dry_run, reload=lambda _: None)


@tool(annotations=ADDITIVE, tags=WRITE)
def manage_my_notifications(
    action: Literal["mark_all_read", "subscribe", "unsubscribe"],
    task_id: str | None = None,
    dry_run: bool = False,
) -> Result:
    """The logged-in user's notifications: mark them all read, or subscribe to a task (get notified of its
    comments and status changes even when not assigned) and unsubscribe. dry_run=True: show the plan without
    writing.
    """
    plan = Plan("manage_my_notifications", would="")
    if action == "mark_all_read":
        unread = sum(1 for n in get_client().get("data/user/notifications") or [] if not n.get("read"))
        plan.request("POST", "actions/user/notifications/mark-all-as-read", {})
        plan.would, plan.message = f"Mark {unread} unread notification(s) as read", "Notifications marked read."
        plan.before, plan.after = {"unread": unread}, {"unread": 0}
    else:
        if not task_id:
            raise ToolError(f"{action} needs task_id")
        task = fetch_task_full(object_id(task_id, "task", "search_tasks"))
        if action == "subscribe":
            plan.request("POST", f"actions/user/tasks/{task['id']}/subscribe", {})
        else:
            plan.request("DELETE", f"actions/user/tasks/{task['id']}/unsubscribe")
        plan.would = f"{action.capitalize()} {'to' if action == 'subscribe' else 'from'} {task_label(task)}"
        plan.message = f"{'Subscribed to' if action == 'subscribe' else 'Unsubscribed from'} {task_label(task)}."
    return send_entity_write(plan, dry_run, reload=lambda _: None)


@tool(annotations=MANAGE, tags=WRITE)
def manage_time(
    action: Literal["set", "delete"],
    task_id: str,
    day: str,
    minutes: int | None = None,
    person: str | None = None,
    confirm: bool = False,
    dry_run: bool = False,
) -> Result:
    """Correct time logged on a task for one day: set it to exactly `minutes` (log_time adds), or delete it
    (needs confirm=True). day: YYYY-MM-DD. person: default the logged-in user. Kitsu only takes time logged by
    someone assigned to the task. dry_run=True: show the time before / after without writing; show it to the
    user first.
    """
    lookups = get_lookups()
    client = get_client()
    require_confirm(action, confirm, dry_run, "logged time")
    task = fetch_task_full(object_id(task_id, "task", "search_tasks"))
    who = lookups.person(person) if person else current_user()
    name = who.get("full_name") or who["id"]
    when = iso_date(day, "day")
    entries = client.get(f"actions/tasks/{task['id']}/time-spents").get(who["id"]) or []
    logged = sum(e.get("duration") or 0 for e in entries if isinstance(e, dict) and str(e.get("date"))[:10] == when)
    plan = Plan("manage_time", would="")
    route = f"actions/tasks/{task['id']}/time-spents/{when}/persons/{who['id']}"
    if action == "set":
        if minutes is None or not 0 < minutes <= 24 * 60:
            raise ToolError("set needs minutes between 1 and 1440 (use action='delete' to clear the day)")
        plan.request("POST", route, {"duration": minutes})
        plan.would = f"Set {name}'s time on {task_label(task)} on {when} to {minutes} min (was {logged:g})"
        plan.message = f"Time set to {minutes} min."
        plan.before, plan.after = {"minutes": logged}, {"minutes": minutes}
    else:
        if not logged:
            raise ToolError(f"{name} has no time logged on that task on {when}")
        plan.request("DELETE", route)
        plan.would = f"Delete {name}'s {logged:g} min on {task_label(task)} on {when}"
        plan.message = "Time deleted."
        plan.before, plan.after = {"minutes": logged}, {"minutes": 0}
    if who["id"] not in assignees_of(task):
        plan.fail(f"Kitsu only takes time logged by someone assigned to the task, and {name} is not.")
    if when > date.today().isoformat():
        plan.warnings.append(f"{when} is in the future.")
    return send_entity_write(plan, dry_run, reload=lambda _: None)
