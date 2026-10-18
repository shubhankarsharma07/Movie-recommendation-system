"""
In-app rating aggregates (sum and count per movie), cached for ~60 seconds.

Cards show avg_rating / rating_count = MovieLens stats merged with the ratings
people gave inside CineMatch. Re-counting the ratings table on every request
would be wasteful, so we refresh this small dict at most once a minute.
"""
import threading
import time

from sqlalchemy import func, select

from app.models import Rating

CACHE_SECONDS = 60

_lock = threading.Lock()
_cache: dict[int, tuple[float, int]] = {}
_loaded_at = 0.0


def get_stats(db) -> dict[int, tuple[float, int]]:
    """movie_id -> (sum of in-app ratings, number of in-app ratings).
    Uses the caller's DB session (opening a second connection inside a
    request can exhaust the connection pool under load)."""
    global _cache, _loaded_at
    if time.monotonic() - _loaded_at < CACHE_SECONDS:
        return _cache
    with _lock:
        if time.monotonic() - _loaded_at < CACHE_SECONDS:   # another thread refreshed it
            return _cache
        try:
            rows = db.execute(
                select(Rating.movie_id, func.sum(Rating.rating), func.count(Rating.id))
                .group_by(Rating.movie_id)
            ).all()
            _cache = {int(m): (float(s or 0.0), int(c)) for m, s, c in rows}
        except Exception:
            db.rollback()   # keep the old numbers if the DB hiccups
        _loaded_at = time.monotonic()
        return _cache


def invalidate() -> None:
    """Force a refresh on the next call (used by tests)."""
    global _loaded_at
    _loaded_at = 0.0
