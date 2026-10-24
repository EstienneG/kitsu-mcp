# Changelog

All notable changes. Versions follow [semantic versioning](https://semver.org); before 1.0, a minor version may
change behaviour (called out under **Changed**).

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
