"""Production structure: create, update, delete (and restore) projects, episodes, sequences, shots, assets,
concepts, edits and tasks. One tool per kind of record, with an `action`.

Routes follow gazu, Kitsu's Python client (what kitsu-cli calls): creates POST to the project's collection,
updates PUT `data/entities/<id>`, deletes DELETE `data/<kind>s/<id>`. Zou merges `data` (custom fields) on
update, so updates send only the fields that change; the plan reads the current values to show before/after.
"""

from typing import Any, Literal

from fastmcp.exceptions import ToolError

from kitsu_mcp.kitsu import links
from kitsu_mcp.kitsu.client import get_client
from kitsu_mcp.kitsu.lookups import get_lookups
from kitsu_mcp.kitsu.models import DryRunResult, EntityWriteResult
from kitsu_mcp.kitsu.plans import Plan, current_user
from kitsu_mcp.kitsu.validation import iso_date, object_id
from kitsu_mcp.server.app import tool
from kitsu_mcp.tools.write.common import (
    MANAGE,
    WRITE,
    require_confirm,
    send_entity_write,
    task_label,
    warn_unless_lead,
)

Action = Literal["create", "update", "delete"]
Result = EntityWriteResult | DryRunResult
STRUCTURE = WRITE | {"structure"}


# --- lookups shared by the tools ---------------------------------------------------------------------------------


def _named(records: list[dict], ref: str, label: str, where: str) -> dict:
    """A record from `records` by ID or (case-insensitive) name; the error lists what exists."""
    for r in records:
        if ref == r["id"]:
            return r
    matches = [r for r in records if (r.get("name") or "").lower() == ref.strip().lower()]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise ToolError(
            f"Several {label}s named '{ref}' in {where}; pass the ID: {', '.join(m['id'] for m in matches)}"
        )
    known = ", ".join(sorted(r.get("name") or r["id"] for r in records)[:30]) or "none"
    raise ToolError(f"No {label} '{ref}' in {where}. Known: {known}")


def _episode(project: dict, ref: str) -> dict:
    return _named(get_client().get(f"data/projects/{project['id']}/episodes"), ref, "episode", project["name"])


def _sequence(project: dict, ref: str, episode: dict | None = None) -> dict:
    sequences = get_client().get(f"data/projects/{project['id']}/sequences")
    if episode:
        sequences = [s for s in sequences if s.get("parent_id") == episode["id"]]
    return _named(sequences, ref, "sequence", episode["name"] if episode else project["name"])


def _record(kind: str, ref: str) -> dict:
    """An existing asset, shot, sequence, episode, concept or edit, by ID."""
    finder = {"asset": "list_assets", "shot": "list_shots", "sequence": "list_sequences", "episode": "list_episodes"}
    record_id = object_id(ref, kind, finder.get(kind, "search"))
    return get_client().get(f"data/{kind}s/{record_id}")


def _name_taken(existing: list[dict], name: str) -> dict | None:
    return next((r for r in existing if (r.get("name") or "").lower() == name.strip().lower()), None)


def _changes(record: dict, fields: dict[str, Any]) -> tuple[dict, dict, dict]:
    """The payload, and before/after, for the fields actually given (None means: leave as is)."""
    payload = {k: v for k, v in fields.items() if v is not None}
    before = {k: record.get(k) for k in payload}
    if "data" in payload:  # Zou merges data: send, and show, only the custom fields that change
        old = record.get("data") or {}
        changed = {k: v for k, v in payload["data"].items() if old.get(k) != v}
        if changed:
            payload["data"] = changed
        else:
            del payload["data"]
        before = {k: record.get(k) for k in payload if k != "data"}
        if changed:
            before["data"] = {k: old.get(k) for k in changed}
    return payload, before, dict(payload)


def _update(plan: Plan, kind: str, record: dict, fields: dict[str, Any], label: str) -> None:
    if all(v is None for v in fields.values()):
        raise ToolError(f"Nothing to update: pass at least one field to change on {label}")
    payload, plan.before, plan.after = _changes(record, fields)
    if not payload:
        plan.would, plan.message = f"Nothing: {label} already has these values", f"{label} unchanged."
        plan.warnings.append("These are the current values: no request is sent.")
        return
    plan.would = f"Update {label}: {', '.join(payload)}"
    plan.message = f"Updated {label}."
    plan.request("PUT", f"data/entities/{record['id']}", payload)


def _delete(plan: Plan, kind: str, record: dict, label: str, force: bool, tasks: int | None) -> None:
    """Kitsu cancels (hides) a record that has tasks instead of deleting it, unless forced."""
    params = {"force": True} if force else {}
    plan.request("DELETE", f"data/{kind}s/{record['id']}", params)
    canceled = bool(tasks) and not force
    if canceled:
        plan.would = f"Cancel {label} (it has {tasks} task(s): Kitsu hides it rather than deleting it)"
        undo = "restore it with action='restore'" if kind == "shot" else "un-cancel it in Kitsu"
        plan.message = f"Canceled {label}; {undo}, or delete it for good with force=True."
    else:
        extra = f" and its {tasks} task(s)" if tasks else ""
        plan.would = f"Delete {label}{extra} for good"
        plan.message = f"Deleted {label}."
        if tasks:
            plan.warnings.append(f"force=True also deletes its {tasks} task(s), their comments and previews.")
    plan.before = {"exists": True, "canceled": bool(record.get("canceled"))}
    plan.after = {"exists": canceled, "canceled": canceled}


def _scene_asset_instances(project_id: str) -> list[str]:
    """IDs of the asset instances placed in the project's scenes ({asset id: [instances]} per scene)."""
    client = get_client()
    ids: list[str] = []
    for scene in client.get(f"data/projects/{project_id}/scenes") or []:
        for instances in (client.get(f"data/scenes/{scene['id']}/asset-instances") or {}).values():
            ids += [i["id"] for i in instances]
    return ids


def _task_count(kind: str, entity_id: str) -> int:
    """Zou has no data/entities/<id>/tasks route: tasks are listed under the typed collection."""
    return len(get_client().get(f"data/{kind}s/{entity_id}/tasks") or [])


def _entity_url(kind: str):
    def url(record: dict) -> str | None:
        episode = record.get("source_id") if kind == "asset" else None
        return links.entity_url(record.get("project_id"), kind, record["id"], episode)

    return url


def _check_writable(plan: Plan, action: str, what: str) -> None:
    if action in ("create", "delete"):
        warn_unless_lead(plan, f"{action} {what}")


# --- tools -----------------------------------------------------------------------------------------------------


@tool(annotations=MANAGE, tags=STRUCTURE)
def manage_shot(
    action: Literal["create", "update", "delete", "restore"],
    project: str | None = None,
    shot_id: str | None = None,
    name: str | None = None,
    sequence: str | None = None,
    episode: str | None = None,
    nb_frames: int | None = None,
    frame_in: int | None = None,
    frame_out: int | None = None,
    description: str | None = None,
    custom_fields: dict[str, Any] | None = None,
    force: bool = False,
    confirm: bool = False,
    dry_run: bool = False,
) -> Result:
    """Create, update, delete or restore a shot.

    create: project, sequence (name or ID; episode too in a TV show) and name; optional nb_frames, frame_in /
    frame_out, description, custom_fields (by field key, see list_custom_fields). Refuses a name already used in
    that sequence. update: shot_id and the fields to change (custom_fields are merged with the current ones).
    delete: shot_id; a shot with tasks is canceled (hidden) unless force=True, which deletes it and its tasks.
    restore: shot_id, to un-cancel it. delete needs confirm=True; call with dry_run=True first and show the
    user the plan.
    """
    lookups = get_lookups()
    plan = Plan("manage_shot", would="")
    data = dict(custom_fields or {})
    if frame_in is not None:
        data["frame_in"] = frame_in
    if frame_out is not None:
        data["frame_out"] = frame_out
    if action == "create":
        if not (project and sequence and name and name.strip()):
            raise ToolError("create needs project, sequence and name")
        proj = lookups.project(project)
        ep = _episode(proj, episode) if episode else None
        seq = _sequence(proj, sequence, ep)
        existing = [
            s
            for s in get_client().get("data/shots", params={"project_id": proj["id"]})
            if s.get("parent_id") == seq["id"]
        ]
        if taken := _name_taken(existing, name):
            raise ToolError(f"{seq['name']} already has a shot '{taken['name']}' (ID {taken['id']}); use update")
        payload: dict[str, Any] = {"name": name.strip(), "sequence_id": seq["id"], "data": data}
        if nb_frames is not None:
            payload["nb_frames"] = nb_frames
        if description is not None:
            payload["description"] = description
        plan.request("POST", f"data/projects/{proj['id']}/shots", payload)
        plan.would = f"Create shot {seq['name']} / {name.strip()} in {proj['name']}"
        plan.message = f"Created shot {seq['name']} / {name.strip()}."
        plan.after = {k: v for k, v in payload.items() if k != "sequence_id"}
        _check_writable(plan, action, "shots")
        return send_entity_write(plan, dry_run, url=_entity_url("shot"))
    if not shot_id:
        raise ToolError(f"{action} needs shot_id (list_shots or search finds it)")
    require_confirm(action, confirm, dry_run, "a shot")
    shot = _record("shot", shot_id)
    label = f"shot {shot.get('name')}"
    if action == "update":
        if name is not None and not name.strip():
            raise ToolError("name is empty")
        fields = {
            "name": name.strip() if name else None,
            "nb_frames": nb_frames,
            "description": description,
            "data": data or None,
        }
        _update(plan, "shot", shot, fields, label)
        return send_entity_write(
            plan, dry_run, reload=lambda _: get_client().get(f"data/shots/{shot['id']}"), url=_entity_url("shot")
        )
    if action == "restore":
        if not shot.get("canceled"):
            raise ToolError(f"{label} is not canceled: nothing to restore")
        plan.request("PUT", f"data/shots/{shot['id']}", {"canceled": False})
        plan.would, plan.message = f"Restore {label}", f"Restored {label}."
        plan.before, plan.after = {"canceled": True}, {"canceled": False}
        return send_entity_write(plan, dry_run, url=_entity_url("shot"))
    _delete(plan, "shot", shot, label, force, _task_count("shot", shot["id"]))
    _check_writable(plan, action, "shots")
    return send_entity_write(plan, dry_run, reload=lambda _: None)


@tool(annotations=MANAGE, tags=STRUCTURE)
def manage_asset(
    action: Action,
    project: str | None = None,
    asset_id: str | None = None,
    name: str | None = None,
    asset_type: str | None = None,
    episode: str | None = None,
    description: str | None = None,
    custom_fields: dict[str, Any] | None = None,
    force: bool = False,
    confirm: bool = False,
    dry_run: bool = False,
) -> Result:
    """Create, update or delete an asset.

    create: project, asset_type (name or ID) and name; optional episode (TV shows), description,
    custom_fields. Refuses a name already used for that asset type. update: asset_id and the fields to change
    (name, asset_type, description; custom_fields are merged). delete: asset_id; an asset with tasks is
    canceled unless force=True, which deletes it and its tasks. delete needs confirm=True; call with
    dry_run=True first and show the user the plan.
    """
    lookups = get_lookups()
    plan = Plan("manage_asset", would="")
    if action == "create":
        if not (project and asset_type and name and name.strip()):
            raise ToolError("create needs project, asset_type and name")
        proj = lookups.project(project)
        atype = lookups.asset_type(asset_type)
        existing = [
            a
            for a in get_client().get("data/assets", params={"project_id": proj["id"]})
            if a.get("entity_type_id") == atype["id"]
        ]
        if taken := _name_taken(existing, name):
            raise ToolError(f"{proj['name']} already has a {atype['name']} '{taken['name']}' (ID {taken['id']})")
        payload: dict[str, Any] = {"name": name.strip(), "data": dict(custom_fields or {}), "is_shared": False}
        if description is not None:
            payload["description"] = description
        if episode:
            payload["episode_id"] = _episode(proj, episode)["id"]
        plan.request("POST", f"data/projects/{proj['id']}/asset-types/{atype['id']}/assets/new", payload)
        plan.would = f"Create {atype['name']} asset '{name.strip()}' in {proj['name']}"
        plan.message = f"Created asset {name.strip()}."
        plan.after = {k: v for k, v in payload.items() if k != "is_shared"}
        _check_writable(plan, action, "assets")
        return send_entity_write(plan, dry_run, url=_entity_url("asset"))
    if not asset_id:
        raise ToolError(f"{action} needs asset_id (list_assets or search finds it)")
    require_confirm(action, confirm, dry_run, "an asset")
    asset = _record("asset", asset_id)
    label = f"asset {asset.get('name')}"
    if action == "update":
        if name is not None and not name.strip():
            raise ToolError("name is empty")
        fields = {
            "name": name.strip() if name else None,
            "entity_type_id": lookups.asset_type(asset_type)["id"] if asset_type else None,
            "description": description,
            "data": custom_fields or None,
        }
        _update(plan, "asset", asset, fields, label)
        return send_entity_write(
            plan, dry_run, reload=lambda _: get_client().get(f"data/assets/{asset['id']}"), url=_entity_url("asset")
        )
    _delete(plan, "asset", asset, label, force, _task_count("asset", asset["id"]))
    _check_writable(plan, action, "assets")
    return send_entity_write(plan, dry_run, reload=lambda _: None)


def _simple_entity_tool(kind: str, collection: str, label_of: str):
    """create/update/delete for sequences, episodes, concepts and edits, which share one shape."""

    def run(action: Action, project, record_id, name, parent, description, custom_fields, force, confirm, dry_run):
        lookups = get_lookups()
        plan = Plan(f"manage_{kind}", would="")
        if action == "create":
            if not (project and name and name.strip()):
                raise ToolError("create needs project and name")
            proj = lookups.project(project)
            existing = get_client().get(f"data/projects/{proj['id']}/{collection}")
            parent_record = None
            if kind == "sequence" and parent:
                parent_record = _episode(proj, parent)
                existing = [s for s in existing if s.get("parent_id") == parent_record["id"]]
            if kind == "edit" and parent:
                parent_record = _episode(proj, parent)
            if taken := _name_taken(existing, name):
                article = "an" if kind[0] in "aeiou" else "a"
                raise ToolError(f"{proj['name']} already has {article} {kind} '{taken['name']}' (ID {taken['id']})")
            payload: dict[str, Any] = {"name": name.strip()}
            if kind in ("concept", "edit"):
                payload["data"] = dict(custom_fields or {})
            if description is not None and kind in ("concept", "edit"):
                payload["description"] = description
            if parent_record:
                payload["episode_id" if kind == "sequence" else "parent_id"] = parent_record["id"]
            plan.request("POST", f"data/projects/{proj['id']}/{collection}", payload)
            plan.would = f"Create {kind} '{name.strip()}' in {proj['name']}"
            plan.message = f"Created {kind} {name.strip()}."
            plan.after = dict(payload)
            _check_writable(plan, action, f"{kind}s")
            return send_entity_write(plan, dry_run)
        if not record_id:
            raise ToolError(f"{action} needs {kind}_id ({label_of} finds it)")
        require_confirm(action, confirm, dry_run, f"a {kind}")
        record = get_client().get(f"data/{collection}/{object_id(record_id, kind, label_of)}")
        label = f"{kind} {record.get('name')}"
        if action == "update":
            if name is not None and not name.strip():
                raise ToolError("name is empty")
            fields = {
                "name": name.strip() if name else None,
                "description": description if kind in ("concept", "edit") else None,
                "data": custom_fields or None,
            }
            _update(plan, kind, record, fields, label)
            return send_entity_write(
                plan, dry_run, reload=lambda _: get_client().get(f"data/{collection}/{record['id']}")
            )
        # Sequences and episodes: without force Kitsu refuses when anything is linked; with it, everything goes.
        if kind in ("sequence", "episode"):
            plan.request("DELETE", f"data/{collection}/{record['id']}", {"force": True} if force else {})
            plan.would = f"Delete {label}" + (" and everything in it (shots, tasks, ...)" if force else "")
            plan.message = f"Deleted {label}."
            if force:
                plan.warnings.append(f"force=True deletes everything in the {kind} as well; this cannot be undone.")
            else:
                plan.warnings.append(f"Kitsu refuses if the {kind} still holds anything; force=True deletes all.")
            plan.before, plan.after = {"exists": True}, {"exists": False}
        else:
            _delete(plan, kind, record, label, force, _task_count(kind, record["id"]))
        _check_writable(plan, action, f"{kind}s")
        return send_entity_write(plan, dry_run, reload=lambda _: None)

    return run


_sequence_run = _simple_entity_tool("sequence", "sequences", "list_sequences")
_episode_run = _simple_entity_tool("episode", "episodes", "list_episodes")
_concept_run = _simple_entity_tool("concept", "concepts", "search(kinds=['concept'])")
_edit_run = _simple_entity_tool("edit", "edits", "search(kinds=['edit'])")


@tool(annotations=MANAGE, tags=STRUCTURE)
def manage_sequence(
    action: Action,
    project: str | None = None,
    sequence_id: str | None = None,
    name: str | None = None,
    episode: str | None = None,
    custom_fields: dict[str, Any] | None = None,
    force: bool = False,
    confirm: bool = False,
    dry_run: bool = False,
) -> Result:
    """Create, rename or delete a sequence. create: project and name (and episode in a TV show). update:
    sequence_id with name and/or custom_fields. delete: sequence_id; Kitsu refuses while it holds shots unless
    force=True, which deletes its shots and tasks too. delete needs confirm=True; dry_run=True first."""
    return _sequence_run(action, project, sequence_id, name, episode, None, custom_fields, force, confirm, dry_run)


@tool(annotations=MANAGE, tags=STRUCTURE)
def manage_episode(
    action: Action,
    project: str | None = None,
    episode_id: str | None = None,
    name: str | None = None,
    custom_fields: dict[str, Any] | None = None,
    force: bool = False,
    confirm: bool = False,
    dry_run: bool = False,
) -> Result:
    """Create, rename or delete an episode (TV shows). delete: Kitsu refuses while it holds anything unless
    force=True, which deletes its sequences, shots, assets, playlists and tasks. delete needs confirm=True; call
    with dry_run=True first and show the user the plan."""
    return _episode_run(action, project, episode_id, name, None, None, custom_fields, force, confirm, dry_run)


@tool(annotations=MANAGE, tags=STRUCTURE)
def manage_concept(
    action: Action,
    project: str | None = None,
    concept_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    custom_fields: dict[str, Any] | None = None,
    force: bool = False,
    confirm: bool = False,
    dry_run: bool = False,
) -> Result:
    """Create, update or delete a concept. A concept with tasks is canceled on delete unless force=True.
    delete needs confirm=True; dry_run=True first."""
    return _concept_run(action, project, concept_id, name, None, description, custom_fields, force, confirm, dry_run)


@tool(annotations=MANAGE, tags=STRUCTURE)
def manage_edit(
    action: Action,
    project: str | None = None,
    edit_id: str | None = None,
    name: str | None = None,
    episode: str | None = None,
    description: str | None = None,
    custom_fields: dict[str, Any] | None = None,
    force: bool = False,
    confirm: bool = False,
    dry_run: bool = False,
) -> Result:
    """Create, update or delete an edit (a montage: animatic, trailer, cut). create: project and name (episode
    optional). An edit with tasks is canceled on delete unless force=True. delete needs confirm=True; call with
    dry_run=True first and show the user the plan."""
    return _edit_run(action, project, edit_id, name, episode, description, custom_fields, force, confirm, dry_run)


ProductionType = Literal["short", "featurefilm", "tvshow", "shots", "assets"]


@tool(annotations=MANAGE, tags=STRUCTURE)
def manage_project(
    action: Literal["create", "update", "close", "reopen", "delete"],
    project: str | None = None,
    name: str | None = None,
    production_type: ProductionType | None = None,
    fps: float | None = None,
    resolution: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    description: str | None = None,
    force: bool = False,
    confirm: bool = False,
    dry_run: bool = False,
) -> Result:
    """Create, update, close, reopen or delete a production.

    create: name, production_type (short, featurefilm, tvshow, shots or assets; default short); optional fps,
    resolution ("1920x1080"), start_date / end_date (YYYY-MM-DD), description. update: project (name or ID)
    and the fields to change. close / reopen: project. delete: project; Kitsu only deletes closed projects
    (close it first), and refuses one that still holds data unless force=True, which deletes everything in it.
    delete needs confirm=True; call with dry_run=True first and show the user the plan.
    """
    lookups = get_lookups()
    client = get_client()
    plan = Plan("manage_project", would="")
    fields: dict[str, Any] = {
        "name": name.strip() if name else None,
        "production_type": production_type,
        "fps": f"{fps:g}" if fps is not None else None,  # Zou stores fps as text
        "resolution": resolution,
        "start_date": iso_date(start_date, "start_date") if start_date else None,
        "end_date": iso_date(end_date, "end_date") if end_date else None,
        "description": description,
    }
    if action == "create":
        if not (name and name.strip()):
            raise ToolError("create needs name")
        if taken := _name_taken(client.get("data/projects"), name):
            raise ToolError(f"A project named '{taken['name']}' already exists (ID {taken['id']})")
        payload = {k: v for k, v in fields.items() if v is not None}
        payload.setdefault("production_type", "short")
        payload.update(production_style="2d3d", team=[], asset_types=[], task_statuses=[], task_types=[])
        plan.request("POST", "data/projects", payload)
        plan.would = f"Create {payload['production_type']} project '{payload['name']}'"
        plan.message = f"Created project {payload['name']}; add task types, statuses and people next."
        if payload["production_type"] == "tvshow":
            plan.message += " Kitsu creates a first episode, E01, with every TV show."
        plan.after = {k: v for k, v in payload.items() if v not in ([], None)}
        warn_unless_lead(plan, "create projects")
        result = send_entity_write(plan, dry_run)
        if not dry_run:
            lookups.clear()  # the new project must resolve by name in the next call
        return result
    if not project:
        raise ToolError(f"{action} needs project (name or ID)")
    require_confirm(action, confirm, dry_run, "a project")
    record = client.get(f"data/projects/{lookups.project(project)['id']}")
    label = f"project {record['name']}"
    statuses = {s["name"].lower(): s["id"] for s in client.get("data/project-status")}
    is_closed = record.get("project_status_id") == statuses.get("closed")
    if action == "update":
        if fields["start_date"] and fields["end_date"] and fields["start_date"] > fields["end_date"]:
            raise ToolError("start_date is after end_date")
        _update(plan, "project", record, fields, label)
        if plan.requests:  # projects update through their own route
            plan.requests[0].path = f"data/projects/{record['id']}"
        result = send_entity_write(plan, dry_run)
    elif action in ("close", "reopen"):
        target = statuses["closed" if action == "close" else "open"]
        if (action == "close") == is_closed:
            raise ToolError(f"{label} is already {'closed' if is_closed else 'open'}")
        plan.request("PUT", f"data/projects/{record['id']}", {"project_status_id": target})
        plan.would = f"{action.capitalize()} {label}"
        plan.message = f"{'Closed' if action == 'close' else 'Reopened'} {label}."
        plan.before, plan.after = {"open": not is_closed}, {"open": action == "reopen"}
        result = send_entity_write(plan, dry_run)
    else:
        # Zou's forced project delete does not remove asset instances placed in scenes, and the database then
        # refuses (Zou answers 500). Remove them first; their route is for admins only.
        instances = _scene_asset_instances(record["id"]) if force else []
        for instance_id in instances:
            plan.request("DELETE", f"data/asset-instances/{instance_id}")
        plan.request("DELETE", f"data/projects/{record['id']}", {"force": True} if force else {})
        plan.would = f"Delete {label}" + (" and everything in it" if force else "")
        if instances:
            plan.would += f" (first its {len(instances)} asset instance(s) in scenes, which Kitsu leaves behind)"
            if current_user().get("role") != "admin":
                plan.fail(
                    f"{label} has {len(instances)} asset instance(s) in scenes, which only an admin can "
                    "remove before deleting it (Kitsu fails otherwise); ask an admin."
                )
        plan.message = f"Deleted {label}."
        plan.before, plan.after = {"exists": True}, {"exists": False}
        if not is_closed:
            plan.fail(f"Kitsu only deletes closed projects: close {record['name']} first (action='close').")
        if force:
            plan.warnings.append("force=True deletes every asset, shot, task, comment and preview of the project.")
        else:
            plan.warnings.append("Kitsu refuses if the project still holds data; force=True deletes it all.")
        warn_unless_lead(plan, "delete projects")
        result = send_entity_write(plan, dry_run, reload=lambda _: None)
    if not dry_run:
        lookups.clear()
    return result


@tool(annotations=MANAGE, tags=STRUCTURE)
def manage_task(
    action: Literal["create", "delete"],
    entity_ids: list[str] | None = None,
    task_type: str | None = None,
    task_id: str | None = None,
    status: str | None = None,
    assignees: list[str] | None = None,
    confirm: bool = False,
    dry_run: bool = False,
) -> Result:
    """Create tasks of one type on assets, shots, sequences, episodes, concepts or edits, or delete a task.

    create: entity_ids (at most 50) and task_type (name or short name); optional status (short name, default
    Kitsu's default status) and assignees (names, emails or IDs). Entities that already have a task of that
    type are skipped, so a repeated call creates nothing twice. delete: task_id; deletes the task with its
    comments, previews and time logs. delete needs confirm=True; call with dry_run=True first.
    """
    lookups = get_lookups()
    client = get_client()
    plan = Plan("manage_task", would="")
    if action == "delete":
        if not task_id:
            raise ToolError("delete needs task_id (search_tasks finds it)")
        require_confirm(action, confirm, dry_run, "a task")
        task = client.get(f"data/tasks/{object_id(task_id, 'task', 'search_tasks')}/full")
        label = task_label(task)
        plan.request("DELETE", f"data/tasks/{task['id']}", {"force": True})
        plan.would = f"Delete task {label}, with its comments, previews and time logs"
        plan.message = f"Deleted task {label}."
        plan.before = {
            "comments": len(client.get(f"data/tasks/{task['id']}/comments") or []),
            "time_logged": task.get("duration") or 0,
        }
        plan.after = {"exists": False}
        warn_unless_lead(plan, "delete tasks")
        return send_entity_write(plan, dry_run, reload=lambda _: None)
    if not entity_ids or not task_type:
        raise ToolError("create needs entity_ids and task_type")
    if len(entity_ids) > 50:
        raise ToolError("At most 50 entities per call; split the list")
    if status:
        status_record = lookups.task_status(status)
    else:
        defaults = [s for s in lookups.index("task_statuses").values() if s.get("is_default")]
        if not defaults:
            raise ToolError("Kitsu has no default task status; pass status")
        status_record = defaults[0]
    people = [lookups.person(a)["id"] for a in assignees or []]
    created, skipped = [], []
    entities = [
        client.get(f"data/entities/{object_id(ref, 'entity', 'list_shots or list_assets')}")
        for ref in dict.fromkeys(entity_ids)
    ]  # de-duplicated, order kept
    # An entity's `type` (Shot, Asset, Concept, ...) is the `for_entity` of the task types that apply to it.
    kinds = {str(e.get("type")) for e in entities}
    # One task type for the call; when a name repeats across kinds ("Concept"), the entities' kind decides.
    ttype = lookups.task_type_for(task_type, kinds.pop()) if len(kinds) == 1 else lookups.task_type(task_type)
    for entity in entities:
        kind = str(entity.get("type"))
        if ttype.get("for_entity") and str(ttype["for_entity"]).lower() != kind.lower():
            plan.warnings.append(
                f"{ttype['name']} is a task type for {ttype['for_entity']}s, and "
                f"{entity.get('name')} is a {kind.lower()}: Kitsu will not show that task."
            )
        existing = client.get("data/tasks", params={"entity_id": entity["id"], "task_type_id": ttype["id"]})
        if existing:
            skipped.append(entity.get("name") or entity["id"])
            continue
        plan.request(
            "POST",
            "data/tasks",
            {
                "project_id": entity["project_id"],
                "entity_id": entity["id"],
                "task_type_id": ttype["id"],
                "task_status_id": status_record["id"],
                "assignees": people,
                "name": "main",
            },
        )
        created.append(entity.get("name") or entity["id"])
    for name_ in skipped:
        plan.warnings.append(f"Skipped {name_}: it already has a {ttype['name']} task")
    if not created:
        plan.warnings.append("Nothing to create: no request is sent.")
    plan.would = f"Create {len(created)} {ttype['name']} task(s)" + (f": {', '.join(created)}" if created else "")
    plan.message = f"Created {len(created)} {ttype['name']} task(s)" + (
        f", skipped {len(skipped)}." if skipped else "."
    )
    plan.after = {"created": created, "status": status_record["short_name"], "assignees": len(people)}
    warn_unless_lead(plan, "create tasks")
    return send_entity_write(plan, dry_run)
