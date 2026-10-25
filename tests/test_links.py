"""Links to the Kitsu web app and direct downloads, built from Kitsu's own routes."""

from kitsu_mcp import links
from kitsu_mcp import lookups as lookups_module


async def test_detail_tools_link_to_kitsu(call):
    asset = await call("get_asset", asset_id="a-hero")
    assert asset["url"] == "http://kitsu.test/productions/p-1/assets/a-hero"
    shot = await call("get_shot", shot_id="s-1")
    assert shot["url"] == "http://kitsu.test/productions/p-1/shots/s-1"
    task = await call("get_task", task_id="t-sh010-anim")
    assert task["url"] == "http://kitsu.test/productions/p-1/shots/tasks/t-sh010-anim"
    previews = {p["id"]: p for p in (await call("get_task", task_id="t-sh010-anim", include_previews=True))["previews"]}
    assert previews["pf-sh010"]["url"] == "http://kitsu.test/productions/p-1/shots/tasks/t-sh010-anim/previews/pf-sh010"
    assert (
        previews["pf-sh010"]["download_url"] == "http://kitsu.test/api/movies/originals/preview-files/pf-sh010/download"
    )
    image = await call("get_preview", preview_file_id="pf-hero", show=False)
    assert image["download_url"] == "http://kitsu.test/api/pictures/originals/preview-files/pf-hero/download"
    playlist = await call("get_playlist", playlist_id="pl-1")
    assert playlist["url"] == "http://kitsu.test/productions/p-1/playlists/pl-1"


def test_tv_show_links_go_through_an_episode(fake):
    fake.data["projects"][0]["production_type"] = "tvshow"
    lookups_module.get_lookups().clear()
    assert links.entity_url("p-1", "shot", "s-1", "ep-1") == "http://kitsu.test/productions/p-1/episodes/ep-1/shots/s-1"
    # Assets outside any episode live in Kitsu's "main" pack; playlists for every episode under "all".
    assert links.entity_url("p-1", "asset", "a-1", "") == "http://kitsu.test/productions/p-1/episodes/main/assets/a-1"
    assert links.playlist_url("p-1", "pl-1") == "http://kitsu.test/productions/p-1/episodes/all/playlists/pl-1"
    assert (
        links.task_url("p-1", "t-1", "Shot", "ep-1", "pf-1")
        == "http://kitsu.test/productions/p-1/episodes/ep-1/shots/tasks/t-1/previews/pf-1"
    )
    assert (
        links.task_url("p-1", "t-1", "Episode", "ep-1") == "http://kitsu.test/productions/p-1/episodes/ep-1/tasks/t-1"
    )
    # A shot or task outside any episode (its sequence has none) uses the plain production route.
    assert links.entity_url("p-1", "shot", "s-1", None) == "http://kitsu.test/productions/p-1/shots/s-1"
    assert links.task_url("p-1", "t-1", "Asset", None) == "http://kitsu.test/productions/p-1/assets/tasks/t-1"


def test_links_never_carry_a_login_embedded_in_the_host(fake):
    fake.settings.host = "https://proxyuser:proxypw@kitsu.example/api"
    assert links.entity_url("p-1", "shot", "s-1") == "https://kitsu.example/productions/p-1/shots/s-1"
    assert links.download_url({"id": "pf-1", "extension": "mp4"}) == (
        "https://kitsu.example/api/movies/originals/preview-files/pf-1/download"
    )


def test_task_on_an_episode_links_to_that_episode(fake):
    """Zou's full task has no `episode` when the entity is an Episode; Kitsu then uses the entity ID."""
    from kitsu_mcp.formatters import task_detail

    fake.data["projects"][0]["production_type"] = "tvshow"
    lookups_module.get_lookups().clear()
    task = {
        "id": "t-ep",
        "project_id": "p-1",
        "entity_id": "ep-1",
        "entity": {"id": "ep-1", "name": "E01"},
        "task_type": {"name": "Storyboard", "for_entity": "Episode"},
        "persons": [],
    }
    assert task_detail(task).url == "http://kitsu.test/productions/p-1/episodes/ep-1/tasks/t-ep"
