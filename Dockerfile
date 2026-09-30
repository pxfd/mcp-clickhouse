# Build stage - Use a Python image with uv pre-installed
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

# Install the project into `/app`
WORKDIR /app

# Bytecode is not precompiled: it would add ~50 MB to the image. Python compiles
# modules on first import instead, which costs a little extra startup time.
ENV UV_COMPILE_BYTECODE=0

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Install only the dependencies first. This layer is reused until uv.lock changes.
# All locked dependencies ship prebuilt wheels, so no compiler or git is needed.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=README.md,target=README.md \
    uv sync --locked --no-install-project --no-dev

# Then install the package itself. Only the files needed to build it are copied, so
# changes to start.sh, middlewares or auth do not rebuild the venv.
COPY pyproject.toml uv.lock README.md /app/
COPY mcp_clickhouse /app/mcp_clickhouse
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# Production stage - Use minimal Python image
FROM python:3.13-slim-bookworm

LABEL org.opencontainers.image.source="https://github.com/ClickHouse/mcp-clickhouse"
LABEL org.opencontainers.image.description="MCP server for ClickHouse"
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL io.modelcontextprotocol.server.name="io.github.ClickHouse/mcp-clickhouse"

# Set the working directory
WORKDIR /app

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# No-auth CH default, baked to image
ENV CLICKHOUSE_USER="default"
ENV CLICKHOUSE_PASSWORD=""

# Copy the virtual environment from the builder stage (largest layer, changes least often)
COPY --from=builder /app/.venv /app/.venv

# Small files that change most often go last, so edits only rebuild these layers.
# Entrypoint that optionally sources /secret/secret.env
COPY ./start.sh /app/start.sh

# Copy middleware code
COPY ./middlewares /app/middlewares

# Copy auth providers
COPY ./auth /app/auth

# Server instructions are not baked in: start.sh loads
# /app/instructions/clickhouse_server_instructions.md, mounted from a ConfigMap.

# Run the MCP ClickHouse server by default
ENTRYPOINT ["/app/start.sh"]
CMD ["python", "-m", "mcp_clickhouse.main"]
