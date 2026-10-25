"""The breakdown: which assets are cast in which shots (and episodes), and scenes.

Zou's casting route (`PUT data/projects/<id>/entities/<id>/casting`) replaces the whole casting of the shot, so
`set_casting` reads it first: `add` and `remove` change only the assets given, and only `replace` sends a new
list as is. Checked on a throwaway Zou.
"""

from typing import Literal

from fastmcp.exceptions import ToolError

from kitsu_mcp.kitsu.client import get_client
from kitsu_mcp.kitsu.lookups import get_lookups
from kitsu_mcp.kitsu.models import DryRunResult, EntityWriteResult
from kitsu_mcp.kitsu.plans import Plan
from kitsu_mcp.kitsu.validation import object_id
from kitsu_mcp.server.app import tool
from kitsu_mcp.tools.write.common import MANAGE, OVERWRITE, WRITE, send_entity_write

PRODUCTION = WRITE | {"production"}


def _entity(entity_id: str) -> dict:
    return get_client().get(f"data/entities/{object_id(entity_id, 'shot, episode or asset', 'list_shots')}")


def _assets_by_ref(project_id: str) -> dict[str, dict]:
    """The project's assets by ID and by lower-case name (names can repeat across types: then ID only)."""
    assets = get_client().get("data/assets", params={"project_id": project_id})
    index: dict[str, dict] = {a["id"]: a for a in assets}
    names: dict[str, list[dict]] = {}
    for a in assets:
        names.setdefault((a.get("name") or "").lower(), []).append(a)
    for name, found in names.items():
        if len(found) == 1:
            index[name] = found[0]
    return index


def _asset(index: dict[str, dict], ref: str) -> dict:
    found = index.get(ref) or index.get(ref.strip().lower())
    if found is None:
        raise ToolError(f"No asset '{ref}' in this project (or several share the name: pass the ID)")
    return found


@tool(annotations=OVERWRITE, tags=PRODUCTION)
def set_casting(
    entity_id: str,
    action: Literal["add", "remove", "replace"],
    assets: list[str],
    occurrences: dict[str, int] | None = None,
    dry_run: bool = False,
) -> EntityWriteResult | DryRunResult:
    """Change which assets are cast in a shot (or an episode, or an asset's own breakdown).

    action: add (cast these assets, keeping the others), remove (uncast them), or replace (the casting becomes
    exactly `assets`). assets: names or IDs. occurrences: asset -> how many times it appears (default 1; with
    add, also updates an asset already cast). dry_run=True: show which assets come and go without writing;
    show it to the user first.
    """
    entity = _entity(entity_id)
    project_id = entity["project_id"]
    route = f"data/projects/{project_id}/entities/{entity['id']}/casting"
    current = {c["asset_id"]: c for c in get_client().get(route) or []}
    index = _assets_by_ref(project_id)
    given = [_asset(index, a) for a in dict.fromkeys(assets)]
    counts = {_asset(index, k)["id"]: v for k, v in (occurrences or {}).items()}
    if any(v < 1 for v in counts.values()):
        raise ToolError("occurrences must be 1 or more; use action='remove' to uncast")
    new = {a: c.get("nb_occurences") or 1 for a, c in current.items()}
    not_cast: list[str] = []
    if action == "add":
        for a in given:
            new[a["id"]] = counts.get(a["id"], new.get(a["id"], 1))
    elif action == "remove":
        not_cast = [a["name"] for a in given if a["id"] not in current]
        for a in given:
            new.pop(a["id"], None)
    else:
        new = {a["id"]: counts.get(a["id"], 1) for a in given}
    names = {a["id"]: a["name"] for a in index.values()} | {a: c.get("asset_name") for a, c in current.items()}
    before = {names.get(a, a): c.get("nb_occurences") or 1 for a, c in current.items()}
    after = {names.get(a, a): n for a, n in new.items()}
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    recounted = sorted(n for n in set(after) & set(before) if after[n] != before[n])
    plan = Plan("set_casting", would="")
    if before != after:
        plan.request("PUT", route, [{"asset_id": a, "nb_occurences": n} for a, n in new.items()])  # whole list
    changes = [
        f"+{', '.join(added)}" if added else "",
        f"-{', '.join(removed)}" if removed else "",
        f"count of {', '.join(recounted)}" if recounted else "",
    ]
    label = entity.get("name") or entity["id"]
    plan.would = f"Casting of {label}: " + ("; ".join(c for c in changes if c) or "no change")
    plan.message = f"Casting of {label} updated: {len(after)} asset(s)."
    plan.before, plan.after = {"casting": before}, {"casting": after}
    if action == "replace" and removed:
        plan.warnings.append(f"replace uncasts {len(removed)} asset(s) not in the list: {', '.join(removed)}")
    if not_cast:
        plan.warnings.append(f"Not cast already: {', '.join(not_cast)}")
    if before == after:
        plan.warnings.append("Nothing changes: no request is sent.")
    return send_entity_write(
        plan, dry_run, reload=lambda _: {"id": entity["id"], "name": label, "casting": get_client().get(route)}
    )


@tool(annotations=MANAGE, tags=WRITE | {"structure"})
def manage_scene(
    action: Literal["create", "rename", "add_shot", "remove_shot", "add_asset"],
    project: str | None = None,
    scene_id: str | None = None,
    name: str | None = None,
    sequence: str | None = None,
    shot_id: str | None = None,
    asset_id: str | None = None,
    dry_run: bool = False,
) -> EntityWriteResult | DryRunResult:
    """Scenes (layout files shared by several shots): create one, rename it, link shots to it or unlink them,
    and instance assets in it.

    create: project, sequence (name or ID) and name. rename: scene_id and name. add_shot / remove_shot:
    scene_id and shot_id. add_asset: scene_id and asset_id (adds an instance of the asset). dry_run=True: show
    the plan without writing; show it to the user first.
    """
    client = get_client()
    plan = Plan("manage_scene", would="")
    if action == "create":
        if not (project and sequence and name and name.strip()):
            raise ToolError("create needs project, sequence and name")
        proj = get_lookups().project(project)
        sequences = client.get(f"data/projects/{proj['id']}/sequences")
        seq = next(
            (s for s in sequences if sequence in (s["id"], s["name"]) or s["name"].lower() == sequence.lower()), None
        )
        if seq is None:
            raise ToolError(f"No sequence '{sequence}' in {proj['name']}")
        scenes = client.get(f"data/projects/{proj['id']}/scenes")
        taken = next(
            (
                s
                for s in scenes
                if s.get("parent_id") == seq["id"] and (s.get("name") or "").lower() == name.strip().lower()
            ),
            None,
        )
        if taken:
            raise ToolError(f"{seq['name']} already has a scene '{taken['name']}' (ID {taken['id']})")
        plan.request("POST", f"data/projects/{proj['id']}/scenes", {"name": name.strip(), "sequence_id": seq["id"]})
        plan.would = f"Create scene {seq['name']} / {name.strip()}"
        plan.message = f"Created scene {name.strip()}."
        return send_entity_write(plan, dry_run)
    if not scene_id:
        raise ToolError(f"{action} needs scene_id")
    scene = client.get(f"data/entities/{object_id(scene_id, 'scene', 'kitsu_get')}")
    label = f"scene {scene.get('name')}"
    if action == "rename":
        if not (name and name.strip()):
            raise ToolError("rename needs name")
        plan.request("PUT", f"data/entities/{scene['id']}", {"name": name.strip()})
        plan.would, plan.message = f"Rename {label} to {name.strip()}", "Scene renamed."
        plan.before, plan.after = {"name": scene.get("name")}, {"name": name.strip()}
    elif action in ("add_shot", "remove_shot"):
        if not shot_id:
            raise ToolError(f"{action} needs shot_id")
        shot = client.get(f"data/shots/{object_id(shot_id, 'shot', 'list_shots')}")
        linked = {s["id"] for s in client.get(f"data/scenes/{scene['id']}/shots") or []}
        if action == "add_shot":
            if shot["id"] in linked:
                raise ToolError(f"Shot {shot['name']} is already in {label}")
            plan.request("POST", f"data/scenes/{scene['id']}/shots", {"shot_id": shot["id"]})
        else:
            if shot["id"] not in linked:
                raise ToolError(f"Shot {shot['name']} is not in {label}")
            plan.request("DELETE", f"data/scenes/{scene['id']}/shots/{shot['id']}")
        verb = "Link" if action == "add_shot" else "Unlink"
        plan.would, plan.message = f"{verb} shot {shot['name']} and {label}", f"{verb}ed shot {shot['name']}."
    else:
        if not asset_id:
            raise ToolError("add_asset needs asset_id")
        asset = client.get(f"data/assets/{object_id(asset_id, 'asset', 'list_assets')}")
        plan.request("POST", f"data/scenes/{scene['id']}/asset-instances", {"asset_id": asset["id"]})
        plan.would, plan.message = f"Add an instance of {asset['name']} to {label}", "Asset instance added."
    return send_entity_write(plan, dry_run)
