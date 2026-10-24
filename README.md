# kitsu-mcp

MCP server (FastMCP + Gazu) for a Kitsu/Zou instance. Runs locally over stdio, or hosted over HTTP as a
Le Chat / AI Studio connector where each person logs in with their own Kitsu account. Read-only by default;
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

## Hosted connector (Le Chat, AI Studio)

Le Chat and AI Studio run in Mistral's cloud, so they need the server at a public HTTPS URL. One server serves
everyone: each person adds their own private connector with their Kitsu login, and every call runs as them,
with their Kitsu permissions.

**Run it.** Only `KITSU_HOST` is needed (no shared login). Deploy the image on a host that terminates HTTPS
(Fly.io, Render, a reverse proxy) and confirm it with `KITSU_BEHIND_TLS=true`:

    docker run -p 8000:8000 -e KITSU_HOST=https://your-studio.cg-wire.com/api -e KITSU_BEHIND_TLS=true \
      ghcr.io/estienneg/kitsu-mcp:latest

(or build it yourself with `docker build -t kitsu-mcp .`). Pin a version tag such as `:0.2.0` in production.

To try it locally without a proxy, run `KITSU_HOST=... kitsu-mcp --http`, which listens on 127.0.0.1:8000.

The supported entry point is `kitsu-mcp --http` (`--host` / `--port`, or `KITSU_HTTP_HOST` / `PORT`): it
applies the TLS check below, which `fastmcp run` would skip. The MCP endpoint is `/mcp`; `/health` answers
for health checks. The image runs as an unprivileged user.

**HTTPS is required.** Callers send their Kitsu password with every request, so the server refuses to listen
on anything but localhost unless the operator confirms TLS terminates in front of it (`--behind-tls` or
`KITSU_BEHIND_TLS=true`; deliberately not set in the image). It never logs credentials and keeps them only in
memory, under keys derived with a per-process secret. Only logins Kitsu accepted are kept, for an hour of
inactivity. Repeated rejected logins for one account are slowed down (a Kitsu outage does not count), while a
login Kitsu accepted in the last day is always let through, so guessing at someone's email cannot lock them
out. Spraying many emails from one address is not throttled; fine at studio scale, otherwise rate-limit at the
proxy. Listing the tools works without a login
(it is metadata only); every tool call needs one.

**Each user** (AI Studio → Connectors → Add, or Le Chat → Connectors → Custom MCP connector):
- URL: `https://<your-server>/mcp`, visibility **Private**
- Authentication: **Basic**, with their Kitsu email and password. Where only a bearer token can be entered,
  use `email:password` as the token.

Differences from stdio: `download_previews` and `download_video` are hidden (they would write to the server's
disk, not the user's); give people the `url` (Kitsu page) or `download_url` (original upload) instead, which
open in their own Kitsu browser session. The
video tools cache movies per user, and `KITSU_VIDEO_CACHE_MB` caps all users' movies together. Write tools
follow `KITSU_ALLOW_WRITE` as over stdio. Kitsu accounts with two-factor authentication cannot log in this
way.

## Configuration

| Variable | Default | |
|---|---|---|
| `KITSU_HOST` | required | Zou API URL, ending in `/api` |
| `KITSU_USER` / `KITSU_PASSWORD` | required over stdio | Kitsu login (over HTTP each caller sends their own) |
| `KITSU_ALLOW_WRITE` | `false` | Expose the write tools below |
| `KITSU_CACHE_TTL` | `300` | Seconds to cache projects, task types, statuses, people, departments, custom fields |
| `KITSU_TIMEOUT` | `30` | Per-request timeout (seconds) |
| `KITSU_MAX_RETRIES` | `3` | Attempts for reads failing with a server or network error |
| `KITSU_VIDEO_CACHE_DIR` | system temp | Where the video tools cache movies (`kitsu-mcp-videos/`) |
| `KITSU_VIDEO_CACHE_MB` | `1024` | Movie cache size; least recently used movies are deleted past it |
| `KITSU_VIDEO_MAX_MB` | `500` | Largest movie the video tools download |
| `KITSU_OMITTED_STATUSES` | `omit,na,n/a,omitted,cancelled,canceled` | Statuses meaning "dropped": left out of progress and open work |
| `KITSU_DONE_STATUSES` | (none) | Statuses meaning "finished", whatever Kitsu flags (e.g. `cbb` for "could be better") |
| `KITSU_ON_HOLD_STATUSES` | `stand by,standby,pause,paused,blocked,on hold` | Open but paused: never overdue |
| `KITSU_REVIEW_STATUSES` | (none) | Extra statuses meaning "waiting for review/approval" |
| `KITSU_RETAKE_STATUSES` | (none) | Extra statuses meaning "sent back for changes" |
| `KITSU_DRY_RUN_LOG` | (none) | JSONL file each write-tool dry run is appended to |

Variables can also come from a `.env` file in the working directory.

### Status roles

Kitsu's flags on a status (done, retake, feedback request, in progress) do not always say what a studio
means: an OMIT status is often flagged done but means dropped, and a studio may flag a "could be better" (CBB)
status as retake while meaning done-but-improvable (set `KITSU_DONE_STATUSES=cbb` for that). So every status gets exactly one **role** — `omitted`, `done`, `on_hold`, `retake`,
`waiting_review`, `wip` or `todo` — and every count and filter uses it (progress, overdue, waiting for
review, workload, search). A status listed in one of the `KITSU_*_STATUSES` settings above (names or short
names, case-insensitive, checked in the order shown) takes that role; any other status gets it from
Kitsu's flags, in the order done > retake > feedback request > in progress > to do.

`list_task_statuses` shows each status's role and where it comes from, and reports configured names that
match no status. `project_overview` reports which statuses it counted as omitted and as
done-but-improvable.

## Development

    cp .env.example .env   # fill in KITSU_USER / KITSU_PASSWORD
    uv run kitsu-mcp       # reads .env from the current directory
    uv run pytest          # tests run against an in-memory fake Kitsu, no credentials needed
    uv run ruff check . && uv run ruff format --check . && uv run pyright

Layout (`src/kitsu_mcp/`): `config.py` settings, `client.py` HTTP client (login, re-login, retries,
error mapping), `lookups.py` cached reference data and name resolution, `models.py` output schemas,
`formatters.py` payload → model conversion, `production.py` project-wide task views, `plans.py` write plans
(dry run), `custom_fields.py` custom field values and filters, `tools/` one module per domain,
`resources.py`, `prompts.py`, `auth.py` per-caller credentials, `http.py` HTTP mode (hidden local tools,
`/health`, TLS guard), `links.py` Kitsu web links.

Release: bump `version` in `pyproject.toml`, merge, then tag it (`git tag v0.2.0 && git push origin v0.2.0`).
The Release workflow checks the tag matches the version, runs the checks, and publishes the Docker image to
`ghcr.io/estienneg/kitsu-mcp` (tags `0.2.0`, `0.2` and `latest`). Publishing the Python package to PyPI
is a separate, manual `uv build && uv publish`.

## Tools

Project, task type, department, status and person arguments take names (case-insensitive) or IDs.
`departments` filters (`search_tasks`, `workload`, `project_overview`) keep tasks whose task type belongs to
one of the departments, so the three tools agree; people's own departments are not used (`list_people` shows
them).

| Area | Tools |
|---|---|
| Meta | `whoami`, `kitsu_get` (raw read of any Zou `data/` route), `refresh_cache` |
| Projects | `list_projects`, `list_task_types`, `list_task_statuses`, `list_asset_types`, `project_overview` |
| Assets | `list_assets` (type, name and per-task-type status filters; `detail="compact"` or `"full"`), `get_asset`, `get_casting` (either way) |
| Shots | `list_episodes`, `list_sequences`, `list_shots`, `get_shot`, `get_casting` |
| Custom fields | `list_custom_fields` (a project's custom columns: type, choices, departments); values show up by display name in `get_asset` / `get_shot` (and `detail="full"` lists), and `list_assets` / `list_shots` filter on them with `custom_field_filters` |
| Tasks | `search_tasks` (type, department, status, assignee, due dates, overdue, waiting feedback, group by assignee, ...), `get_task`, `task_history`, `my_tasks` |
| People | `list_people`, `get_person_tasks`, `workload` |
| Previews | `recent_previews` (latest uploads), `get_preview` (image or metadata, by entity or preview file), `list_task_previews`, `download_previews`, `list_playlists`, `get_playlist` |
| Video (`[video]` extra) | `get_video_info`, `get_video_contact_sheet`, `get_video_frames`, `compare_revisions`, `review_video`, `download_video` |
| Write (opt-in) | `add_comment`, `set_task_status`, `assign_task`, `update_task_schedule`, `log_time`, `create_playlist`, `add_to_playlist` (shots/assets with their latest preview) |

**Links:** detail results carry a `url` to the Kitsu page (asset, shot, task, preview in the player, playlist),
and preview metadata a `download_url` to the original upload. They open in a browser signed in to Kitsu, so
movies are watched and downloaded there rather than passed through the server.

**Dry run.** Every write tool takes `dry_run=True`: it runs the same lookups and checks with reads only and
returns the plan instead of writing: `would` (the action in one line), `requests` (method, path and payload,
exactly what the real call sends), `before`/`after` for the fields that change (status, assignees, dates,
estimate, time logged), and `warnings` (e.g. Kitsu may refuse a status your role cannot set). If a check fails
(archived status, inactive person, start date after due date, over 24 h logged in a day), `verdict` is
`would_fail` with the `reason`, and the real call refuses with the same reason. Invalid arguments (bad IDs,
unknown names) are errors either way. Agents are told to dry-run first and show the user the plan.

**Resources:** `kitsu://projects`, `kitsu://task-types`, `kitsu://task-statuses`,
`kitsu://projects/{project}/overview`, `kitsu://tasks/{task_id}`.

**Prompts:** `project_status_report`, `review_queue`, `my_day`, `person_summary`, `review_shot`.

## Video

The video tools look inside movie previews. They need the optional `video` extra (PyAV, which
bundles ffmpeg, and Pillow), so no system ffmpeg is required:

    uvx --from 'kitsu-mcp[video]' kitsu-mcp      # or: pip install 'kitsu-mcp[video]'

Use that as the command when registering the server (e.g. `-- uvx --from 'kitsu-mcp[video]' kitsu-mcp`
for Claude Code). Without the extra the tools are still listed but answer with an error saying how
to install it (`download_video` works either way). `get_preview` says when a
preview is a video.

- Movies are fetched at Kitsu's low-resolution playback quality by default (`quality="original"` for
  the uploaded file) and cached per preview file and quality (see the `KITSU_VIDEO_*` settings).
- Tools take a `preview_file_id`, or an `entity_id` (shot or asset) to use its current preview.
- Frames are numbered from 1, like Kitsu's player. Frame arguments accept frame numbers (`37`),
  timecodes (`"00:00:01:12"`, HH:MM:SS:FF), times (`"1.5s"`) and percentages (`"50%"`).
  `review_video` finds the frames a task's comments point at: Kitsu's `v3 00:00:01:12 (37)` tags,
  timecodes, "frame 37", "2.5s", and frames with drawn annotations.
- Limits: at most 16 frames per call, grids at most 1568 px on a side, single frames at most
  1280 px. The agent only sees sampled still frames: no motion in between and no audio. Every image
  costs context, so start with `get_video_contact_sheet` and zoom in with `get_video_frames`.

## License

MIT: see [LICENSE](LICENSE). Free to use, modify and distribute, including commercially, provided the
copyright notice is kept; no warranty.
