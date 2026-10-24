"""Custom fields (Kitsu "metadata descriptors"): definitions, typed values and filters.

Kitsu stores an entity's custom field values in its `data` dict under each field's `field_name`, mostly as
text (booleans come back as "true" / "false"). Tools show them by display name, typed.
"""

import json
from typing import Any

from fastmcp.exceptions import ToolError

from kitsu_mcp.lookups import Lookups, Record, unknown_message
from kitsu_mcp.validation import iso_date

FilterValue = str | int | float | bool | None
CustomFieldFilters = dict[str, list[FilterValue]]

_TRUE, _FALSE = {"true", "yes", "1", "on"}, {"false", "no", "0", "off", ""}


def fields_for(lookups: Lookups, project_id: str, entity_type: str) -> list[Record]:
    """A project's custom fields for one entity type ("Asset", "Shot", ...), in Kitsu's display order."""
    wanted = entity_type.lower()
    found = [d for d in lookups.custom_fields(project_id) if (d.get("entity_type") or "").lower() == wanted]
    return sorted(found, key=order)


def order(descriptor: Record) -> tuple:
    position = descriptor.get("position")
    return (position is None, position or 0, str(descriptor.get("name") or "").lower())


def typed(descriptor: Record, raw: Any) -> Any:
    """A stored value as its field's type: booleans as true/false (unset is false, as Kitsu shows an unticked
    box), numbers as numbers, tag lists as lists. Unset or blank values are None (booleans: false)."""
    kind = descriptor.get("data_type")
    if kind == "boolean":
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in _TRUE if raw is not None else False
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if kind == "number" and isinstance(raw, str):
        try:
            number = float(raw)
        except ValueError:
            return raw
        return int(number) if number.is_integer() else number
    if kind == "taglist" and isinstance(raw, str):
        return [tag.strip() for tag in raw.split(",") if tag.strip()]
    if kind == "checklist" and isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return raw
    return raw


def values(descriptors: list[Record], data: dict | None) -> dict[str, Any]:
    """An entity's custom field values by display name, every field of its type included (None when unset)."""
    data = data or {}
    return {d["name"]: typed(d, data.get(d.get("field_name"))) for d in descriptors}


def compile_filters(filters: CustomFieldFilters | None, descriptors: list[Record], what: str) -> list[tuple]:
    """Check filters (display name or field_name -> allowed values) and normalize them for `matches`.

    Unknown fields, values a "list" field does not offer, and values that are not of the field's type are
    errors. `what`: "shot" or "asset", for messages.
    """
    if not filters:
        return []
    by_key: dict[str, Record] = {}
    for d in descriptors:
        for key in (d.get("name"), d.get("field_name")):
            if key:
                by_key.setdefault(str(key).strip().lower(), d)
    compiled = []
    for key, allowed in filters.items():
        descriptor = by_key.get(key.strip().lower())
        if descriptor is None:
            if not descriptors:
                raise ToolError(f"Unknown custom field '{key}': this project has no {what} custom fields")
            names = [str(d["name"]) for d in descriptors]
            raise ToolError(unknown_message(f"{what} custom field", key, names))
        if not isinstance(allowed, list) or not allowed:
            raise ToolError(f"custom_field_filters['{key}'] must be a non-empty list of allowed values")
        compiled.append((descriptor, {_wanted(descriptor, v) for v in allowed}))
    return compiled


def _wanted(descriptor: Record, value: FilterValue) -> Any:
    """A filter value normalized like `_key` normalizes stored ones."""
    name, kind = descriptor["name"], descriptor.get("data_type")
    if value is None:
        return None
    if kind == "boolean":
        text = str(value).strip().lower()
        if isinstance(value, bool) or text in _TRUE | _FALSE - {""}:
            return value if isinstance(value, bool) else text in _TRUE
        raise ToolError(f"'{name}' is a yes/no field: filter it with true or false, not {value!r}")
    if kind == "number":
        try:
            return float(value)
        except (TypeError, ValueError) as error:
            raise ToolError(f"'{name}' is a number field: {value!r} is not a number") from error
    if kind == "date":
        return iso_date(str(value), f"custom_field_filters['{name}']")
    text = str(value).strip().lower()
    if kind == "list":
        choices = {str(c).strip().lower(): c for c in descriptor.get("choices") or []}
        if choices and text not in choices:
            raise ToolError(unknown_message(f"value for '{name}'", str(value), list(choices.values())))
    return text


def _key(descriptor: Record, value: Any) -> Any:
    """A typed stored value, normalized for comparison with filter values."""
    if value is None or isinstance(value, bool):
        return value
    if descriptor.get("data_type") == "number":
        try:
            return float(value)
        except (TypeError, ValueError):
            return str(value).lower()
    if descriptor.get("data_type") == "date":
        return str(value)[:10]
    return str(value).strip().lower()


def matches(compiled: list[tuple], data: dict | None) -> bool:
    """True if the entity's value for every filtered field is one of the allowed values (a tag list: any tag).
    None in the allowed values matches an unset field."""
    data = data or {}
    for descriptor, allowed in compiled:
        value = typed(descriptor, data.get(descriptor.get("field_name")))
        candidates = value if isinstance(value, list) and value else [value]
        if not any(_key(descriptor, v) in allowed for v in candidates):
            return False
    return True


def extra_data(descriptors: list[Record], data: dict | None, shown: frozenset[str] = frozenset()) -> dict[str, Any]:
    """The rest of an entity's `data`: non-empty values that are not custom fields nor shown elsewhere (`shown`)."""
    custom = {d.get("field_name") for d in descriptors}
    return {k: v for k, v in (data or {}).items() if k not in custom and k not in shown and v not in (None, "")}


def detail_fields(lookups: Lookups, entity: dict, entity_type: str, shown: frozenset[str] = frozenset()) -> dict:
    """`custom_fields` and `extra_data` of an asset or shot, for its detail model."""
    descriptors = fields_for(lookups, entity["project_id"], entity_type) if entity.get("project_id") else []
    return {
        "custom_fields": values(descriptors, entity.get("data")),
        "extra_data": extra_data(descriptors, entity.get("data"), shown),
    }
