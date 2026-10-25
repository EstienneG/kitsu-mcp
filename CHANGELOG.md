# Changelog

All notable changes. Versions follow [semantic versioning](https://semver.org); before 1.0, a minor version may
change behaviour (called out under **Changed**).

## Unreleased

## 0.4.0 — 2026-10-25

### Added
- Tool groups. A conversation starts with 12 core tools (about 2,500 tokens instead of 9,000); `load_tools`
  adds the `browse`, `activity`, `planning`, `review` or `write` group when a task needs it, and the server
  tells the client its tool list changed. `KITSU_TOOL_GROUPS` lists groups from the start (default `write`;
  `all` for clients that do not refresh their tool list). Groups only change what is listed: the server
  accepts calls to any of its tools, and write tools still need `KITSU_ALLOW_WRITE`.

- `planning` tools: `quotas` (output per artist per day, week or month, as Kitsu's Quotas page, in its four
  count modes),
  `production_schedule` (task types' planned dates against their tasks' due dates, late task types,
  milestones) and `budget` (planned salary costs per person and department, computed as Kitsu does).
- `timesheet` lists the person's days off in the period (when Kitsu lets the caller see them).
- `assign_task(remove=True)` unassigns someone, and reports it when Kitsu refuses (it skips tasks silently).

### Changed
- **Only the 12 core tools are listed at first** (`refresh_cache` among them, so agents can refetch names
  without loading a group). Agents add the rest with `load_tools`. If your client does not refresh its tool
  list when told to (or only lets the model call listed tools), set `KITSU_TOOL_GROUPS=all` to list every
  tool from the start, as before.
- Fewer tools for the same features (48 to 44), so agents see a shorter list: `my_tasks` is
  `get_person_tasks` without a person; `task_history` and `list_task_previews` are `get_task` with
  `include_history` / `include_previews`; `reply_to_comment` is `add_comment` with `reply_to`.
- Source reorganised into packages: `kitsu/` (Kitsu client, lookups, production views, models), `server/`
  (the FastMCP app, tool groups, HTTP mode, prompts, resources) and `tools/` by area, with `review/` and
  `write/` split per subject. `kitsu_mcp.server:mcp` is unchanged; other module paths moved (for example
  `kitsu_mcp.client` is now `kitsu_mcp.kitsu.client`).
- README rewritten for Kitsu users: what you can do by role, what it covers in Kitsu, safety, and client
  setup with the Mistral clients first. Development, layout and release notes moved to CONTRIBUTING.md.

## 0.3.2 — 2026-10-24

### Added
- `project_activity`: what changed on a project since a date (comments, status changes, uploads), filtered by
  person, task type or name, with a count per person.
- `my_notifications`: the user's Kitsu inbox, unread first.
- `search`: find assets, shots, sequences, episodes, edits, concepts and people by name, across projects.
- `timesheet`: time a person logged over a period, per day and per task.
- Write tools `reply_to_comment` and `acknowledge_comment`, with dry runs. Acknowledging never toggles an
  acknowledgement off.
- `get_task` comments carry their ID, replies and who acknowledged them; `my_day` starts from notifications.
- README: the tool list's context cost, and a test that keeps it under a budget.
- Compatibility: supported Zou and gazu versions in the README, and CI integration tests that run the read
  tools against real Zou 1.0.43 and 1.0.97 (`tests/integration`).
- `CHANGELOG.md`, `SECURITY.md` and `CONTRIBUTING.md`.

### Changed
- gazu is pinned to `>=1.3,<2` (1.2 lacks an exception this server imports).

## 0.3.1 — 2026-10-24

### Changed
- README centered on Kitsu: a client-agnostic quick start, then setups for AI Studio, Vibe Work, Vibe CLI,
  Claude Code and Codex. The hosted server is documented for any web agent, with the Mistral connector steps in
  their own section.

## 0.3.0 — 2026-10-24

### Added
- Published on PyPI (`uvx kitsu-mcp`), from the release workflow with trusted publishing.

### Changed
- `KITSU_DONE_STATUSES` defaults to empty: statuses follow Kitsu's own flags unless a studio opts in. Set
  `KITSU_DONE_STATUSES=cbb` to keep counting a "could be better" status as done.
- `.env.example` lists every setting with its default.

## 0.2.0 — 2026-10-24

First tagged release, published as a Docker image (`ghcr.io/estienneg/kitsu-mcp`).

- Read tools for projects, assets, shots, casting, tasks, people, workload, previews and playlists, with
  status roles (done, omitted, on hold, waiting review, retake) that every count and filter follows.
- Video tools (`[video]` extra): contact sheets, frames, revision comparison, comment-driven review.
- Opt-in write tools (comments, status, assignment, schedule, time logs, playlists), each with a dry run.
- Custom fields and department filters.
- HTTP mode for hosted connectors, with per-caller Kitsu logins, a TLS guard and a login throttle.
- Links to Kitsu pages and original downloads.
