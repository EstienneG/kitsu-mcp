import contextlib

import pytest
from fastmcp.exceptions import ToolError


async def test_whoami(call):
    assert (await call("whoami"))["full_name"] == "Alice Martin"


async def test_list_projects_open_by_default(call):
    projects = await call("list_projects")
    assert [p["name"] for p in projects] == ["Demo Short"]
    assert projects[0]["status"] == "Open"
    assert len(await call("list_projects", include_closed=True)) == 2


async def test_list_task_types_hides_archived(call):
    assert "Old" not in {t["name"] for t in await call("list_task_types")}


async def test_list_asset_types_accepts_project_name(call):
    assert {t["name"] for t in await call("list_asset_types", project="Demo Short")} == {"Character", "Environment"}


async def test_list_assets_filters(call):
    result = await call("list_assets", project="p-1", asset_types=["character"], compact=False)
    assert [a["name"] for a in result["assets"]] == ["Hero"]
    assert result["assets"][0]["tasks"][0] == {
        "id": "t-hero-mod",
        "task_type": "Modeling",
        "status": "wfa",
        "assignees": ["Alice Martin"],
        "due_date": "2026-10-01",
        "last_comment_date": None,
        "last_preview_file_id": None,
    }
    result = await call("list_assets", project="p-1", task_status_filters={"modeling": ["WIP"]})
    assert [a["name"] for a in result["assets"]] == ["Forest"]
    result = await call("list_assets", project="p-1", exclude_asset_types=["Environment"], name_contains="er")
    assert [a["name"] for a in result["assets"]] == ["Hero"]


async def test_list_assets_paginates(call):
    result = await call("list_assets", project="p-1", limit=1, offset=1)
    assert result["total"] == 2
    assert [a["name"] for a in result["assets"]] == ["Forest"]


async def test_get_asset(call):
    asset = await call("get_asset", asset_id="a-hero")
    assert asset["type"] == "Character"
    assert [t["task_type"] for t in asset["tasks"]] == ["Modeling"]


async def test_get_task_with_comments(call):
    task = await call("get_task", task_id="t-hero-mod", comment_limit=1)
    assert task["entity"] == "Hero"
    assert task["status"] == "wfa"
    assert task["comments"] == [
        {
            "date": "2026-10-02T10:00:00",
            "author": "Alice Martin",
            "status": "wfa",
            "text": "Ready for review",
            "preview_ids": ["pf-hero"],
        }
    ]


async def test_get_task_without_comments(call):
    assert (await call("get_task", task_id="t-hero-mod", include_comments=False))["comments"] is None


async def test_unknown_project_is_a_readable_error(call):
    with pytest.raises(ToolError, match="Unknown project 'Nope'"):
        await call("list_assets", project="Nope")


async def test_kitsu_get_strips_api_prefix(call, fake):
    await call("kitsu_get", path="/api/data/task-types")
    assert fake.calls[-1][1] == "data/task-types"


async def test_refresh_cache(call, fake):
    await call("list_task_types")
    await call("refresh_cache")
    await call("list_task_types")
    assert sum(path == "data/task-types" for _, path, _ in fake.calls) == 2


@pytest.mark.parametrize(
    "path", ["auth/logout", "data/playlists/pl-1/build/mp4", "data/../auth/logout", "actions/tasks/t/comment"]
)
async def test_kitsu_get_refuses_non_data_or_side_effect_routes(call, fake, path):
    with pytest.raises(ToolError, match="kitsu_get (only allows|refuses)"):
        await call("kitsu_get", path=path)
    assert all(p != path for _, p, _ in fake.calls)


async def test_list_assets_skips_canceled_and_sorts(call, fake):
    fake.data["assets"].append({**fake.data["assets"][0], "id": "a-old", "name": "Old Hero", "canceled": True})
    fake.data["assets"].append({**fake.data["assets"][0], "id": "a-aaa", "name": "Archer"})
    names = [a["name"] for a in (await call("list_assets", project="p-1"))["assets"]]
    assert names == ["Archer", "Hero", "Forest"]


@pytest.mark.parametrize(
    "path",
    [
        "data/%2e%2e/auth/logout",
        "data/.%2e/auth/logout",
        "data/%2E%2E/auth/logout",
        "data/playlists/X/%62uild/mp4",
        "data/playlists/X/bui%6cd/mp4",
        "data/playlists/X/build%2fmp4",
        "data\\..\\auth/logout",
        "data/./../auth/logout",
        "data/x?y=1",
        "data//build",
        "data/x#frag",
    ],
)
async def test_kitsu_get_refuses_encoded_and_escaped_routes(call, fake, path):
    with pytest.raises(ToolError, match="kitsu_get"):
        await call("kitsu_get", path=path)
    assert all(method != "GET" or p != path for method, p, _ in fake.calls)
    assert not any(p.startswith(("auth", "data/playlists/X")) for _, p, _ in fake.calls)


@pytest.mark.parametrize("path", ["data/task-types", "/api/data/task-types", "data/task-types/", "data/user.context"])
async def test_kitsu_get_allows_plain_data_routes(call, fake, path):
    with contextlib.suppress(ToolError):  # unknown fake routes are fine, only the filter matters
        await call("kitsu_get", path=path)
    assert fake.calls[-1][1] == path.lstrip("/").removeprefix("api/")
