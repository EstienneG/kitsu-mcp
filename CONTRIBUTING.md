# Contributing

Issues and pull requests are welcome. For a new tool or a behaviour change, open an issue first to agree on
the shape.

## Setup

You need [uv](https://docs.astral.sh/uv/). Then:

    uv sync
    cp .env.example .env   # only to run the server against your own Kitsu

## Checks

Every pull request must pass these, as CI does:

    uv run pytest                                  # unit tests, in-memory fake Kitsu, no credentials
    uv run ruff check . && uv run ruff format --check .
    uv run pyright

CI also runs `tests/integration` against real Zou versions (see the README's Development section to run them
locally with Docker). Add to them when a change depends on what Zou returns.

## Guidelines

- **Read-only by default.** New write tools go in `tools/write.py`, are only registered with
  `KITSU_ALLOW_WRITE=true`, and take `dry_run=True` that returns the plan without writing.
- **Names, not just IDs.** Tool arguments accept names (case-insensitive) or IDs; resolve them with `lookups.py`.
- **Small outputs.** Agents pay for every token: list tools return compact rows by default (`detail="full"` for
  more) with `total`, `limit` and `offset`.
- **Status roles.** Counts and filters use each status's role (`lookups.role`), never Kitsu's raw flags.
- **No studio-specific defaults.** Anything that fits only one studio goes behind a setting.
- **Tests with every change**, against the fake in `tests/fakes.py`. Never test against a production Kitsu
  you do not own; writes to a real Kitsu need its owner's agreement.
- Add a line under **Unreleased** in `CHANGELOG.md`.
