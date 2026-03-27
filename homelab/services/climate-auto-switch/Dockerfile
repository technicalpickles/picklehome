ARG UV_VERSION=0.11.2
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:3.12-slim

COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app

# Install deps first (layer caching: deps change less often than code)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Copy the climate package
COPY climate/ climate/

# Install the project itself (uses cached deps layer)
RUN uv sync --frozen

ENTRYPOINT ["uv", "run", "python", "-m", "climate.sync", "comfort-switch", "auto", "--clear-holds"]
