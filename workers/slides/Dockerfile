# SPDX-License-Identifier: AGPL-3.0-only
FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv
FROM python:3.14.10-slim-trixie AS build
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY --from=uv /uv /usr/local/bin/uv
COPY workers/slides/pyproject.toml workers/slides/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache

FROM python:3.14.10-slim-trixie AS run
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY workers/slides/slides_worker ./slides_worker
COPY apps/design-system/tokens.json ./slides_worker/tokens.json
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["python", "-m", "slides_worker"]
