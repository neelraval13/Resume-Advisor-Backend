# syntax=docker/dockerfile:1.7

# ─── stage 1: build ────────────────────────────────────────────────────────
# We use uv's official image which has uv pre-installed and a slim Python.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /app

# Install dependencies first (cached layer if pyproject.toml hasn't changed)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Now copy application code
COPY app/ ./app/

# ─── stage 2: runtime ──────────────────────────────────────────────────────
# Slim Python image — no uv, no build tools, just what's needed to run.
FROM python:3.13-slim-bookworm AS runtime

# Create a non-root user. Running as root inside containers is bad hygiene;
# even if a process gets compromised, it's confined to a low-privilege user.
RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --no-create-home app

WORKDIR /app

# Copy the virtual env from the builder stage
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/app /app/app

# Make sure the venv's binaries are first on PATH
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app

EXPOSE 8000

# uvicorn binds 0.0.0.0 so traffic from outside the container reaches it.
# --workers 1 because Fly.io scales by spawning more machines, not workers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
