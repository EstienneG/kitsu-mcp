import re

from fastmcp.exceptions import ToolError

from kitsu_mcp import custom_fields as cf
from kitsu_mcp import links
from kitsu_mcp.app import READ_ONLY, tool
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


def match_types(
    wanted: list[str] | None, project_types: list[str], studio_types: set[str], *, strict: bool
) -> set[str]:
    """Lower-case names of the project's asset types that `wanted` refers to.

    For each name: the type with exactly that name, else every type that starts with it as whole words
    ("Characters" matches "Characters - PFE 2028", "Set" matches "Set Dressing" but not "Asset"). A name
    that matches no project type is an error when `strict` (an include filter), and for an exclude filter
    only when no type in the whole studio has that name (excluding a type a project lacks is harmless).
    """
    matched: set[str] = set()
    lowered = {" ".join(t.split()).lower(): t for t in project_types}
    studio = {" ".join(t.split()).lower() for t in studio_types}
    for name in wanted or []:
        key = " ".join(name.split()).lower()
        hits = {key} if key in lowered else {t for t in lowered if key and _starts_with_words(t, key)}
        if hits:
            matched |= hits
        elif strict or (key not in studio and not any(_starts_with_words(t, key) for t in studio)):
            if not project_types:
                raise ToolError(f"Unknown asset type '{name}': this project has no asset types")
            check_names("asset type in this project", [name], set(project_types))
    return matched


def _starts_with_words(name: str, prefix: str) -> bool:
    """True if `name` begins with `prefix` (or its plural/singular) followed by a word boundary."""
    stem = prefix.removesuffix("s") if len(prefix) > 3 else prefix
    return re.match(rf"{re.escape(stem)}s?(?!\w)", name) is not None


def matches_status_filters(tasks: list, status_filters: dict[str, list[str]] | None) -> bool:
    """True if, for every task type in the filter, the entity has a task of that type in an allowed status."""
    if not status_filters:
        return True
    by_type = {(t.task_type or "").lower(): (t.status or "").lower() for t in tasks}
    return all(
        by_type.get(task_type.lower()) in {s.lower() for s in allowed} for task_type, allowed in status_filters.items()
    )


@tool(annotations=READ_ONLY, tags={"browse"})
def list_assets(
    project: str,
    asset_types: list[str] | None = None,
    exclude_asset_types: list[str] | None = None,
    task_status_filters: dict[str, list[str]] | None = None,
    name_contains: str | None = None,
    custom_field_filters: cf.CustomFieldFilters | None = None,
    detail: Detail = "compact",
    limit: Limit = 100,
    offset: Offset = 0,
) -> AssetList:
    """List a project's assets with their tasks, optionally filtered.

    detail="compact" (default) gives each asset's tasks as {task type: status}; detail="full" returns
    full task rows (IDs, assignees, due dates, latest preview), several times larger. get_asset has the details.
    project: project name or ID.
    asset_types / exclude_asset_types: asset type names, matched against the types this project uses:
    an exact name, else every type starting with it as whole words ("Characters" also matches
    "Characters - PFE 2028"). Excluding a type the project does not use is fine.
    task_status_filters: task type name -> allowed status short names; all must match,
    e.g. {"Modelling": ["APP", "wip"], "Sculpting": ["WRA"]}. Matching is case-insensitive.
    custom_field_filters: custom field (display name or field_name, see list_custom_fields) -> allowed
    values; all must match, e.g. {"Rigged": [true]}. Text is case-insensitive; null matches an unset
    field (an unset yes/no field is false).
    detail="full" also gives each asset's custom_fields.
    """
    lookups = get_lookups()
    project_id = lookups.project(project)["id"]
    check_status_filters(task_status_filters, lookups)
    descriptors = cf.fields_for(lookups, project_id, "Asset")
    field_filters = cf.compile_filters(custom_field_filters, descriptors, "asset")
    client = get_client()
    project_types = [t["name"] for t in client.get(f"data/projects/{project_id}/asset-types")]
    studio_types = {t["name"] for t in lookups.index("asset_types").values()}
    include = match_types(asset_types, project_types, studio_types, strict=True)
    exclude = match_types(exclude_asset_types, project_types, studio_types, strict=False)
    if include and include <= exclude:
        raise ToolError("asset_types and exclude_asset_types cancel out: nothing would be listed")

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
        if not cf.matches(field_filters, asset.get("data")):
            continue
        tasks = [task_summary(t, lookups) for t in asset.get("tasks") or []]
        if not matches_status_filters(tasks, task_status_filters):
            continue
        if detail == "compact":
            results.append(AssetSummary(id=asset["id"], name=asset["name"], type=type_name, statuses=statuses(tasks)))
        else:
            custom = cf.values(descriptors, asset.get("data"))
            results.append(
                AssetSummary(id=asset["id"], name=asset["name"], type=type_name, tasks=tasks, custom_fields=custom)
            )

    results.sort(key=lambda a: ((a.type or "").lower(), a.name.lower()))
    return AssetList(total=len(results), assets=results[offset : offset + limit])


@tool(annotations=READ_ONLY, tags={"core"})
def get_asset(asset_id: str) -> AssetDetail:
    """Get an asset's details, custom field values (by display name; list_custom_fields explains them) and tasks."""
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
        **cf.detail_fields(lookups, asset, "Asset"),
        tasks=[task_summary(t, lookups) for t in tasks],
        url=links.entity_url(asset.get("project_id"), "asset", asset["id"], asset.get("episode_id")),
    )
