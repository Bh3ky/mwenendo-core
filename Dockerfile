# syntax=docker/dockerfile:1

# ---- Stage 1: build the virtual environment ---------------------------------
# uv and its download cache live only in this stage, so neither ends up in the
# final image.
FROM python:3.12-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# uv, pinned to the version the lock file was made with.
COPY --from=ghcr.io/astral-sh/uv:0.9.28 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first: this layer is rebuilt only when the lock file changes.
# The cache mount reuses downloaded packages across builds without storing
# them in any layer.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

# ---- Stage 2: the image that runs -------------------------------------------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Run as an ordinary user, not root.
RUN useradd --create-home --uid 1000 app && mkdir /app && chown app:app /app
USER app
WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app . .

# Gather static files (admin CSS and so on) for WhiteNoise to serve. Django
# reads its settings while doing this, so give it throwaway values. They exist
# only for this one command and are not kept in the image.
RUN SECRET_KEY=build-only POSTGRES_DB=build POSTGRES_USER=build \
    POSTGRES_PASSWORD=build POSTGRES_HOST=build POSTGRES_PORT=5432 \
    python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "-c", "gunicorn.conf.py", "config.wsgi:application"]
