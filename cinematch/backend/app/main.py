"""
CineMatch API — FastAPI entry point.

Run locally (from the backend/ folder):
    uvicorn app.main:app --reload

Startup:
  1. create DB tables
  2. load the live artifact version (artifacts/current.txt) into memory
  3. copy its catalog.csv into the `movies` table if the version changed
  4. delete request logs older than 180 days
If ../frontend exists, it is served at "/" (after all /api routes), so
http://localhost:8000 runs the whole app.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.routers import (
    admin, auth, context, events, health, home, meta, movies, party, playback, profile, ratings, recommend,
)
from app.services import catalog_sync
from app.services.logging import maybe_cleanup, request_logging_middleware, setup_logging
from app.services.model_store import store

log = logging.getLogger("cinematch")


def _sync_movies_table(state) -> None:
    try:
        catalog_sync.sync_movies(state)
    except Exception:
        log.exception("could not sync the movies table")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    if settings.jwt_secret == "change-me":
        log.warning("JWT_SECRET is the default 'change-me' - set a real secret in production!")
    init_db()
    store.add_listener(_sync_movies_table)   # also runs after every hot reload
    if not store.reload():
        log.warning("no model loaded (%s) - serving popularity fallback", store.last_error)
    maybe_cleanup()
    yield


app = FastAPI(title="CineMatch API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,          # we use Bearer tokens, not cookies
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
app.middleware("http")(request_logging_middleware)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """422 with a readable {"detail": "..."} message (CONTRACT error format).
    The submitted values are NOT echoed back (could be a password - NFR-2)."""
    errors = []
    for err in exc.errors():
        location = ".".join(str(part) for part in err.get("loc", []) if part not in ("body", "query", "path"))
        errors.append({"field": location, "message": err.get("msg", "invalid value")})
    first = errors[0] if errors else {"field": "", "message": "Invalid request"}
    detail = f"{first['field']}: {first['message']}" if first["field"] else first["message"]
    return JSONResponse(status_code=422, content={"detail": detail, "errors": errors})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


for module in (health, auth, movies, meta, ratings, context, recommend, home, playback, events,
               profile, party, admin):
    app.include_router(module.router)


# Static frontend LAST, so every /api route wins.
if settings.frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(settings.frontend_dir), html=True), name="frontend")
else:
    @app.get("/", include_in_schema=False)
    def root():
        return {"name": "CineMatch API", "docs": "/docs", "health": "/api/health"}
