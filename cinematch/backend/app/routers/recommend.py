"""
POST /api/recommendations (FR-4.1 .. FR-4.5) and dismiss / undo-dismiss.

Never a 500 for recommendations: if anything goes wrong in the personalised
path we serve the popularity fallback ("Trending now").
"""
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db, utcnow
from app.deps import get_current_user, get_model_state, get_user_for_recommendations
from app.models import Dismissal, Event, Movie, User
from app.schemas import RecommendationIn
from app.services import rating_stats
from app.services.cards import json_response, movie_ids_of, rec_items
from app.services.logging import log_recommendation
from app.services.recommender import (
    TRENDING, RecResult, build_user_state, db_popularity_fallback, engine_slot, load_user_rows,
    popularity_fallback, prepare, recommend,
)

log = logging.getLogger("cinematch.api")
router = APIRouter(prefix="/api", tags=["recommendations"])


def get_recommendations(db: Session, state, user_id, ctx: dict, limit: int) -> RecResult:
    """Personalised list -> catalog popularity fallback -> DB popularity fallback
    -> empty list. Each step only runs if the previous one could not answer."""
    if state is not None:
        us, prep = None, None
        try:
            us = build_user_state(db, user_id, state)
            prep = prepare(state, ctx)
            result = recommend(state, us, prep, limit)
            if result is not None and result.items:
                return result
        except Exception:
            log.exception("personalised recommendations failed - using fallback")
        try:
            prep = prep or prepare(state, ctx)
            result = popularity_fallback(state, us, prep, limit)
            if result.items:
                return result
        except Exception:
            log.exception("catalog fallback failed")
    try:
        ratings, dismissed, _, _ = load_user_rows(db, user_id)
        return db_popularity_fallback(db, ctx, {m for m, _ in ratings}, dismissed, limit)
    except Exception:
        log.exception("database fallback failed")
        return RecResult([], TRENDING, True, ctx)


def response_body(request_id, result: RecResult, items: list[dict]) -> dict:
    return {
        "request_id": str(request_id),
        "label": result.label,
        "fallback": result.fallback,
        "items": items,
        "context_used": result.context_used,
        "relaxed_filters": result.relaxed,
    }


@router.post("/recommendations")
def recommendations(request: Request, body: RecommendationIn | None = None,
                    user: User = Depends(get_user_for_recommendations),
                    state=Depends(get_model_state), db: Session = Depends(get_db)):
    started = time.perf_counter()
    body = body or RecommendationIn()
    ctx = body.context.cleaned()
    with engine_slot():
        result = get_recommendations(db, state, user.id, ctx, body.limit)
    items = rec_items(state, result, rating_stats.get_stats(db))
    request_id = request.state.request_id
    latency = (time.perf_counter() - started) * 1000
    log_recommendation(db, request_id, user.id, "/api/recommendations", result.context_used,
                       movie_ids_of(items), result.fallback, latency)
    return json_response(response_body(request_id, result, items))


def _movie_exists(state, db: Session, movie_id: int) -> bool:
    if state is not None and state.idx(movie_id) is not None:
        return True
    return db.get(Movie, movie_id) is not None


@router.post("/recommendations/{movie_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss(movie_id: int, user: User = Depends(get_current_user), state=Depends(get_model_state),
            db: Session = Depends(get_db)):
    """FR-4.5: 'Not interested' - this title never comes back for this user."""
    if not _movie_exists(state, db, movie_id):
        raise HTTPException(status_code=404, detail="Movie not found")
    exists = db.scalar(select(Dismissal.id).where(Dismissal.user_id == user.id, Dismissal.movie_id == movie_id))
    if exists is None:
        db.add(Dismissal(user_id=user.id, movie_id=movie_id, created_at=utcnow()))
        try:
            db.commit()
        except IntegrityError:   # double click: already dismissed
            db.rollback()
    db.add(Event(user_id=user.id, movie_id=movie_id, type="dismiss", created_at=utcnow()))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/recommendations/{movie_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def undo_dismiss(movie_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(delete(Dismissal).where(Dismissal.user_id == user.id, Dismissal.movie_id == movie_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
