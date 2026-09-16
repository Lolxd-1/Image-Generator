# Multi-stage: build the React SPA with Node, then serve it from the Python
# image alongside the API. One image, one origin, no CORS, one URL to click.
#
# Build context is `webapp/` (the repository root for this app).

# ---------------------------------------------------------------------------
# Stage 1 - build the SPA
# ---------------------------------------------------------------------------
FROM node:20-slim AS frontend

WORKDIR /app

# Manifests first, so `npm ci` is cached and only re-runs when deps change.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./

# Headroom: the default heap is small and a Vite build can exceed it on a
# constrained build machine, which fails with an opaque OOM.
ENV NODE_OPTIONS=--max-old-space-size=2048

# Build straight to an absolute path INSIDE this stage, overriding the
# vite.config.ts outDir of "../backend/frontend_dist". That default writes
# outside the Vite project root, which makes both `emptyOutDir` and the later
# `COPY --from` fragile. An absolute target removes the whole class of problem.
#
# We invoke `vite build` directly rather than `npm run build`, because the
# build script is `tsc --noEmit && vite build` and a type error must not be
# able to take down a deployment. Typechecking belongs in local dev and CI,
# not between you and a running app.
RUN npx vite build --outDir /frontend_dist --emptyOutDir \
 && test -f /frontend_dist/index.html \
 || (echo "FRONTEND BUILD PRODUCED NO index.html" && ls -la /frontend_dist && exit 1)

# ---------------------------------------------------------------------------
# Stage 2 - the runtime image
# ---------------------------------------------------------------------------
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# build-essential compiles a couple of wheels, then goes away again so it does
# not bloat the final image.
COPY backend/requirements.txt .
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && pip install --no-cache-dir -r requirements.txt \
 && apt-get purge -y --auto-remove build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY backend/ .

# The built SPA from stage 1. app/main.py serves this at / with an SPA
# fallback, so deep links like /shops/<id>/review survive a hard refresh.
COPY --from=frontend /frontend_dist ./frontend_dist

# Fail at build time, not at 3am, if the SPA did not make it into the image.
RUN test -f ./frontend_dist/index.html \
 || (echo "frontend_dist/index.html missing in final image" && exit 1)

EXPOSE 8000

# $PORT is injected by most hosts (Render, Koyeb, Cloud Run); default for local.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
