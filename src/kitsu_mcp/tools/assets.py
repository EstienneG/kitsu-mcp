from kitsu_mcp.app import READ_ONLY, mcp
from kitsu_mcp.client import get_client
from kitsu_mcp.formatters import task_summary
from kitsu_mcp.lookups import Lookups, check_names, get_lookups
from kitsu_mcp.models import AssetDetail, AssetList, AssetSummary
from kitsu_mcp.validation import Detail, Limit, Offset, object_id


def statuses(tasks: list) -> dict[str, str | None]:
    """Compact form of an entity's tasks: task type -> status short name."""
    return {t.task_type or "?": t.status for t in tasks}


def check_status_filters(status_filters: dict[str, list[str]] | None, lookups: Lookups) -> None:
    """Unknown task type or status names in a filter are errors, not silently empty results."""
    if not status_filters:
        return
    types = lookups.index("task_types").values()
    check_names("task type", list(status_filters), {t["name"] for t in types})
    statuses = {s["short_name"] for s in lookups.index("task_statuses").values()}
    for allowed in status_filters.values():
        check_names("task status", allowed, statuses)


def match_types(wanted: list[str] | None, project_types: list[str]) -> set[str]:
    """Lower-case names of the project's asset types that `wanted` refers to: for each, the type with that
    exact name, else every type whose name contains it. An unmatched name is an error naming the options."""
    matched: set[str] = set()
    lowered = {t.lower(): t for t in project_types}
    for name in wanted or []:
        key = " ".join(name.split()).lower()
        hits = {key} if key in lowered else {t for t in lowered if key and key in t}
        if not hits:
            check_names("asset type in this project", [name], set(project_types))
        matched |= hits
    return matched


def matches_status_filters(tasks: list, status_filters: dict[str, list[str]] | None) -> bool:
    """True if, for every task type in the filter, the entity has a task of that type in an allowed status."""
    if not status_filters:
        return True
    by_type = {(t.task_type or "").lower(): (t.status or "").lower() for t in tasks}
    return all(
        by_type.get(task_type.lower()) in {s.lower() for s in allowed} for task_type, allowed in status_filters.items()
    )


@mcp.tool(annotations=READ_ONLY, tags={"assets"})
def list_assets(
    project: str,
    asset_types: list[str] | None = None,
    exclude_asset_types: list[str] | None = None,
    task_status_filters: dict[str, list[str]] | None = None,
    name_contains: str | None = None,
    detail: Detail = "compact",
    limit: Limit = 100,
    offset: Offset = 0,
) -> AssetList:
    """List a project's assets with their tasks, optionally filtered.

    detail="compact" (default) gives each asset's tasks as {task type: status}; detail="full" returns
    full task rows (IDs, assignees, due dates, latest preview), several times larger. get_asset has the details.
    project: project name or ID.
    asset_types / exclude_asset_types: asset type names, matched against the types this project uses:
    an exact name, else every type containing it ("Characters" also matches "Characters - PFE 2028").
    task_status_filters: task type name -> allowed status short names; all must match,
    e.g. {"Modelling": ["APP", "wip"], "Sculpting": ["WRA"]}. Matching is case-insensitive.
    """
    lookups = get_lookups()
    project_id = lookups.project(project)["id"]
    check_status_filters(task_status_filters, lookups)
    client = get_client()
    project_types = [t["name"] for t in client.get(f"data/projects/{project_id}/asset-types")]
    include = match_types(asset_types, project_types)
    exclude = match_types(exclude_asset_types, project_types)

    results = []
    for asset in client.get("data/assets/with-tasks", params={"project_id": project_id}):
        if asset.get("canceled"):
            continue
        type_name = asset.get("asset_type_name") or lookups.name("asset_types", asset.get("entity_type_id")) or ""
        if include and type_name.lower() not in include:
            continue
        if exclude and type_name.lower() in exclude:
            continue
        if name_contains and name_contains.lower() not in asset.get("name", "").lower():
            continue
        tasks = [task_summary(t, lookups) for t in asset.get("tasks") or []]
        if not matches_status_filters(tasks, task_status_filters):
            continue
        if detail == "compact":
            results.append(AssetSummary(id=asset["id"], name=asset["name"], type=type_name, statuses=statuses(tasks)))
        else:
            results.append(AssetSummary(id=asset["id"], name=asset["name"], type=type_name, tasks=tasks))

    results.sort(key=lambda a: ((a.type or "").lower(), a.name.lower()))
    return AssetList(total=len(results), assets=results[offset : offset + limit])


@mcp.tool(annotations=READ_ONLY, tags={"assets"})
def get_asset(asset_id: str) -> AssetDetail:
    """Get an asset's details and tasks."""
    asset_id = object_id(asset_id, "asset", "list_assets")
    lookups = get_lookups()
    client = get_client()
    asset = client.get(f"data/assets/{asset_id}")
    tasks = client.get(f"data/assets/{asset_id}/tasks")
    return AssetDetail(
        id=asset["id"],
        name=asset["name"],
        type=asset.get("asset_type_name") or lookups.name("asset_types", asset.get("entity_type_id")),
        description=asset.get("description"),
        project_id=asset.get("project_id"),
        data=asset.get("data"),
        tasks=[task_summary(t, lookups) for t in tasks],
    )
