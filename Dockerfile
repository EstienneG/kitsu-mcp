# Hosted kitsu-mcp for Le Chat / AI Studio connectors. Put HTTPS in front (Fly.io, Render and the like do),
# then confirm it with KITSU_BEHIND_TLS=true at run time: the server refuses a public bind without it.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --extra video --no-install-project
COPY src ./src
RUN uv sync --locked --extra video

RUN useradd --system --no-create-home app && install -d -o app -g app -m 700 /var/cache/kitsu-mcp-videos
USER app

# Only KITSU_HOST is needed: every caller brings their own Kitsu login.
ENV KITSU_HTTP_HOST=0.0.0.0 PORT=8000 KITSU_VIDEO_CACHE_DIR=/var/cache/kitsu-mcp-videos
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health')"
CMD ["/app/.venv/bin/kitsu-mcp", "--http"]
