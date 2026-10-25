# Contributing

Issues and pull requests are welcome. For a new tool or a behaviour change, open an issue first to agree on
the shape.

## Setup

You need [uv](https://docs.astral.sh/uv/). Then:

    uv sync
    cp .env.example .env   # only to run the server against your own Kitsu
    uv run kitsu-mcp       # reads .env from the current directory

## Checks

Every pull request must pass these, as CI does:

    uv run pytest                                  # unit tests, in-memory fake Kitsu, no credentials
    uv run ruff check . && uv run ruff format --check .
    uv run pyright

CI also runs `tests/integration` against real Zou versions (1.0.43 and 1.0.97), seeded with a tiny
production; writes are blocked. Add to them when a change depends on what Zou returns. To run them locally:

    docker run -d -p 8090:80 cgwire/cgwire:1.0.73-1.0.97-01
    uv run python tests/integration/seed.py http://127.0.0.1:8090/api
    KITSU_TEST_HOST=http://127.0.0.1:8090/api uv run pytest tests/integration

Add `KITSU_TEST_WRITES=1` to also run the write tools for real (`tests/integration/test_live_writes.py`). They
only run against `127.0.0.1` or `localhost`, and clean up their own project; never use them on a Kitsu you
care about. CI sets it, since its container is thrown away after each run.

**Context budgets.** Clients send every listed tool's name, description and arguments to the model at the
start of a conversation. The 12 core tools are about 2,500 tokens, plus about 300 for the server
instructions; with every group listed (60 tools, writes enabled) about 13,500. Tests keep the core list
(`tests/test_groups.py`) and the full list (`tests/test_registry.py`) under fixed budgets: raise them
deliberately when a tool earns its place, and prefer putting new tools in a group rather than in core.

## Layout

`src/kitsu_mcp/`:

- `__init__.py` the `kitsu-mcp` entry point; `config.py` settings.
- `kitsu/` talking to Kitsu, independent of the MCP server and tools: `client.py` HTTP client (login,
  re-login, retries, error mapping), `auth.py` per-caller credentials, `lookups.py` cached reference data and
  name resolution, `production.py` project-wide task views, `plans.py` write plans (dry run),
  `custom_fields.py`, `links.py` Kitsu web links, `validation.py`, `video.py` movie decoding, `models/` output
  schemas by area, `formatters.py` payload → model conversion.
- `server/` what MCP clients reach besides tools: `app.py` the FastMCP app and `@tool`, `groups.py` tool
  groups and `load_tools`, `http.py` HTTP mode (hidden local tools, `/health`, TLS guard), `prompts.py`,
  `resources.py`. `kitsu_mcp.server:mcp` is the app with everything registered.
- `tools/` one module per area: `meta`, `projects`, `tasks`, `people`, `assets`, `shots`, `custom_fields`,
  `activity`, `planning`; `review/` (`previews`, `playlists`, `video`); `write/` (`comments`, `assignments`,
  `schedule`, `time`, `playlists`, and `common` helpers). A tool's group is its tag, not its folder.

## Guidelines

- **Read-only by default.** New write tools go in `tools/write/`, are only registered with
  `KITSU_ALLOW_WRITE=true`, and take `dry_run=True` that returns the plan without writing.
- **Names, not just IDs.** Tool arguments accept names (case-insensitive) or IDs; resolve them with `kitsu/lookups.py`.
- **Small outputs.** Agents pay for every token: list tools return compact rows by default (`detail="full"` for
  more) with `total`, `limit` and `offset`.
- **Status roles.** Counts and filters use each status's role (`lookups.role`), never Kitsu's raw flags.
- **No studio-specific defaults.** Anything that fits only one studio goes behind a setting.
- **Tests with every change**, against the fake Kitsu (`tests/fakes.py`, seeded from `tests/fake_data.py`).
  Never test against a production Kitsu you do not own; writes to a real Kitsu need its owner's agreement.
- **Where code goes.** Kitsu access and production logic in `kitsu/`, which never imports `server/` or
  `tools/` (a test checks it); MCP plumbing in `server/`; tools in `tools/` by area. Tag each tool with its
  group (see `server/groups.py`).
- Add a line under **Unreleased** in `CHANGELOG.md`.

## Release

Bump `version` in `pyproject.toml` (and `uv lock`), give the CHANGELOG's Unreleased section the version and
date, merge, then tag the merge commit `vX.Y.Z` (`git tag vX.Y.Z && git push origin vX.Y.Z`).
The Release workflow checks the tag matches the version, runs the checks, then publishes the package to
PyPI and the Docker image to `ghcr.io/estienneg/kitsu-mcp` (tags `X.Y.Z`, `X.Y` and `latest`).
PyPI uses trusted publishing, so no token is stored: the `kitsu-mcp` project on PyPI has this repository
as its publisher (workflow `release.yml`, environment `pypi`).

The release workflow can publish, so its actions are pinned to commit SHAs (with a `# vX.Y.Z` comment) rather
than tags, which most projects can move; CI uses major tags. Keep new actions in `release.yml` pinned the same
way. Dependabot (`.github/dependabot.yml`) proposes updates weekly, once a release is a week old: minor and
patch bumps in one PR, each major bump in its own. When reviewing one, check that each new SHA is the commit its
`# vX.Y.Z` tag points at, and for a major bump read its breaking changes: CI never runs `release.yml`, so its
PyPI and Docker login/metadata steps are first exercised at the next release.
