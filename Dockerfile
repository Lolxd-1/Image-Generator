# Multi-stage: build the React SPA with Node, then serve it from the Python
# image alongside the API. One image, one origin, no CORS, one URL to click.
#
# Build context is `webapp/` (the repo root for this app), NOT `webapp/backend`,
# because stage 1 needs the frontend sources.

# ---------------------------------------------------------------------------
# Stage 1 - build the SPA
# ---------------------------------------------------------------------------
FROM node:20-slim AS frontend

WORKDIR /build

# Copy manifests first so `npm ci` is cached and only re-runs when deps change.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
# vite.config.ts writes to ../backend/frontend_dist, so give that path somewhere
# real to land inside this stage.
RUN mkdir -p /backend && npm run build

# ---------------------------------------------------------------------------
# Stage 2 - the runtime image
# ---------------------------------------------------------------------------
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# build-essential is needed to compile a couple of wheels, then removed again so
# it does not bloat the final image (free hosts have tight image size limits).
COPY backend/requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY backend/ .

# The built SPA, from stage 1. app/main.py serves this at / with an SPA
# fallback, so deep links like /shops/<id>/review survive a hard refresh.
COPY --from=frontend /backend/frontend_dist ./frontend_dist

EXPOSE 8000

# $PORT is injected by most hosts (Render, Koyeb, Cloud Run); default for local.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
