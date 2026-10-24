# Hosted kitsu-mcp for Le Chat / AI Studio connectors. Put HTTPS in front (Fly.io, Render and the like do).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --extra video --no-install-project
COPY src ./src
RUN uv sync --locked --extra video

# Only KITSU_HOST is needed: every caller brings their own Kitsu login.
ENV HOST=0.0.0.0 PORT=8000 KITSU_BEHIND_TLS=true KITSU_VIDEO_CACHE_DIR=/tmp/kitsu-mcp-videos
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health')"
CMD ["/app/.venv/bin/kitsu-mcp", "--http"]
