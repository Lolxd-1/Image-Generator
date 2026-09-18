"""FastAPI application entrypoint: startup lifespan, routers, error handling, SPA hosting."""
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.db import init_models
from app.errors import AppError, app_error_handler

logger = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend_dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_models()

    # Seed users from APP_USERS. This must NOT be guarded: if seeding fails,
    # nobody can log in, and a silently-skipped seed produces an app that looks
    # healthy but rejects every password. Fail at boot instead.
    from app.auth import seed_users
    from app.db import async_session_maker

    async with async_session_maker() as session:
        await seed_users(session)

        # Migrate any single-key users into the pool so nothing breaks on
        # deploy. Unlike seeding, a failed backfill must not stop the app from
        # booting - the operator can still re-add keys in Settings.
        from app.engine import keypool

        try:
            await keypool.migrate_legacy_keys(session)
        except Exception:
            logger.warning("migrate_legacy_keys failed at boot", exc_info=True)

    yield


app = FastAPI(title="Menu Catalog Automation", lifespan=lifespan)

# Process start time: a changing value here proves a redeploy actually
# restarted the app, even when the commit is the same.
_STARTED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")

app.add_exception_handler(AppError, app_error_handler)


# Routers are imported directly and eagerly. An earlier version wrapped each
# in try/except ImportError so the app could boot while agents were still
# writing them; that is actively harmful now - a missing dependency in
# production would start a healthy-looking app with half its API silently
# absent, surfacing as mystery 404s. Fail loudly at boot instead.
from app.routers.auth import router as auth_router
from app.routers.keys import router as keys_router
from app.routers.shops import router as shops_router
from app.routers.items import router as items_router
from app.routers.images import router as images_router
from app.routers.jobs import router as jobs_router
from app.routers.export import router as export_router
from app.routers.storage import router as storage_router

# One convention: routers declare paths RELATIVE to /api, and are mounted
# here at /api. A router that also self-prefixes with /api produces
# /api/api/... and every frontend call to it 404s.
for _router in (auth_router, keys_router, shops_router, items_router,
                images_router, jobs_router, export_router, storage_router):
    app.include_router(_router, prefix="/api")


@app.get("/api/health")
async def health() -> dict[str, str]:
    """Liveness probe, plus which build is actually serving.

    "ok" alone cannot tell you whether a fix you just pushed is live, which
    makes debugging a deploy guesswork. `commit` answers that directly.
    """
    return {
        "status": "ok",
        "commit": settings.build_commit,
        "started_at": _STARTED_AT,
    }


# Mount the built SPA, if present. Anything not under /api falls back to
# index.html so client-side routing works on a hard refresh / deep link.
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="spa")

    @app.exception_handler(StarletteHTTPException)
    async def spa_fallback_handler(request, exc: StarletteHTTPException):
        if exc.status_code == 404 and not request.url.path.startswith("/api"):
            return FileResponse(FRONTEND_DIST / "index.html")
        return await http_exception_handler(request, exc)
