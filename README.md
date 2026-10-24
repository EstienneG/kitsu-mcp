# kitsu-mcp

Read-only MCP server (FastMCP + Gazu) for a Kitsu/Zou instance. Runs locally over stdio.

## Install

You only need [uv](https://docs.astral.sh/uv/getting-started/installation/):

    curl -LsSf https://astral.sh/uv/install.sh | sh

Then register the server with your agent, using your Kitsu login.

**Mistral Vibe**

    vibe mcp add kitsu --transport stdio --command uvx --arg kitsu-mcp \
      --env KITSU_HOST=https://your-studio.cg-wire.com/api \
      --env KITSU_USER=you@example.com \
      --env KITSU_PASSWORD='your-password'

**Claude Code**

    claude mcp add kitsu --scope user \
      -e KITSU_HOST=https://your-studio.cg-wire.com/api \
      -e KITSU_USER=you@example.com \
      -e KITSU_PASSWORD='your-password' \
      -- uvx kitsu-mcp

The password is stored in plain text in the agent's config file (e.g. `~/.vibe/config.toml`).

## Development

    cp .env.example .env   # fill in KITSU_USER / KITSU_PASSWORD
    uv run kitsu-mcp       # reads .env from the current directory

Release: bump `version` in `pyproject.toml`, then `uv build && uv publish`.

## Tools

whoami, list_projects, list_task_types, list_task_statuses, list_asset_types,
list_assets (type + per-task-type status filters), get_asset, get_task (with comments),
my_tasks, kitsu_get (raw GET on any Zou route).
