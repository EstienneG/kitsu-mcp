from kitsu_mcp.app import READ_ONLY, tool
from kitsu_mcp.custom_fields import order
from kitsu_mcp.lookups import check_names, get_lookups
from kitsu_mcp.models import CustomField


@tool(annotations=READ_ONLY, tags={"browse"})
def list_custom_fields(project: str, entity_type: str | None = None) -> list[CustomField]:
    """List a project's custom fields (Kitsu "metadata descriptors"), in Kitsu's column order.

    project: name or ID. entity_type: Asset, Shot, Sequence, Episode or Edit (case-insensitive); all by default.
    get_asset / get_shot (and list_assets / list_shots with detail="full") show the values by `name`, and
    list_assets / list_shots filter on them with custom_field_filters. A "list" field only takes its `choices`.
    """
    lookups = get_lookups()
    project_id = lookups.project(project)["id"]
    descriptors = lookups.custom_fields(project_id)
    if entity_type:
        known = {"Asset", "Shot", "Sequence", "Episode", "Edit"} | {str(d.get("entity_type")) for d in descriptors}
        check_names("entity type", [entity_type], known)
        descriptors = [d for d in descriptors if str(d.get("entity_type") or "").lower() == entity_type.lower()]
    departments = lookups.index("departments")
    return [
        CustomField(
            name=d["name"],
            field_name=d.get("field_name") or d["name"],
            entity_type=d.get("entity_type") or "?",
            data_type=d.get("data_type") or "string",
            choices=[str(c) for c in d.get("choices") or []],
            departments=[departments.get(i, {}).get("name") or i for i in d.get("departments") or []],
            for_client=bool(d.get("for_client")),
        )
        for d in sorted(descriptors, key=lambda d: (str(d.get("entity_type")), *order(d)))
    ]
