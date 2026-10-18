"""
Copies catalog.csv (of the live artifact version) into the `movies` table.

Runs on startup and whenever a new version is hot-loaded, but only does real
work when the version changed (remembered in the small app_state table) or the
table is empty. It is an UPSERT: new titles are inserted, existing ones are
updated, and titles that disappeared are KEPT (old ratings point at them).
"""
import logging
import math

from sqlalchemy import func, select

from app.database import SessionLocal, engine, utcnow
from app.models import AppState, Movie

log = logging.getLogger("cinematch.catalog_sync")

VERSION_KEY = "movies_version"
COLUMNS = ["title", "year", "content_type", "genres", "poster_path", "backdrop_path",
           "original_language", "age_rating", "runtime", "ml_rating_mean", "ml_rating_count",
           "popularity_score"]


def _clean(value, as_int=False):
    if value is None:
        return None
    value = float(value)
    if math.isnan(value) or math.isinf(value):
        return None
    return int(round(value)) if as_int else value


def _rows(state) -> list[dict]:
    rows = []
    for i in range(state.n):
        rows.append({
            "movie_id": int(state.movie_ids[i]),
            "title": state.title[i][:1000],
            "year": _clean(state.year[i], as_int=True),
            "content_type": state.content_type[i],
            "genres": state.genres_text[i],
            "poster_path": state.poster_path[i][:255] or None,
            "backdrop_path": state.backdrop_path[i][:255] or None,
            "original_language": state.language[i][:10] or None,
            "age_rating": state.age_rating[i][:10] or None,
            "runtime": _clean(state.runtime[i], as_int=True),
            "ml_rating_mean": _clean(state.ml_mean[i]),
            "ml_rating_count": int(state.ml_count[i]),
            "popularity_score": _clean(state.popularity[i]) or 0.0,
        })
    return rows


def _upsert_statement():
    """INSERT ... ON CONFLICT (movie_id) DO UPDATE, for Postgres or SQLite."""
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    stmt = insert(Movie)
    return stmt.on_conflict_do_update(
        index_elements=[Movie.movie_id],
        set_={col: getattr(stmt.excluded, col) for col in COLUMNS},
    )


def sync_movies(state, force: bool = False) -> int:
    """Upsert the catalog of `state` into movies. Returns the number of rows written."""
    with SessionLocal() as db:
        marker = db.get(AppState, VERSION_KEY)
        count = db.scalar(select(func.count()).select_from(Movie)) or 0
        if not force and marker is not None and marker.value == state.version and count > 0:
            return 0
        rows = _rows(state)
        stmt = _upsert_statement()
        batch = 2000
        for start in range(0, len(rows), batch):
            db.execute(stmt, rows[start:start + batch])   # executemany, fast on both DBs
        if marker is None:
            db.add(AppState(key=VERSION_KEY, value=state.version, updated_at=utcnow()))
        else:
            marker.value = state.version
            marker.updated_at = utcnow()
        db.commit()
    log.info("movies table synced with %s (%d rows)", state.version, len(rows))
    return len(rows)
