import pytest
from fastmcp.exceptions import ToolError

from kitsu_mcp import validation
from kitsu_mcp.lookups import Lookups, unknown_message
from tests.fakes import FakeClient


@pytest.fixture
def strict_ids(monkeypatch):
    monkeypatch.setattr(validation, "id_pattern", validation.UUID)


@pytest.mark.parametrize("value", ["SH100", "not-a-uuid", "", " ", "../x", "a1b2c3d4"])
def test_object_id_rejects_non_uuids_with_a_pointer(strict_ids, value):
    with pytest.raises(ToolError, match="use list_shots"):
        validation.object_id(value, "shot", "list_shots")


def test_object_id_accepts_uuids(strict_ids):
    uuid = " 1258B106-125e-499a-a19b-a3a3410638e3 "
    assert validation.object_id(uuid, "task", "search_tasks") == uuid.strip()


async def test_tools_reject_names_as_ids_before_calling_kitsu(call, fake, strict_ids):
    for tool, args in [
        ("get_task", {"task_id": "not-an-id"}),
        ("get_asset", {"asset_id": "Hero"}),
        ("get_shot", {"shot_id": "SH010"}),
        ("task_history", {"task_id": "x"}),
        ("get_playlist", {"playlist_id": "Dailies"}),
    ]:
        with pytest.raises(ToolError, match="is not a"):
            await call(tool, **args)
    assert fake.calls == []


@pytest.mark.parametrize(
    "tool, args",
    [
        ("search_tasks", {"project": "p-1", "limit": -1}),
        ("search_tasks", {"project": "p-1", "limit": 0}),
        ("search_tasks", {"project": "p-1", "limit": 501}),
        ("search_tasks", {"project": "p-1", "offset": -1}),
        ("list_assets", {"project": "p-1", "limit": -1}),
        ("list_shots", {"project": "p-1", "limit": -1}),
        ("get_task", {"task_id": "t-hero-mod", "comment_limit": 0}),
    ],
)
async def test_page_sizes_are_bounded(call, tool, args):
    with pytest.raises(ToolError, match="(?i)validation|greater|less"):
        await call(tool, **args)


def test_unknown_message_suggests_close_matches():
    message = unknown_message("asset type", "Charcters", ["Characters", "Environment", "Props"])
    assert "Did you mean: Characters?" in message
    assert "Did you mean: LAST DROP?" in unknown_message("project", "last", ["LAST DROP", "Wing It"])


def test_ambiguous_person_lists_names_and_emails():
    fake = FakeClient()
    fake.data["people"].append({**fake.data["people"][0], "id": "person-alice-2", "email": "alice2@example.com"})
    with pytest.raises(ToolError) as error:
        Lookups(fake, ttl=300).person("Alice Martin")  # type: ignore[arg-type]
    assert "Alice Martin (alice@example.com) = person-alice" in str(error.value)
    assert "alice2@example.com" in str(error.value)


@pytest.mark.parametrize(
    "tool, args, label",
    [
        ("list_assets", {"project": "p-1", "asset_types": ["Charcters"]}, "asset type in this project 'Charcters'"),
        ("list_assets", {"project": "p-1", "exclude_asset_types": ["Props"]}, "asset type in this project 'Props'"),
        ("list_assets", {"project": "p-1", "task_status_filters": {"Modelingg": ["wip"]}}, "task type 'Modelingg'"),
        ("list_assets", {"project": "p-1", "task_status_filters": {"Modeling": ["wipp"]}}, "task status 'wipp'"),
        ("list_shots", {"project": "p-1", "sequence": "sq999x"}, "sequence 'sq999x'"),
        ("list_shots", {"project": "p-1", "episode": "E99"}, "episode 'E99'"),
        ("list_sequences", {"project": "p-1", "episode": "nope"}, "episode 'nope'"),
    ],
)
async def test_unknown_filter_names_are_errors_not_empty_results(call, tool, args, label):
    with pytest.raises(ToolError, match=f"Unknown {label}"):
        await call(tool, **args)


async def test_known_filter_names_still_work(call):
    assert (await call("list_assets", project="p-1", asset_types=["character"]))["total"] == 1
    assert (await call("list_shots", project="p-1", sequence="SQ010"))["total"] == 2
    assert (await call("list_shots", project="p-1", sequence="seq-1"))["total"] == 2
