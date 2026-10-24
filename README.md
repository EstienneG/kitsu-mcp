# kitsu-mcp

An [MCP](https://modelcontextprotocol.io) server for [Kitsu](https://www.cg-wire.com/kitsu), CGWire's production
tracker. It lets an AI agent read a Kitsu production the way a production manager or supervisor would: where a
project stands, what is waiting for review, who is overloaded, what changed on a shot, what a preview movie shows.
Write tools (comments, status changes, assignments, schedules, time logs, playlists) are opt-in.

It talks to the Zou API with each person's own Kitsu login, so everyone sees exactly what Kitsu lets them see.
It runs on the user's machine (stdio) for desktop and CLI agents, or hosted once for a whole studio (HTTP) for
web agents.

Examples of what to ask:
- "Where does our short film stand? What is late?"
- "What is waiting for my review today?"
- "Who on the animation team has too much on their plate this week?"
- "Show me the latest compositing preview of sh010 and the comments on it."

## Quick start

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
and a Kitsu account. Any MCP client that runs local servers can start it with:

    command: uvx kitsu-mcp
    env:     KITSU_HOST=https://your-studio.cg-wire.com/api
             KITSU_USER=you@example.com
             KITSU_PASSWORD=your-password

Use `uvx --from 'kitsu-mcp[video]' kitsu-mcp` as the command for the [video tools](#video). Web agents need the
[hosted server](#hosted-server) instead.

## Client setup

**AI Studio** and **Vibe Work** run in the cloud: they connect to a [hosted server](#hosted-server) at an HTTPS
URL. Each person signs in with their own Kitsu login. See [Mistral connectors](#mistral-connectors-ai-studio-vibe-work-le-chat).

**Vibe CLI**

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

**Codex**

    codex mcp add kitsu \
      --env KITSU_HOST=https://your-studio.cg-wire.com/api \
      --env KITSU_USER=you@example.com \
      --env KITSU_PASSWORD='your-password' \
      -- uvx kitsu-mcp

Local clients store the password in plain text in their config file (e.g. `~/.vibe/config.toml`). Add
`KITSU_ALLOW_WRITE=true` to expose the write tools; every write tool also has a [dry run](#tools).

## Hosted server

Web agents need the server at a public HTTPS URL. One server serves the whole studio: each person connects with
their own Kitsu login, and every call runs as them, with their Kitsu permissions.

**Run it.** Only `KITSU_HOST` is needed (no shared login). Deploy the image on a host that terminates HTTPS
(Fly.io, Render, a reverse proxy) and confirm it with `KITSU_BEHIND_TLS=true`:

    docker run -p 8000:8000 -e KITSU_HOST=https://your-studio.cg-wire.com/api -e KITSU_BEHIND_TLS=true \
      ghcr.io/estienneg/kitsu-mcp:latest

(or build it yourself with `docker build -t kitsu-mcp .`). Pin a version tag such as `:0.3.0` in production.

To try it locally without a proxy, run `KITSU_HOST=... kitsu-mcp --http`, which listens on 127.0.0.1:8000.

The supported entry point is `kitsu-mcp --http` (`--host` / `--port`, or `KITSU_HTTP_HOST` / `PORT`): it
applies the TLS check below, which `fastmcp run` would skip. The MCP endpoint is `/mcp`; `/health` answers
for health checks. The image runs as an unprivileged user.

**Logging in.** Clients send the person's Kitsu login in the `Authorization` header: `Basic` with their Kitsu
email and password, or, where only a bearer token can be entered, `Bearer email:password`.

**HTTPS is required.** Callers send their Kitsu password with every request, so the server refuses to listen
on anything but localhost unless the operator confirms TLS terminates in front of it (`--behind-tls` or
`KITSU_BEHIND_TLS=true`; deliberately not set in the image). It never logs credentials and keeps them only in
memory, under keys derived with a per-process secret. Only logins Kitsu accepted are kept, for an hour of
inactivity. Repeated rejected logins for one account are slowed down (a Kitsu outage does not count), while a
login Kitsu accepted in the last day is always let through, so guessing at someone's email cannot lock them
out. Spraying many emails from one address is not throttled; fine at studio scale, otherwise rate-limit at the
proxy. Listing the tools works without a login (it is metadata only); every tool call needs one.

Differences from stdio: `download_previews` and `download_video` are hidden (they would write to the server's
disk, not the user's); give people the `url` (Kitsu page) or `download_url` (original upload) instead, which
open in their own Kitsu browser session. The video tools cache movies per user, and `KITSU_VIDEO_CACHE_MB` caps
all users' movies together. Write tools follow `KITSU_ALLOW_WRITE` as over stdio. Kitsu accounts with
two-factor authentication cannot log in this way.

### Mistral connectors (AI Studio, Vibe Work, Le Chat)

AI Studio, Vibe Work and Le Chat all use the hosted server through the same custom MCP connector:

- **AI Studio:** Connectors → Add. **Vibe Work:** Connectors → + Add Connector → Custom MCP Connector.
  **Le Chat:** Connectors → Custom MCP connector.
- Each person adds their own connector. Name: `kitsu`. Server URL: `https://<your-server>/mcp`. Visibility:
  **Private**, so the connector carries only their login.
- Authentication: **Basic** with the person's Kitsu email and password. Where only a bearer token can be
  entered, use `email:password` as the token.

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

## Compatibility

| | Supported | Tested in CI |
|---|---|---|
| Zou (Kitsu API) | 1.0.43 and later | 1.0.43 and 1.0.97, with the `cgwire/cgwire` image |
| gazu | 1.3.x (`>=1.3,<2`) | the locked version |
| Python | 3.12 and later | 3.12 |

`curl https://your-studio.cg-wire.com/api` shows a Zou version. Older Zou versions may work but are not tested.
Report anything that breaks on a supported version as an issue.

## Development

    cp .env.example .env   # fill in KITSU_USER / KITSU_PASSWORD
    uv run kitsu-mcp       # reads .env from the current directory
    uv run pytest          # tests run against an in-memory fake Kitsu, no credentials needed
    uv run ruff check . && uv run ruff format --check . && uv run pyright

Integration tests run the read tools against a real Zou, seeded with a tiny production (writes are blocked):

    docker run -d -p 8090:80 cgwire/cgwire:1.0.73-1.0.97-01
    uv run python tests/integration/seed.py http://127.0.0.1:8090/api
    KITSU_TEST_HOST=http://127.0.0.1:8090/api uv run pytest tests/integration

See [CONTRIBUTING.md](CONTRIBUTING.md), [CHANGELOG.md](CHANGELOG.md) and [SECURITY.md](SECURITY.md).

Layout (`src/kitsu_mcp/`): `config.py` settings, `client.py` HTTP client (login, re-login, retries,
error mapping), `lookups.py` cached reference data and name resolution, `models.py` output schemas,
`formatters.py` payload → model conversion, `production.py` project-wide task views, `plans.py` write plans
(dry run), `custom_fields.py` custom field values and filters, `tools/` one module per domain,
`resources.py`, `prompts.py`, `auth.py` per-caller credentials, `http.py` HTTP mode (hidden local tools,
`/health`, TLS guard), `links.py` Kitsu web links.

Release: bump `version` in `pyproject.toml` and add a `CHANGELOG.md` entry, merge, then tag it
(`git tag v0.3.1 && git push origin v0.3.1`).
The Release workflow checks the tag matches the version, runs the checks, then publishes the package to
PyPI and the Docker image to `ghcr.io/estienneg/kitsu-mcp` (tags `0.3.1`, `0.3` and `latest`).
PyPI uses trusted publishing, so no token is stored: the `kitsu-mcp` project on PyPI has this repository
as its publisher (workflow `release.yml`, environment `pypi`).

## Tools

Project, task type, department, status and person arguments take names (case-insensitive) or IDs.
`departments` filters (`search_tasks`, `workload`, `project_overview`) keep tasks whose task type belongs to
one of the departments, so the three tools agree; people's own departments are not used (`list_people` shows
them).

| Area | Tools |
|---|---|
| Meta | `whoami`, `search` (assets, shots, sequences, episodes, edits, concepts and people by name), `kitsu_get` (raw read of any Zou `data/` route), `refresh_cache` |
| Activity | `project_activity` (comments, status changes and uploads since a date, by person or task type), `my_notifications` (the user's Kitsu inbox) |
| Projects | `list_projects`, `list_task_types`, `list_task_statuses`, `list_asset_types`, `project_overview` |
| Assets | `list_assets` (type, name and per-task-type status filters; `detail="compact"` or `"full"`), `get_asset`, `get_casting` (either way) |
| Shots | `list_episodes`, `list_sequences`, `list_shots`, `get_shot`, `get_casting` |
| Custom fields | `list_custom_fields` (a project's custom columns: type, choices, departments); values show up by display name in `get_asset` / `get_shot` (and `detail="full"` lists), and `list_assets` / `list_shots` filter on them with `custom_field_filters` |
| Tasks | `search_tasks` (type, department, status, assignee, due dates, overdue, waiting feedback, group by assignee, ...), `get_task` (with comments, replies and acknowledgements), `task_history`, `my_tasks` |
| People | `list_people`, `get_person_tasks`, `workload`, `timesheet` (time logged per day and task over a period) |
| Previews | `recent_previews` (latest uploads), `get_preview` (image or metadata, by entity or preview file), `list_task_previews`, `download_previews`, `list_playlists`, `get_playlist` |
| Video (`[video]` extra) | `get_video_info`, `get_video_contact_sheet`, `get_video_frames`, `compare_revisions`, `review_video`, `download_video` |
| Write (opt-in) | `add_comment`, `reply_to_comment`, `acknowledge_comment`, `set_task_status`, `assign_task`, `update_task_schedule`, `log_time`, `create_playlist`, `add_to_playlist` (shots/assets with their latest preview) |

**Context cost.** Clients send every tool's name, description and arguments to the model at the start of a
conversation. With all 48 tools (writes enabled) that is about 9,000 tokens (about 7,100 read-only), plus about
200 for the server instructions; results come on top, and list tools return compact rows to keep them small.
A test keeps the tool list under a fixed budget. To trim it, hide tool groups your agent does not need: most
clients let you turn individual tools off, and write tools stay hidden unless `KITSU_ALLOW_WRITE=true`.

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
