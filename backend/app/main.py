"""FastAPI application entrypoint: startup lifespan, routers, error handling, SPA hosting."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

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

    yield


app = FastAPI(title="Menu Catalog Automation", lifespan=lifespan)

app.add_exception_handler(AppError, app_error_handler)


# Routers are imported directly and eagerly. An earlier version wrapped each
# in try/except ImportError so the app could boot while agents were still
# writing them; that is actively harmful now - a missing dependency in
# production would start a healthy-looking app with half its API silently
# absent, surfacing as mystery 404s. Fail loudly at boot instead.
from app.routers.auth import router as auth_router
from app.routers.shops import router as shops_router
from app.routers.items import router as items_router
from app.routers.images import router as images_router
from app.routers.jobs import router as jobs_router
from app.routers.export import router as export_router

# One convention: routers declare paths RELATIVE to /api, and are mounted
# here at /api. A router that also self-prefixes with /api produces
# /api/api/... and every frontend call to it 404s.
for _router in (auth_router, shops_router, items_router,
                images_router, jobs_router, export_router):
    app.include_router(_router, prefix="/api")

@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# Routers are owned by other agents; include defensively so this app boots
# even while those modules are still being written.

# Mount the built SPA, if present. Anything not under /api falls back to
# index.html so client-side routing works on a hard refresh / deep link.
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="spa")

    @app.exception_handler(StarletteHTTPException)
    async def spa_fallback_handler(request, exc: StarletteHTTPException):
        if exc.status_code == 404 and not request.url.path.startswith("/api"):
            return FileResponse(FRONTEND_DIST / "index.html")
        return await http_exception_handler(request, exc)
