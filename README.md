# kitsu-mcp

MCP server (FastMCP + Gazu) for a Kitsu/Zou instance. Runs locally over stdio. Read-only by default;
write tools are opt-in.

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

## Configuration

| Variable | Default | |
|---|---|---|
| `KITSU_HOST` | required | Zou API URL, ending in `/api` |
| `KITSU_USER` / `KITSU_PASSWORD` | required | Kitsu login |
| `KITSU_ALLOW_WRITE` | `false` | Expose the write tools below |
| `KITSU_CACHE_TTL` | `300` | Seconds to cache projects, task types, statuses, people |
| `KITSU_TIMEOUT` | `30` | Per-request timeout (seconds) |
| `KITSU_MAX_RETRIES` | `3` | Attempts for reads failing with a server or network error |

Variables can also come from a `.env` file in the working directory.

## Development

    cp .env.example .env   # fill in KITSU_USER / KITSU_PASSWORD
    uv run kitsu-mcp       # reads .env from the current directory
    uv run pytest          # tests run against an in-memory fake Kitsu, no credentials needed
    uv run ruff check . && uv run ruff format --check . && uv run pyright

Layout (`src/kitsu_mcp/`): `config.py` settings, `client.py` HTTP client (login, re-login, retries,
error mapping), `lookups.py` cached reference data and name resolution, `models.py` output schemas,
`formatters.py` payload → model conversion, `production.py` project-wide task views, `tools/` one
module per domain, `resources.py`, `prompts.py`.

Release: bump `version` in `pyproject.toml`, then `uv build && uv publish`.

## Tools

Project, task type, status and person arguments take names (case-insensitive) or IDs.

| Area | Tools |
|---|---|
| Meta | `whoami`, `kitsu_get` (raw GET on any Zou route), `refresh_cache` |
| Projects | `list_projects`, `list_task_types`, `list_task_statuses`, `list_asset_types`, `project_overview` |
| Assets | `list_assets` (type, name and per-task-type status filters), `get_asset`, `get_asset_cast_in` |
| Shots | `list_episodes`, `list_sequences`, `list_shots`, `get_shot`, `get_shot_casting` |
| Tasks | `search_tasks` (type, status, assignee, due dates, overdue, ...), `get_task`, `task_history`, `my_tasks` |
| People | `list_people`, `get_person_tasks`, `workload` |
| Previews | `get_preview` (image), `get_preview_file`, `list_task_previews`, `download_previews`, `list_playlists`, `get_playlist` |
| Video (`[video]` extra) | `get_video_info`, `get_video_contact_sheet`, `get_video_frames`, `compare_revisions`, `review_video`, `download_video` |
| Write (opt-in) | `add_comment`, `set_task_status`, `assign_task`, `update_task_schedule`, `log_time` |

**Resources:** `kitsu://projects`, `kitsu://task-types`, `kitsu://task-statuses`,
`kitsu://projects/{project}/overview`, `kitsu://tasks/{task_id}`.

**Prompts:** `project_status_report`, `review_queue`, `my_day`, `person_summary`.
