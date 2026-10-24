from kitsu_mcp.app import READ_ONLY, mcp
from kitsu_mcp.client import get_client
from kitsu_mcp.formatters import task_summary
from kitsu_mcp.lookups import get_lookups
from kitsu_mcp.models import AssetDetail, AssetList, AssetSummary


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
    limit: int = 200,
    offset: int = 0,
) -> AssetList:
    """List a project's assets with their tasks, optionally filtered.

    project: project name or ID.
    asset_types / exclude_asset_types: asset type names (e.g. ["Environment"]).
    task_status_filters: task type name -> allowed status short names; all must match,
    e.g. {"Modelling": ["APP", "wip"], "Sculpting": ["WRA"]}. Matching is case-insensitive.
    """
    lookups = get_lookups()
    project_id = lookups.project(project)["id"]
    include = {n.lower() for n in asset_types or []}
    exclude = {n.lower() for n in exclude_asset_types or []}

    results = []
    for asset in get_client().get("data/assets/with-tasks", params={"project_id": project_id}):
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
        results.append(AssetSummary(id=asset["id"], name=asset["name"], type=type_name, tasks=tasks))

    results.sort(key=lambda a: ((a.type or "").lower(), a.name.lower()))
    return AssetList(total=len(results), assets=results[offset : offset + limit])


@mcp.tool(annotations=READ_ONLY, tags={"assets"})
def get_asset(asset_id: str) -> AssetDetail:
    """Get an asset's details and tasks."""
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
