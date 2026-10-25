# kitsu-mcp

An [MCP](https://modelcontextprotocol.io) server for [Kitsu](https://www.cg-wire.com/kitsu), CGWire's production
tracker. Plug it into an AI agent (Mistral Vibe, Claude, Codex, ...) and ask about your production in plain
language: where a project stands, what is waiting for review, who is overloaded, what a preview movie shows, how
the schedule and budget look. With writes enabled, the agent can also comment, change statuses, assign, schedule,
log time and build review playlists; it is told to show you its plan and ask before writing.

It talks to Kitsu's API (Zou) with each person's own login, so everyone sees exactly what Kitsu lets them see.

**Which setup?** With a desktop or command-line agent (Vibe CLI, Claude Code, Codex), it runs on your machine:
see [Client setup](#client-setup). With Vibe Work or AI Studio, it runs once for the whole studio: ask
your pipeline or IT team to run the [hosted server](#hosted-server), then add it as a connector.

## What you can do

| You are | Ask things like | What the agent uses |
|---|---|---|
| **Producer / production manager** | "Where does the short stand, and which task types are behind schedule?" · "How many shots did each animator deliver per week this month?" · "What does the budget plan for the modeling department?" · "What changed on the project since Monday?" | progress per task type, overdue work, the production schedule and milestones, quotas, the budget, the activity feed |
| **Supervisor / lead** | "What is waiting for review in animation, oldest first?" · "Review the latest animation of SQ010 / SH020 against the last retake notes." · "Who on my team has the most open or overdue work?" · "Put today's wfa shots in a dailies playlist." | the review queue, comments and their history, the movie frames the comments point at, revision comparison, workload per person, playlists |
| **Artist** | "What should I work on today?" · "What did the supervisor say on my last upload?" · "Log 3 hours on Hero modeling for yesterday." · "Reply to Bob's note that it's fixed." | your tasks and notifications, the task's comments and previews, time logs, replies |
| **Pipeline / TD** | "Which shots in SQ020 are approved in layout but not started in animation?" · "List the assets cast in SH010 with their modeling status." · most other reads, straight from the API | asset, shot and casting lists with status and custom-field filters, `kitsu_get` for any `data/` read route |

In clients that show MCP prompts, ready-made ones cover the common requests: a project status report, a
supervisor's review queue, an artist's day, a person summary and a shot review.

## What it covers in Kitsu

| Kitsu | The agent can |
|---|---|
| Production tracking (assets, shots, sequences, episodes, tasks) | Search and filter tasks by type, status, department, assignee and due date; (with writes) comment, change statuses, assign and unassign; read any asset or shot, and any task with its comments, status history and previews |
| Production overview, statistics | Summarize progress per task type, overdue work, retakes, work waiting for review, unassigned work, time logged vs. estimated |
| Review and playlists | Show preview images, look at the frames of a movie that the comments point at, compare two revisions; list and read playlists, and (with writes) create and fill them |
| Breakdown / casting | Read which assets are in a shot, and which shots use an asset |
| Schedule, estimates | Read each task type's planned dates against its tasks' due dates, and the milestones; (with writes) change a task's dates and estimate |
| Quotas | Shots and frames per artist per day, week or month, in each of Kitsu's counting modes |
| Budget | Planned salary costs per person and department, computed as the Budget page does (producers and admins, as in Kitsu) |
| Timesheets, days off | Time a person logged per day and task, with their days off when Kitsu shows them to you; (with writes) log time |
| News feed, notifications | What changed on a project since a date; your notifications |
| Team, workload | People, departments, and open work per person |
| Custom fields (metadata columns) | Read them and filter assets and shots on them |
| Concepts, edits | Find them by name (no dedicated tools yet) |

Not covered: creating or deleting projects, assets, shots or tasks; editing asset and shot data (descriptions,
frame ranges, custom field values) or the breakdown; uploading previews; removing playlist entries; editing
budgets; and studio settings (task types, statuses, automations, permissions). Use Kitsu for those.

## Safe by default

- **Read-only unless you say otherwise.** Tools that change Kitsu only exist when the server runs with
  `KITSU_ALLOW_WRITE=true`.
- **Every write can be previewed.** Each write tool has a dry run that shows exactly what would change, and the
  agent is told to show you that plan and ask before writing.
- **Your permissions, not more.** Every call runs as you, with your Kitsu permissions. On a shared server, each
  person signs in with their own Kitsu login.
- **Where your password goes.** Locally it is stored in your agent's config file, in plain text, as for any
  local MCP server. On a hosted server it is sent with each request (HTTPS only) and kept in memory, never logged.

Limits: the agent sees still frames sampled from a movie, not motion or sound; Kitsu accounts with two-factor
authentication cannot log in yet.

## Client setup

Desktop and command-line agents start the server on your machine. You need a Kitsu account and
[uv](https://docs.astral.sh/uv/getting-started/installation/), a small Python tool runner (macOS and Linux:
`curl -LsSf https://astral.sh/uv/install.sh | sh`). Replace the Kitsu address, email and password below with
yours; the address is your Kitsu URL followed by `/api`.

### Mistral Vibe CLI

    vibe mcp add kitsu --transport stdio --command uvx --arg=--from --arg='kitsu-mcp[video]' --arg kitsu-mcp \
      --env KITSU_HOST=https://your-studio.cg-wire.com/api \
      --env KITSU_USER=you@example.com \
      --env KITSU_PASSWORD='your-password'

### Mistral Vibe Work and AI Studio

These run in the cloud, so they connect to your studio's [hosted server](#hosted-server) through a custom MCP
connector:

- **Vibe Work:** Connectors → + Add Connector → Custom MCP Connector. **AI Studio:** Connectors → Add.
- Each person adds their own connector. Name: `kitsu`. Server URL: `https://<your-server>/mcp`. Visibility:
  **Private**, so the connector carries only their login.
- Authentication: **Basic** with the person's Kitsu email and password. Where only a bearer token can be
  entered, use `email:password` as the token.

### Claude Code

    claude mcp add kitsu --scope user \
      -e KITSU_HOST=https://your-studio.cg-wire.com/api \
      -e KITSU_USER=you@example.com \
      -e KITSU_PASSWORD='your-password' \
      -- uvx --from 'kitsu-mcp[video]' kitsu-mcp

### Codex

    codex mcp add kitsu \
      --env KITSU_HOST=https://your-studio.cg-wire.com/api \
      --env KITSU_USER=you@example.com \
      --env KITSU_PASSWORD='your-password' \
      -- uvx --from 'kitsu-mcp[video]' kitsu-mcp

### Other MCP clients

Any client that runs local MCP servers can start it with:

    command: uvx --from 'kitsu-mcp[video]' kitsu-mcp
    env:     KITSU_HOST=https://your-studio.cg-wire.com/api
             KITSU_USER=you@example.com
             KITSU_PASSWORD=your-password

### Options

- The `[video]` extra (about 30 MB, downloaded once) lets the agent look inside preview movies. Use plain
  `uvx kitsu-mcp` to leave it out.
- Add `KITSU_ALLOW_WRITE=true` to the environment to let the agent change Kitsu (comments, statuses,
  assignments, ...); every write tool also has a [dry run](#dry-run).
- If your client does not refresh its tool list during a conversation, also add `KITSU_TOOL_GROUPS=all` (see
  [tool groups](#tool-groups)).
- All settings are in [Configuration](#configuration).

## Hosted server

Web agents (Vibe Work, AI Studio, ...) need the server at a public HTTPS URL. One server serves the
whole studio: each person connects with their own Kitsu login, and every call runs as them, with their Kitsu
permissions. Once it runs, people add it as a connector: see
[Mistral Vibe Work and AI Studio](#mistral-vibe-work-and-ai-studio).

**Run it.** Only `KITSU_HOST` is needed (no shared login). Deploy the image on a host that terminates HTTPS
(Fly.io, Render, a reverse proxy) and confirm it with `KITSU_BEHIND_TLS=true`:

    docker run -p 8000:8000 -e KITSU_HOST=https://your-studio.cg-wire.com/api -e KITSU_BEHIND_TLS=true \
      ghcr.io/estienneg/kitsu-mcp:latest

(or build it yourself with `docker build -t kitsu-mcp .`). Pin a version tag such as `:0.5.0` in production.

To try it locally without a proxy, run `KITSU_HOST=... uvx --from 'kitsu-mcp[video]' kitsu-mcp --http`, which
listens on 127.0.0.1:8000.

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
two-factor authentication cannot log in (the same holds locally).

## Configuration

| Variable | Default | |
|---|---|---|
| `KITSU_HOST` | required | Zou API URL, ending in `/api` |
| `KITSU_USER` / `KITSU_PASSWORD` | required over stdio | Kitsu login (over HTTP each caller sends their own) |
| `KITSU_ALLOW_WRITE` | `false` | Expose the write tools below |
| `KITSU_TOOL_GROUPS` | `write` | Tool groups listed from the start besides the core tools (`browse`, `activity`, `planning`, `review`, `write`, or `all`); the others come with `load_tools` |
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

Kitsu's flags on a status (done, retake, feedback request, in progress) do not always say what a studio means: an
OMIT status is often flagged done but means dropped, and a studio may flag a "could be better" (CBB) status as
retake while meaning done-but-improvable (set `KITSU_DONE_STATUSES=cbb` for that). So every status gets exactly one
**role** — `omitted`, `done`, `on_hold`, `retake`, `waiting_review`, `wip` or `todo` — and every count and filter
uses it (progress, overdue, waiting for review, workload, search). A status listed in one of the `KITSU_*_STATUSES`
settings above (names or short names, case-insensitive, checked in the order shown) takes that role; any other
status gets it from Kitsu's flags, in the order done > retake > feedback request > in progress > to do.

`list_task_statuses` shows each status's role and where it comes from, and reports configured names that
match no status. `project_overview` reports which statuses it counted as omitted and as
done-but-improvable.

## Tools

Arguments take names (case-insensitive) as well as IDs: projects, task types, departments, statuses and people.
`departments` filters (`search_tasks`, `workload`, `project_overview`) keep tasks whose task type belongs to
one of the departments, so the three tools agree; people's own departments are not used (`list_people` shows
them).

### Tool groups

Tools come in groups, so an agent does not start every conversation with all 48 of them. Only the **core** tools
are listed at first; the agent adds a group with `load_tools(groups=[...])` when the task needs it, and the server
tells the client its tool list changed. `KITSU_TOOL_GROUPS` lists groups from the start (default `write`, which
still needs `KITSU_ALLOW_WRITE`): set `all` for clients that do not refresh their tool list, or that only let the
model call listed tools. Loading a group only changes what is listed: the server accepts calls to any of its tools.
Both settings are read by `kitsu-mcp` at startup; a platform that imports `kitsu_mcp.server:mcp` directly gets the
defaults (core and write tools listed, write tools disabled).

### Tool list

| Group | Tools |
|---|---|
| Core (always listed) | `whoami`, `search` (assets, shots, sequences, episodes, edits, concepts and people by name), `list_projects`, `project_overview`, `search_tasks` (type, department, status, assignee, due dates, overdue, waiting feedback, group by assignee, ...), `get_task` (with comments, replies and acknowledgements; optionally its status history and uploaded previews), `get_person_tasks` (anyone's, or the user's own), `get_asset`, `get_shot`, `kitsu_get` (raw read of any Zou `data/` route), `refresh_cache`, `load_tools` |
| `browse` | `list_assets` (type, name and per-task-type status filters; `detail="compact"` or `"full"`), `list_shots`, `list_sequences`, `list_episodes`, `list_asset_types`, `list_task_types`, `list_task_statuses`, `list_custom_fields` (a project's custom columns: type, choices, departments; values show up by display name in `get_asset` / `get_shot`, and `list_assets` / `list_shots` filter on them with `custom_field_filters`), `get_casting` (a shot's, an episode's, a whole sequence's, or the shots an asset is in), `list_people`, `list_entities` / `get_entity` (concepts, edits, scenes, sequences, episodes) |
| `activity` | `project_activity` (comments, status changes and uploads since a date, by person or task type), `my_notifications` (the user's Kitsu inbox) |
| `planning` | `workload`, `timesheet` (time logged per day and task over a period, with days off when Kitsu shows them), `quotas` (shots and frames per artist per day, week or month, in the count modes of Kitsu's Quotas page), `production_schedule` (each task type's planned dates vs. its tasks' due dates, late and unscheduled task types, milestones), `budget` (planned salary costs per person and department, as Kitsu's Budget page) |
| `review` | `recent_previews` (latest uploads), `get_preview` (image or metadata, by entity or preview file), `download_previews`, `list_playlists`, `get_playlist`; with the `[video]` extra: `get_video_info`, `get_video_contact_sheet`, `get_video_frames`, `compare_revisions`, `review_video`, `download_video` |
| `structure` (opt-in) | `manage_project` (create, update, close, reopen, delete), `manage_episode`, `manage_sequence`, `manage_shot` (create, update, delete, restore), `manage_asset`, `manage_concept`, `manage_edit` (create, update, delete), `manage_task` (create tasks of a type on many entities, delete a task), `manage_scene` (create, rename, link shots, instance assets) |
| `production` (opt-in) | `task_action` (start a task, submit it for review), `publish_preview` (a file as the task's next revision, with a status; stdio only), `batch_tasks` (status, assign, unassign, priority or delete up to 100 tasks), `manage_comment` (edit, delete, delete a reply), `set_casting` (add, remove or replace the assets cast in a shot or episode) |
| `admin` (opt-in) | `manage_project_team`, `manage_project_settings` (task types, statuses, asset types and status automations a production uses), `manage_custom_field` (create, update, delete a metadata column), `manage_schedule` (task type dates, milestones), `manage_budget` (budget versions and salary lines), `manage_person` (accounts, departments, invitations), `manage_day_off` |
| `write` (opt-in) | `add_comment` (or a reply to a comment), `acknowledge_comment`, `set_task_status`, `assign_task` (or unassign), `update_task_schedule`, `log_time`, `create_playlist`, `add_to_playlist` (shots/assets with their latest preview), `manage_playlist` (rename, remove an entry, change an entry's preview, delete), `manage_my_notifications` (mark read, subscribe to a task), `manage_time` (set or delete a day's time) |

The 12 core tools cost a model about 2,700 tokens of context; every group listed, about 17,000.

### Links

Detail results carry a `url` to the Kitsu page (asset, shot, task, preview in the player, playlist),
and preview metadata a `download_url` to the original upload. They open in a browser signed in to Kitsu, so
movies are watched and downloaded there rather than passed through the server.

### Dry run

Every write tool takes `dry_run=True`: it runs the same lookups and checks with reads only and
returns the plan instead of writing: `would` (the action in one line), `requests` (method, path and payload,
exactly what the real call sends), `before`/`after` for the fields that change (status, assignees, dates,
estimate, time logged), and `warnings` (e.g. Kitsu may refuse a status your role cannot set). If a check fails
(archived status, inactive person, start date after due date, over 24 h logged in a day), `verdict` is
`would_fail` with the `reason`, and the real call refuses with the same reason. Invalid arguments (bad IDs,
unknown names) are errors either way. Agents are told to dry-run first and show the user the plan.

**Deletes** (`action="delete"` on the `manage_*` tools) also need `confirm=True`; without it they refuse, so
an agent cannot delete by picking the wrong action. Kitsu cancels (hides) a shot, asset, concept or edit that
has tasks rather than deleting it; `force=True` deletes it and its tasks for good, and the dry run says which
will happen. Projects can only be deleted once closed.

### Prompts and resources

**Prompts:** `project_status_report`, `review_queue`, `my_day`, `person_summary`, `review_shot`.

**Resources:** `kitsu://projects`, `kitsu://task-types`, `kitsu://task-statuses`,
`kitsu://projects/{project}/overview`, `kitsu://tasks/{task_id}`.

## Video

The video tools look inside movie previews. They need the `video` extra (PyAV, which bundles ffmpeg, and
Pillow), so no system ffmpeg is required. The setup commands above and the Docker image include it; with pip,
install `kitsu-mcp[video]`. Without the extra the tools are still listed but answer with an error saying how to
install it (`download_video` works either way). `get_preview` says when a preview is a video.

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

## Compatibility

| | Supported | Tested in CI |
|---|---|---|
| Zou (Kitsu API) | 1.0.43 and later | 1.0.43 and 1.0.97, with the `cgwire/cgwire` image |
| gazu | 1.3.x (`>=1.3,<2`) | the locked version |
| Python | 3.12 and later | 3.12 |

`curl https://your-studio.cg-wire.com/api` shows a Zou version. Older Zou versions may work but are not tested.
Report anything that breaks on a supported version as an issue.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests, the code layout and releases,
[CHANGELOG.md](CHANGELOG.md) for what changed, and [SECURITY.md](SECURITY.md) to report a vulnerability.

## License

MIT: see [LICENSE](LICENSE). Free to use, modify and distribute, including commercially, provided the
copyright notice is kept; no warranty.
