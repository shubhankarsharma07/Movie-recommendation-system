"""
Logging (NFR-3) and the request log table.

* Every HTTP request gets a uuid request_id (also returned in the X-Request-ID
  header) and one log line: method, path, status, latency. We NEVER log request
  bodies, so passwords sent to /api/auth can't leak into logs (NFR-2).
* Every recommendation request (/api/recommendations, /api/home, party
  recommendations) also gets a `request_logs` row: request id, user, context,
  movie ids returned, fallback flag, latency.
* cleanup_request_logs() deletes rows older than 180 days. It refuses to delete
  anything younger than 90 days (the SRS says keep >= 90 days).
"""
import json
import logging
import time
import uuid
from datetime import timedelta

from sqlalchemy import delete

from app.database import SessionLocal, utcnow
from app.models import RequestLog

log = logging.getLogger("cinematch.requests")
rec_log = logging.getLogger("cinematch.recommendations")

KEEP_DAYS = 180
MIN_KEEP_DAYS = 90
_last_cleanup: float | None = None   # monotonic time of the last cleanup


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def request_logging_middleware(request, call_next):
    """Adds request.state.request_id and logs one line per request (no bodies)."""
    request_id = uuid.uuid4()
    request.state.request_id = request_id
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = str(request_id)
        return response
    finally:
        latency = (time.perf_counter() - started) * 1000
        # path only - no query string for auth routes, no bodies ever
        log.info("%s %s %s %.1fms rid=%s", request.method, request.url.path, status, latency, request_id)


def log_recommendation(db, request_id: uuid.UUID, user_id, endpoint: str, context: dict,
                       movie_ids: list[int], fallback: bool, latency_ms: float) -> None:
    """Write the NFR-3 row. A logging failure must never break the response."""
    try:
        db.add(RequestLog(
            id=request_id, user_id=user_id, endpoint=endpoint, context=context,
            movie_ids=[int(m) for m in movie_ids], fallback=bool(fallback),
            latency_ms=float(latency_ms), created_at=utcnow(),
        ))
        db.commit()
    except Exception:
        db.rollback()
        log.exception("could not write request_logs row %s", request_id)
    rec_log.info("rid=%s user=%s endpoint=%s fallback=%s latency=%.1fms context=%s movies=%s",
                 request_id, user_id, endpoint, fallback, latency_ms,
                 json.dumps(context, sort_keys=True), movie_ids)
    maybe_cleanup(db)


def cleanup_request_logs(older_than_days: int = KEEP_DAYS, db=None) -> int:
    """Delete request_logs older than `older_than_days` (never below 90).
    Uses `db` if given, otherwise opens its own session."""
    days = max(int(older_than_days), MIN_KEEP_DAYS)
    cutoff = utcnow() - timedelta(days=days)
    if db is None:
        with SessionLocal() as own_db:
            return cleanup_request_logs(days, own_db)
    result = db.execute(delete(RequestLog).where(RequestLog.created_at < cutoff))
    db.commit()
    return result.rowcount or 0


def maybe_cleanup(db=None) -> None:
    """Run the cleanup at most once a day (called after each logged request)."""
    global _last_cleanup
    now = time.monotonic()
    if _last_cleanup is not None and now - _last_cleanup < 24 * 3600:
        return
    _last_cleanup = now
    try:
        removed = cleanup_request_logs(KEEP_DAYS, db)
        if removed:
            log.info("removed %d request_logs rows older than %d days", removed, KEEP_DAYS)
    except Exception:
        if db is not None:
            db.rollback()
        log.exception("request_logs cleanup failed")
