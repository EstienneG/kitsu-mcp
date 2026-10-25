"""Project configuration: team, the task types / statuses / asset types a project uses, custom fields, the
schedule, budgets and status automations.

Checked on a throwaway Zou, which differs from gazu (what kitsu-cli calls) in places:
- Updating a custom field (metadata descriptor) resets every attribute not sent: choices alone turn a "list"
  into "string", a rename without choices empties them. `manage_custom_field` always sends the whole field.
- A budget entry is a salary line (person, department, start month, months, daily rate), not gazu's
  name/amount: Zou refuses those. Updating one writes None into every field left out (Zou then refuses), so
  `update_line` sends the whole line.
- Schedule items and milestones are only created through Zou's generic routes. Admins and the production's
  managers may use them (older Zou, e.g. 1.0.43, keeps creating schedule rows to admins).
"""

from typing import Any, Literal

from fastmcp.exceptions import ToolError

from kitsu_mcp.kitsu.client import get_client
from kitsu_mcp.kitsu.lookups import get_lookups
from kitsu_mcp.kitsu.models import DryRunResult, EntityWriteResult
from kitsu_mcp.kitsu.plans import Plan, current_user
from kitsu_mcp.kitsu.validation import iso_date, object_id
from kitsu_mcp.server.app import tool
from kitsu_mcp.tools.write.common import MANAGE, WRITE, require_confirm, send_entity_write, warn_unless_lead

ADMIN = WRITE | {"admin"}
Result = EntityWriteResult | DryRunResult


def _project(ref: str) -> dict:
    return get_client().get(f"data/projects/{get_lookups().project(ref)['id']}")


def _managers_only(plan: Plan, what: str) -> None:
    """Zou checks manager access to the production; versions differ, so a warning rather than a refusal."""
    if current_user().get("role") not in ("admin", "manager"):
        plan.warnings.append(f"Kitsu may refuse: it lets admins and the production's managers {what}.")


def _done(plan: Plan, dry_run: bool) -> Result:
    result = send_entity_write(plan, dry_run, reload=lambda _: None)
    if not dry_run:
        get_lookups().clear()  # team, types and custom fields are cached
    return result


@tool(annotations=MANAGE, tags=ADMIN)
def manage_project_team(
    project: str,
    action: Literal["add", "remove"],
    people: list[str],
    dry_run: bool = False,
) -> Result:
    """Add people to a production's team, or remove them (names, emails or IDs). Only team members see the
    project in Kitsu. Removing someone does not unassign their tasks. dry_run=True: show the plan without
    writing; show it to the user first.
    """
    record = _project(project)
    lookups = get_lookups()
    team = set(record.get("team") or [])
    plan = Plan("manage_project_team", would="")
    changed = []
    for ref in dict.fromkeys(people):
        person = lookups.person(ref)
        name = person.get("full_name") or person["id"]
        if action == "add" and person["id"] not in team:
            plan.request("POST", f"data/projects/{record['id']}/team", {"person_id": person["id"]})
            changed.append(name)
        elif action == "remove" and person["id"] in team:
            plan.request("DELETE", f"data/projects/{record['id']}/team/{person['id']}")
            changed.append(name)
        else:
            plan.warnings.append(f"{name} is {'already' if action == 'add' else 'not'} in the team: skipped.")
    plan.would = f"{'Add' if action == 'add' else 'Remove'} {', '.join(changed) or 'nobody'} " + (
        f"{'to' if action == 'add' else 'from'} the {record['name']} team"
    )
    plan.message = f"Team of {record['name']}: {len(changed)} {'added' if action == 'add' else 'removed'}."
    plan.before, plan.after = (
        {"team_size": len(team)},
        {"team_size": len(team) + (len(changed) if action == "add" else -len(changed))},
    )
    warn_unless_lead(plan, "change a project's team")
    return _done(plan, dry_run)


@tool(annotations=MANAGE, tags=ADMIN)
def manage_project_settings(
    project: str,
    action: Literal["add", "remove"],
    task_types: list[str] | None = None,
    task_statuses: list[str] | None = None,
    asset_types: list[str] | None = None,
    status_automations: list[str] | None = None,
    dry_run: bool = False,
) -> Result:
    """Choose which studio task types, task statuses, asset types and status automations a production uses
    (Kitsu's production settings). Names, short names or IDs; status_automations take IDs (kitsu_get
    data/status-automations). Removing one from a project keeps its existing tasks. dry_run=True: show the plan
    without writing; show it to the user first.
    """
    record = _project(project)
    lookups = get_lookups()
    plan = Plan("manage_project_settings", would="")
    kinds: list[tuple[str, list[str], Any, str, str]] = [
        ("task type", task_types or [], lambda r: lookups.task_type(r), "task-types", "task_types"),
        ("task status", task_statuses or [], lambda r: lookups.task_status(r), "task-status", "task_statuses"),
        ("asset type", asset_types or [], lambda r: lookups.asset_type(r), "asset-types", "asset_types"),
        (
            "status automation",
            status_automations or [],
            lambda r: {"id": object_id(r, "status automation", "kitsu_get data/status-automations"), "name": r},
            "status-automations",
            "status_automations",
        ),
    ]
    if not any(refs for _, refs, *_ in kinds):
        raise ToolError("Pass task_types, task_statuses, asset_types and/or status_automations")
    lines = []
    for label, refs, resolve, route, field in kinds:
        current = set(record.get(field) or [])
        for ref in dict.fromkeys(refs):
            item = resolve(ref)
            name = item.get("name") or item.get("short_name") or item["id"]
            if action == "add" and item["id"] not in current:
                key = {
                    "task-types": "task_type_id",
                    "task-status": "task_status_id",
                    "asset-types": "asset_type_id",
                    "status-automations": "status_automation_id",
                }[route]
                payload: dict[str, Any] = {key: item["id"]}
                if route == "task-types":
                    payload["priority"] = len(current) + 1
                plan.request("POST", f"data/projects/{record['id']}/settings/{route}", payload)
                lines.append(f"+{label} {name}")
            elif action == "remove" and item["id"] in current:
                plan.request("DELETE", f"data/projects/{record['id']}/settings/{route}/{item['id']}")
                lines.append(f"-{label} {name}")
            else:
                plan.warnings.append(f"{label} {name} is {'already' if action == 'add' else 'not'} used: skipped.")
    plan.would = f"{record['name']} settings: " + ("; ".join(lines) or "no change")
    plan.message = f"Updated the settings of {record['name']}: {len(lines)} change(s)."
    plan.after = {"changes": lines}
    warn_unless_lead(plan, "change production settings")
    return _done(plan, dry_run)


DataType = Literal["string", "number", "boolean", "date", "list", "taglist", "checklist"]


@tool(annotations=MANAGE, tags=ADMIN)
def manage_custom_field(
    project: str,
    action: Literal["create", "update", "delete"],
    name: str | None = None,
    entity_type: Literal["Asset", "Shot", "Sequence", "Episode", "Edit"] | None = None,
    data_type: DataType | None = None,
    choices: list[str] | None = None,
    new_name: str | None = None,
    for_client: bool | None = None,
    departments: list[str] | None = None,
    confirm: bool = False,
    dry_run: bool = False,
) -> Result:
    """Create, change or delete a production's custom field (a metadata column).

    create: name, entity_type, data_type (default string); choices for list / taglist / checklist; optional
    for_client and departments (who sees it). update: name (and entity_type if several share it) plus what
    changes: new_name, data_type, choices (the full new list), for_client, departments; the rest is kept.
    delete: name; removes the column and its values on every entity; needs confirm=True. dry_run=True: show
    the plan without writing; show it to the user first.
    """
    record = _project(project)
    lookups = get_lookups()
    require_confirm(action, confirm, dry_run, "a custom field")
    if not name or not name.strip():
        raise ToolError(f"{action} needs name")
    department_ids = [lookups.resolve("departments", d)["id"] for d in departments] if departments is not None else None
    fields = lookups.custom_fields(record["id"])
    matches = [
        f
        for f in fields
        if f["name"].lower() == name.strip().lower() and (entity_type is None or f.get("entity_type") == entity_type)
    ]
    plan = Plan("manage_custom_field", would="")
    route = f"data/projects/{record['id']}/metadata-descriptors"
    if action == "create":
        if not entity_type:
            raise ToolError("create needs entity_type")
        if matches:
            raise ToolError(f"{record['name']} already has a {entity_type} field '{matches[0]['name']}'")
        kind = data_type or "string"
        if kind in ("list", "taglist", "checklist") and not choices:
            raise ToolError(f"A {kind} field needs choices")
        payload = {
            "name": name.strip(),
            "entity_type": entity_type,
            "data_type": kind,
            "choices": choices or [],
            "for_client": bool(for_client),
            "departments": department_ids or [],
        }
        plan.request("POST", route, payload)
        plan.would = f"Add {entity_type} field '{name.strip()}' ({kind}) to {record['name']}"
        plan.message = f"Added field {name.strip()}."
        plan.after = payload
        return _done(plan, dry_run)
    if not matches:
        raise ToolError(f"No custom field '{name}' in {record['name']} (list_custom_fields)")
    if len(matches) > 1:
        raise ToolError(
            f"Several fields are named '{name}' ({', '.join(str(m.get('entity_type')) for m in matches)}): "
            "pass entity_type"
        )
    field = matches[0]
    label = f"{field.get('entity_type')} field '{field['name']}'"
    if action == "delete":
        plan.request("DELETE", f"{route}/{field['id']}")
        plan.would = f"Delete {label} and its values on every {str(field.get('entity_type')).lower()}"
        plan.message = f"Deleted {label}."
        plan.before, plan.after = {"exists": True}, {"exists": False}
        return _done(plan, dry_run)
    # Zou resets every attribute an update leaves out (choices alone turn a list into a string; a rename empties
    # the choices), so send the whole field with the changes applied.
    current = {
        "name": field["name"],
        "data_type": field.get("data_type") or "string",
        "choices": field.get("choices") or [],
        "for_client": bool(field.get("for_client")),
        "departments": field.get("departments") or [],
    }
    changes = {
        "name": new_name.strip() if new_name else None,
        "data_type": data_type,
        "choices": choices,
        "for_client": for_client,
        "departments": department_ids,
    }
    changes = {k: v for k, v in changes.items() if v is not None and v != current[k]}
    if not changes:
        raise ToolError("Nothing to update: pass new_name, data_type, choices, for_client or departments")
    full = {**current, **changes}
    if full["data_type"] in ("list", "taglist", "checklist") and not full["choices"]:
        raise ToolError(f"A {full['data_type']} field needs choices")
    removed = set(current["choices"]) - set(full["choices"])
    plan.request("PUT", f"{route}/{field['id']}", full)
    plan.would = f"Update {label}: {', '.join(changes)}"
    plan.message = f"Updated {label}."
    plan.before, plan.after = {k: current[k] for k in changes}, changes
    if removed:
        plan.warnings.append(f"Entities set to a removed choice keep that value: {', '.join(sorted(removed))}")
    return _done(plan, dry_run)


@tool(annotations=MANAGE, tags=ADMIN)
def manage_schedule(
    project: str,
    action: Literal["set_task_type_dates", "add_milestone", "delete_milestone"],
    task_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    man_days: float | None = None,
    name: str | None = None,
    date: str | None = None,
    milestone_id: str | None = None,
    confirm: bool = False,
    dry_run: bool = False,
) -> Result:
    """Plan a production on Kitsu's Schedule page: a task type's dates, and milestones.

    set_task_type_dates: task_type and start_date / end_date (YYYY-MM-DD), optional man_days; creates the
    schedule row if missing. add_milestone: name and date (optional task_type). delete_milestone: milestone_id
    (production_schedule lists them); needs confirm=True. Kitsu lets admins and the production's managers do
    this. dry_run=True: show the plan without writing; show it to the user first.
    """
    record = _project(project)
    lookups = get_lookups()
    client = get_client()
    require_confirm("delete" if action == "delete_milestone" else action, confirm, dry_run, "a milestone")
    plan = Plan("manage_schedule", would="")
    if action == "set_task_type_dates":
        if not task_type or not (start_date or end_date or man_days is not None):
            raise ToolError("set_task_type_dates needs task_type and start_date, end_date and/or man_days")
        ttype = lookups.task_type(task_type)
        rows = [
            i
            for i in client.get(f"data/projects/{record['id']}/schedule-items")
            if i.get("task_type_id") == ttype["id"] and not i.get("object_id")
        ]
        start = iso_date(start_date, "start_date") if start_date else None
        end = iso_date(end_date, "end_date") if end_date else None
        changes = {k: v for k, v in (("start_date", start), ("end_date", end), ("man_days", man_days)) if v is not None}
        if rows:
            row = rows[0]
            plan.request("PUT", f"data/schedule-items/{row['id']}", changes)
            plan.before = {k: row.get(k) for k in changes}
            merged = {**row, **changes}
        else:
            if not (start and end):
                raise ToolError(f"{ttype['name']} has no schedule row yet: pass both start_date and end_date")
            plan.request(
                "POST", "data/schedule-items", {"project_id": record["id"], "task_type_id": ttype["id"], **changes}
            )
            _managers_only(plan, "create schedule rows")
            merged = changes
        first, last = str(merged.get("start_date") or "")[:10], str(merged.get("end_date") or "")[:10]
        if first and last and first > last:
            plan.fail("The start date would be after the end date.")
        plan.would = f"Schedule {ttype['name']} in {record['name']}: " + ", ".join(
            f"{k} {v}" for k, v in changes.items()
        )
        plan.message = f"Schedule of {ttype['name']} updated."
        plan.after = changes
    elif action == "add_milestone":
        if not (name and name.strip() and date):
            raise ToolError("add_milestone needs name and date")
        payload: dict[str, Any] = {"project_id": record["id"], "name": name.strip(), "date": iso_date(date, "date")}
        if task_type:
            payload["task_type_id"] = lookups.task_type(task_type)["id"]
        plan.request("POST", "data/milestones", payload)
        plan.would = f"Add milestone '{name.strip()}' on {payload['date']} to {record['name']}"
        plan.message = "Milestone added."
        plan.after = payload
        _managers_only(plan, "create milestones")
    else:
        if not milestone_id:
            raise ToolError("delete_milestone needs milestone_id")
        milestone = next(
            (m for m in client.get(f"data/projects/{record['id']}/milestones") if m["id"] == milestone_id), None
        )
        if milestone is None:
            raise ToolError(f"No milestone {milestone_id} in {record['name']} (production_schedule lists them)")
        plan.request("DELETE", f"data/milestones/{milestone_id}")
        plan.would = f"Delete milestone '{milestone.get('name')}' ({milestone.get('date')})"
        plan.message = "Milestone deleted."
        _managers_only(plan, "delete milestones")
    return send_entity_write(plan, dry_run, reload=lambda _: None)


Position = Literal["artist", "lead", "supervisor", "manager", "vendor"]
Seniority = Literal["junior", "mid", "senior"]


@tool(annotations=MANAGE, tags=ADMIN)
def manage_budget(
    project: str,
    action: Literal["create", "rename", "delete", "add_line", "update_line", "delete_line"],
    budget: str | None = None,
    name: str | None = None,
    currency: str | None = None,
    line_id: str | None = None,
    person: str | None = None,
    department: str | None = None,
    start_month: str | None = None,
    months: int | None = None,
    daily_rate: float | None = None,
    position: Position | None = None,
    seniority: Seniority | None = None,
    confirm: bool = False,
    dry_run: bool = False,
) -> Result:
    """Edit a production's budget, as on Kitsu's Budget page: budget versions and their salary lines.

    create: name (and currency, e.g. EUR). rename / delete: budget (name or ID). add_line: budget, department,
    start_month (YYYY-MM), months, daily_rate; optional person, position, seniority. update_line /
    delete_line: budget and line_id (budget shows them) plus what changes. Deletes need confirm=True. Kitsu shows
    budgets to producers and admins. dry_run=True: show the plan without writing; show it to the user first.
    """
    record = _project(project)
    lookups = get_lookups()
    client = get_client()
    require_confirm("delete" if action in ("delete", "delete_line") else action, confirm, dry_run, "budget data")
    route = f"data/projects/{record['id']}/budgets"
    plan = Plan("manage_budget", would="")
    if action == "create":
        if not (name and name.strip()):
            raise ToolError("create needs name")
        payload = {"name": name.strip()} | ({"currency": currency.upper()} if currency else {})
        plan.request("POST", route, payload)
        plan.would, plan.message = f"Create budget '{name.strip()}' in {record['name']}", "Budget created."
        plan.after = payload
        return send_entity_write(plan, dry_run)
    budgets = client.get(route) or []
    if not budget:
        raise ToolError(f"{action} needs budget (name or ID)")
    chosen = next((b for b in budgets if budget == b["id"] or (b.get("name") or "").lower() == budget.lower()), None)
    if chosen is None:
        raise ToolError(
            f"No budget '{budget}' in {record['name']}; it has: "
            f"{', '.join(b.get('name') or b['id'] for b in budgets) or 'none'}"
        )
    label = f"budget '{chosen.get('name')}'"
    if action == "rename":
        if not (name and name.strip()):
            raise ToolError("rename needs name")
        plan.request("PUT", f"{route}/{chosen['id']}", {"name": name.strip()})
        plan.would, plan.message = f"Rename {label} to '{name.strip()}'", "Budget renamed."
        plan.before, plan.after = {"name": chosen.get("name")}, {"name": name.strip()}
    elif action == "delete":
        plan.request("DELETE", f"{route}/{chosen['id']}")
        plan.would, plan.message = f"Delete {label} and all its lines", "Budget deleted."
    elif action == "add_line":
        if not (department and start_month and months and daily_rate is not None):
            raise ToolError("add_line needs department, start_month, months and daily_rate")
        payload = {
            "department_id": lookups.resolve("departments", department)["id"],
            "start_date": iso_date(f"{start_month}-01" if len(start_month) == 7 else start_month, "start_month"),
            "months_duration": months,
            "daily_salary": daily_rate,
            "position": position or "artist",
            "seniority": seniority or "mid",
        }
        if person:
            payload["person_id"] = lookups.person(person)["id"]
        plan.request("POST", f"{route}/{chosen['id']}/entries", payload)
        plan.would = (
            f"Add a line to {label}: {department}, {months} month(s) from {payload['start_date'][:7]} "
            f"at {daily_rate:g}/day"
        )
        plan.message = "Budget line added."
        plan.after = payload
    else:
        if not line_id:
            raise ToolError(f"{action} needs line_id (budget lists the lines)")
        lines = client.get(f"{route}/{chosen['id']}/entries") or []
        line = next((x for x in lines if x["id"] == line_id), None)
        if line is None:
            raise ToolError(f"No line {line_id} in {label}")
        if action == "delete_line":
            plan.request("DELETE", f"{route}/{chosen['id']}/entries/{line_id}")
            plan.would, plan.message = f"Delete a line of {label}", "Budget line deleted."
        else:
            changes: dict[str, Any] = {
                "department_id": lookups.resolve("departments", department)["id"] if department else None,
                "person_id": lookups.person(person)["id"] if person else None,
                "start_date": (
                    iso_date(f"{start_month}-01" if len(start_month) == 7 else start_month, "start_month")
                    if start_month
                    else None
                ),
                "months_duration": months,
                "daily_salary": daily_rate,
                "position": position,
                "seniority": seniority,
            }
            changes = {k: v for k, v in changes.items() if v is not None and v != line.get(k)}
            if not changes:
                raise ToolError("Nothing to update on that line")
            # Zou writes None into every field an update leaves out (and refuses), and resets the hand-set
            # month costs: send the whole line with the changes applied.
            keep = (
                "department_id",
                "person_id",
                "start_date",
                "months_duration",
                "daily_salary",
                "position",
                "seniority",
                "exceptions",
            )
            full = {k: line.get(k) for k in keep} | changes
            full["start_date"] = str(full.get("start_date") or "")[:10] or None
            full["exceptions"] = full.get("exceptions") or {}
            plan.request("PUT", f"{route}/{chosen['id']}/entries/{line_id}", full)
            plan.would, plan.message = f"Update a line of {label}: {', '.join(changes)}", "Budget line updated."
            plan.before, plan.after = {k: line.get(k) for k in changes}, changes
    warn_unless_lead(plan, "edit budgets")
    return send_entity_write(plan, dry_run, reload=lambda _: None)
