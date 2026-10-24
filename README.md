# kitsu-mcp

Read-only MCP server (FastMCP + Gazu) for a Kitsu/Zou instance. Runs locally over stdio.

## Setup

    cp .env.example .env   # fill in KITSU_USER / KITSU_PASSWORD

## Register

    claude mcp add kitsu --scope user -- uv run --directory ~/.superset/projects/kitsu-mcp server.py
    codex mcp add kitsu -- uv run --directory ~/.superset/projects/kitsu-mcp server.py

## Tools

whoami, list_projects, list_task_types, list_task_statuses, list_asset_types,
list_assets (type + per-task-type status filters), get_asset, get_task (with comments),
my_tasks, kitsu_get (raw GET on any Zou route).
