async def test_list_sequences(call):
    assert [s["name"] for s in await call("list_sequences", project="Demo Short")] == ["SQ010"]


async def test_list_episodes_empty_for_short(call):
    assert await call("list_episodes", project="Demo Short") == []


async def test_list_shots(call):
    result = await call("list_shots", project="p-1", sequence="sq010", detail="full")
    assert result["total"] == 2
    first = result["shots"][0]
    assert (first["name"], first["frame_in"], first["frame_out"], first["nb_frames"]) == ("SH010", 1, 48, 48)
    assert {t["task_type"] for t in first["tasks"]} == {"Animation", "Compositing"}


async def test_list_shots_status_filter(call):
    result = await call("list_shots", project="p-1", task_status_filters={"Animation": ["todo"]})
    assert [s["name"] for s in result["shots"]] == ["SH020"]


async def test_get_shot(call):
    shot = await call("get_shot", shot_id="s-1")
    assert shot["sequence"] == "SQ010"
    assert shot["fps"] == 24.0


async def test_casting_both_ways(call):
    assert await call("get_shot_casting", shot_id="s-1") == [
        {"asset_id": "a-hero", "name": "Hero", "asset_type": "Character", "occurrences": 1, "label": "animate"}
    ]
    cast_in = await call("get_asset_cast_in", asset_id="a-hero")
    assert [(c["shot"], c["sequence"]) for c in cast_in] == [("SH010", "SQ010")]


async def test_list_sequences_by_episode(call, fake):
    fake.data["episodes"] = [{"id": "ep-1", "name": "E01", "project_id": "p-1"}]
    fake.data["sequences"].append({"id": "seq-2", "name": "SQ020", "project_id": "p-1", "parent_id": "ep-1"})
    assert [s["name"] for s in await call("list_sequences", project="p-1", episode="e01")] == ["SQ020"]
    assert [s["name"] for s in await call("list_sequences", project="p-1", episode="ep-1")] == ["SQ020"]


async def test_frame_range_falls_back_to_data(call):
    shot = await call("get_shot", shot_id="s-2")
    assert (shot["frame_in"], shot["frame_out"], shot["nb_frames"]) == (101, 172, 72)


def test_frames_tolerates_odd_values():
    from kitsu_mcp.tools.shots import _frames

    values = ["12", "12.0", " 7 ", "²", "--5", "abc", "inf", True, None, 3.9]
    assert [_frames({"f": v}, "f") for v in values] == [12, 12, 7, None, None, None, None, None, None, 3]
