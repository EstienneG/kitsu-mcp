import json

from fastmcp import Client

from kitsu_mcp.server import mcp


async def test_static_resources(fake):
    async with Client(mcp) as client:
        uris = {str(r.uri) for r in await client.list_resources()}
        assert {"kitsu://projects", "kitsu://task-types", "kitsu://task-statuses"} <= uris
        projects = json.loads((await client.read_resource("kitsu://projects"))[0].text)
    assert [p["name"] for p in projects] == ["Demo Short"]


async def test_template_resources(fake):
    async with Client(mcp) as client:
        overview = json.loads((await client.read_resource("kitsu://projects/p-1/overview"))[0].text)
        task = json.loads((await client.read_resource("kitsu://tasks/t-hero-mod"))[0].text)
    assert overview["tasks"] == 5
    assert task["entity"] == "Hero"


async def test_prompts_mention_the_tools_they_rely_on(fake):
    tool_names = {t.name for t in await mcp.list_tools()}
    async with Client(mcp) as client:
        prompts = await client.list_prompts()
        assert {p.name for p in prompts} == {
            "project_status_report",
            "review_queue",
            "my_day",
            "person_summary",
            "review_shot",
        }
        for prompt in prompts:
            args = {a.name: "X" for a in prompt.arguments or [] if a.required}
            text = (await client.get_prompt(prompt.name, args)).messages[0].content.text
            referenced = {name for name in tool_names if name in text}
            assert referenced, f"{prompt.name} references no tool"


async def test_list_resources_with_nothing_in_them(fake):
    """Resources call tool functions directly: an empty studio must give [], not crash."""
    fake.data["projects"] = [p for p in fake.data["projects"] if p["project_status_id"] != "ps-open"]
    fake.data["task_types"] = []
    async with Client(mcp) as client:
        assert json.loads((await client.read_resource("kitsu://projects"))[0].text) == []
        assert json.loads((await client.read_resource("kitsu://task-types"))[0].text) == []
