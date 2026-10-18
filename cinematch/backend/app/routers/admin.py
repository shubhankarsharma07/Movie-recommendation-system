"""
Admin / analytics panel (CONTRACT 5.9). Only for admins (403 otherwise).
"""
import os
import subprocess
import sys
import threading
from collections import Counter, deque
from datetime import timedelta

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, REPO_DIR, settings
from app.database import as_utc, get_db, utcnow
from app.deps import get_model_state, require_admin
from app.models import Event, PlaybackSession, Rating, RequestLog, User
from app.services import rating_stats
from app.services.behavior import completion_ratio
from app.services.cards import card_for, json_response
from app.services.model_store import store

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

WINDOW_DAYS = 30
CLICK_EVENTS = ("select", "details_open", "trailer_open")
CONTEXT_KEYS = ["weather", "time_of_day", "time_available_min", "occasion", "festival",
                "reference_movie_ids", "directors", "actors", "language", "max_age_rating",
                "franchise_mode", "nostalgia_decade", "start_emotion", "end_emotion", "genres",
                "content_type", "preset"]


def _by_day(datetimes) -> list[dict]:
    counts = Counter(as_utc(d).date().isoformat() for d in datetimes if d is not None)
    return [{"date": day, "count": counts[day]} for day in sorted(counts)]


@router.get("/stats")
def stats(state=Depends(get_model_state), db: Session = Depends(get_db)):
    since = utcnow() - timedelta(days=WINDOW_DAYS)
    count = lambda model: int(db.scalar(select(func.count()).select_from(model)) or 0)  # noqa: E731

    # ratings
    ratings_by_day = _by_day(db.scalars(select(Rating.created_at).where(Rating.created_at >= since)).all())
    histogram = {f"{v / 2:.1f}": 0 for v in range(1, 11)}
    for value, n in db.execute(select(Rating.rating, func.count(Rating.id)).group_by(Rating.rating)).all():
        histogram[f"{float(value):.1f}"] = int(n)
    stats_cache = rating_stats.get_stats(db)
    top = db.execute(
        select(Rating.movie_id, func.avg(Rating.rating), func.count(Rating.id))
        .group_by(Rating.movie_id).order_by(func.avg(Rating.rating).desc(), func.count(Rating.id).desc())
        .limit(10)
    ).all()
    top_rated = []
    for movie_id, avg, n in top:
        card = card_for(state, db, movie_id, stats_cache)
        if card is not None:
            top_rated.append({"movie": card, "avg": round(float(avg), 2), "count": int(n)})

    # recommendation requests (NFR-3 log)
    logs = db.execute(
        select(RequestLog.created_at, RequestLog.latency_ms, RequestLog.context, RequestLog.movie_ids,
               RequestLog.endpoint).where(RequestLog.created_at >= since)
    ).all()
    latencies = np.array([row.latency_ms for row in logs], dtype=np.float64)
    items_served = sum(len(row.movie_ids or []) for row in logs)
    context_usage = {key: 0 for key in CONTEXT_KEYS}
    for row in logs:
        if row.endpoint == "/api/home":
            continue   # home rows use built-in presets, not user choices
        for key, value in (row.context or {}).items():
            if key in context_usage and value not in (None, [], ""):
                context_usage[key] += 1

    # engagement
    clicked_requests = db.scalar(
        select(func.count(func.distinct(Event.request_id)))
        .where(Event.type.in_(CLICK_EVENTS), Event.request_id.is_not(None), Event.created_at >= since)
    ) or 0
    avg_select = db.scalar(select(func.avg(Event.value)).where(Event.type == "select", Event.value.is_not(None)))
    dismisses = db.scalar(select(func.count(Event.id)).where(Event.type == "dismiss", Event.created_at >= since)) or 0
    sessions = db.scalars(select(PlaybackSession).where(PlaybackSession.ended_at.is_not(None))
                          .order_by(PlaybackSession.started_at.desc()).limit(5000)).all()
    ratios = [r for r in (completion_ratio(s) for s in sessions) if r is not None]

    meta = dict(state.meta) if state is not None else {}
    meta.update({
        "loaded_version": state.version if state is not None else None,
        "model_loaded": store.model_loaded,
        "catalog_size": state.n if state is not None else 0,
        "last_error": store.last_error,
    })
    return json_response({
        "users": count(User),
        "ratings": count(Rating),
        "sessions": count(PlaybackSession),
        "events": count(Event),
        "requests": count(RequestLog),
        "ratings_by_day": ratings_by_day,
        "rating_histogram": histogram,
        "top_rated": top_rated,
        # share of recommendation lists (last 30 days) that led to a click
        "rec_ctr": round(clicked_requests / len(logs), 4) if logs else 0.0,
        "avg_browse_to_select_ms": round(float(avg_select), 1) if avg_select is not None else None,
        "avg_completion": round(float(np.mean(ratios)), 4) if ratios else None,
        # dismissals per recommended item shown (last 30 days)
        "dismiss_rate": round(dismisses / items_served, 4) if items_served else 0.0,
        "latency_p50_ms": round(float(np.percentile(latencies, 50)), 1) if len(latencies) else None,
        "latency_p95_ms": round(float(np.percentile(latencies, 95)), 1) if len(latencies) else None,
        "requests_by_day": _by_day([row.created_at for row in logs]),
        "context_usage": context_usage,
        "model": meta,
    })


@router.post("/reload-model")
def reload_model():
    store.reload(force=True)
    state = store.state
    return {"version": state.version if state is not None else None,
            "model_loaded": store.model_loaded, "error": store.last_error}


# ------------------------------------------------------------------------- in-app retraining
RETRAIN_LOG = BACKEND_DIR / "retrain.log"
_retrain = {"status": "idle", "process": None}
_retrain_lock = threading.Lock()


def _watch(process: subprocess.Popen) -> None:
    code = process.wait()
    with _retrain_lock:
        _retrain["status"] = "succeeded" if code == 0 else "failed"
        _retrain["process"] = None
    if code == 0:
        store.reload()   # pick up the new current.txt right away


@router.post("/retrain")
def start_retrain():
    if not settings.enable_inapp_retrain:
        raise HTTPException(status_code=400, detail="In-app retraining is disabled (set ENABLE_INAPP_RETRAIN=true)")
    script = REPO_DIR / "ml" / "retrain.py"
    if not script.is_file():
        raise HTTPException(status_code=400, detail="ml/retrain.py not found")
    with _retrain_lock:
        if _retrain["process"] is not None:
            return {"status": "running"}
        env = dict(os.environ, ARTIFACTS_DIR=str(store.artifacts_dir), DATABASE_URL=settings.database_url)
        log_file = open(RETRAIN_LOG, "w", encoding="utf-8")
        process = subprocess.Popen([sys.executable, str(script)], cwd=str(REPO_DIR), env=env,
                                   stdout=log_file, stderr=subprocess.STDOUT)
        log_file.close()   # the child process keeps its own handle
        _retrain.update(status="running", process=process)
    threading.Thread(target=_watch, args=(process,), daemon=True).start()
    return {"status": "started"}


@router.get("/retrain")
def retrain_status():
    tail = ""
    if RETRAIN_LOG.is_file():
        with open(RETRAIN_LOG, encoding="utf-8", errors="replace") as fh:
            tail = "".join(deque(fh, maxlen=40))
    return {"status": _retrain["status"], "last_log_tail": tail}
