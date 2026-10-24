"""Custom fields (Kitsu metadata descriptors): definitions, values on entities, filters."""

import pytest
from fastmcp.exceptions import ToolError


async def test_list_custom_fields(call):
    fields = await call("list_custom_fields", project="Demo Short")
    assert [(f["entity_type"], f["name"]) for f in fields] == [
        ("Asset", "DATE RENDU"),
        ("Asset", "Rigged"),
        ("Shot", "key_shot"),  # position 1
        ("Shot", "Anim Level"),  # position 2
    ]
    level = fields[3]
    assert level == {
        "name": "Anim Level",
        "field_name": "anim_level",
        "entity_type": "Shot",
        "data_type": "list",
        "choices": ["⭐", "⭐⭐", "⭐⭐⭐"],
        "departments": ["Animation"],
        "for_client": False,
    }


async def test_list_custom_fields_by_entity_type(call):
    assert [f["name"] for f in await call("list_custom_fields", project="p-1", entity_type="asset")] == [
        "DATE RENDU",
        "Rigged",
    ]
    assert await call("list_custom_fields", project="p-1", entity_type="Episode") == []
    with pytest.raises(ToolError, match="Unknown entity type 'Shots'.*Did you mean: Shot"):
        await call("list_custom_fields", project="p-1", entity_type="Shots")


async def test_get_shot_and_asset_show_typed_values_by_display_name(call):
    shot = await call("get_shot", shot_id="s-1")
    assert shot["custom_fields"] == {"key_shot": True, "Anim Level": "⭐⭐"}
    assert shot["extra_data"] == {"handle_in": 4}
    assert "data" not in shot
    other = await call("get_shot", shot_id="s-2")
    # Booleans are stored as "false"; frame_in/frame_out are already top-level fields.
    assert other["custom_fields"] == {"key_shot": False, "Anim Level": None}
    assert other["extra_data"] == {}
    asset = await call("get_asset", asset_id="a-hero")
    assert asset["custom_fields"] == {"DATE RENDU": "2026-11-06", "Rigged": True}
    assert asset["extra_data"] == {}  # empty "resolution" left out
    forest = await call("get_asset", asset_id="a-forest")  # data is null
    assert forest["custom_fields"] == {"DATE RENDU": None, "Rigged": False}


async def test_lists_show_custom_fields_only_in_full_detail(call):
    compact = await call("list_shots", project="p-1")
    assert all(s["custom_fields"] is None for s in compact["shots"])
    full = await call("list_shots", project="p-1", detail="full")
    assert full["shots"][0]["custom_fields"] == {"key_shot": True, "Anim Level": "⭐⭐"}
    assets = await call("list_assets", project="p-1", detail="full")
    assert {a["name"]: a["custom_fields"]["Rigged"] for a in assets["assets"]} == {"Hero": True, "Forest": False}
    assert all(a["custom_fields"] is None for a in (await call("list_assets", project="p-1"))["assets"])


@pytest.mark.parametrize(
    "filters, expected",
    [
        ({"key_shot": [True]}, ["SH010"]),
        ({"KEY_SHOT": ["false"]}, ["SH020"]),
        ({"Anim Level": ["⭐⭐", "⭐⭐⭐"]}, ["SH010"]),
        ({"anim_level": [None]}, ["SH020"]),  # field_name works too; null = unset
        ({"key_shot": [True, False], "Anim Level": ["⭐"]}, []),
    ],
)
async def test_list_shots_custom_field_filters(call, filters, expected):
    result = await call("list_shots", project="p-1", custom_field_filters=filters)
    assert [s["name"] for s in result["shots"]] == expected


async def test_list_assets_custom_field_filters(call):
    result = await call("list_assets", project="p-1", custom_field_filters={"rigged": [True]})
    assert [a["name"] for a in result["assets"]] == ["Hero"]
    result = await call("list_assets", project="p-1", custom_field_filters={"DATE RENDU": ["2026-11-06"]})
    assert [a["name"] for a in result["assets"]] == ["Hero"]


async def test_text_filters_are_case_insensitive(call, fake):
    fake.data["custom_fields"].append(
        {
            "id": "md-notes",
            "project_id": "p-1",
            "name": "Look",
            "field_name": "look",
            "entity_type": "Shot",
            "data_type": "string",
            "choices": [],
            "departments": [],
            "position": 3,
        }
    )
    fake.data["shots"][1]["data"]["look"] = "Night Exterior"
    result = await call("list_shots", project="p-1", custom_field_filters={"look": ["night exterior"]})
    assert [s["name"] for s in result["shots"]] == ["SH020"]


@pytest.mark.parametrize(
    "tool, filters, error",
    [
        ("list_shots", {"Anim Lvl": ["⭐"]}, r"Unknown shot custom field 'Anim Lvl'.*Did you mean: Anim Level"),
        ("list_shots", {"Rigged": [True]}, r"Unknown shot custom field 'Rigged'.*Valid values: Anim Level, key_shot"),
        ("list_shots", {"Anim Level": ["⭐⭐⭐⭐⭐"]}, r"Unknown value for 'Anim Level'.*⭐⭐⭐"),
        ("list_shots", {"key_shot": ["maybe"]}, "yes/no field"),
        ("list_shots", {"key_shot": []}, "non-empty list"),
        ("list_assets", {"DATE RENDU": ["next week"]}, "YYYY-MM-DD"),
    ],
)
async def test_bad_custom_field_filters_are_errors(call, tool, filters, error):
    with pytest.raises(ToolError, match=error):
        await call(tool, project="p-1", custom_field_filters=filters)


async def test_project_without_custom_fields_says_so(call, fake):
    fake.data["custom_fields"] = []
    with pytest.raises(ToolError, match="this project has no shot custom fields"):
        await call("list_shots", project="p-1", custom_field_filters={"key_shot": [True]})


async def test_descriptors_are_cached_per_project(call, fake):
    for _ in range(3):
        await call("list_shots", project="p-1", custom_field_filters={"key_shot": [True]})
    await call("get_shot", shot_id="s-1")
    assert sum(path.endswith("metadata-descriptors") for _, path, _ in fake.calls) == 1
    await call("refresh_cache")
    await call("list_shots", project="p-1")
    assert sum(path.endswith("metadata-descriptors") for _, path, _ in fake.calls) == 2
