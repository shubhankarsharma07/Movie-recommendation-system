"""
Ratings (FR-1.1, FR-1.2, AC-2).

Valid ratings are 0.5 .. 5.0 in steps of 0.5. Anything else gets HTTP 400 with
a message stating the valid range, and NOTHING is written. Re-rating the same
title updates the existing row (and its created_at).
"""
import math

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db, iso, utcnow
from app.deps import get_current_user, get_model_state
from app.models import Movie, Rating, User
from app.schemas import RatingIn
from app.services import rating_stats
from app.services.cards import card_for, json_response

router = APIRouter(prefix="/api/ratings", tags=["ratings"])

INVALID_RATING = "Rating must be between 0.5 and 5.0 in steps of 0.5"   # exact FR-1.2 text


def parse_rating(value) -> float | None:
    """Return the rating as a float if it is valid, else None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0.5 or number > 5.0:
        return None
    doubled = number * 2
    if abs(doubled - round(doubled)) > 1e-9:   # 4.3 -> 8.6 is not a whole number
        return None
    return round(doubled) / 2


@router.post("")
def rate(body: RatingIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    value = parse_rating(body.rating)
    if value is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=INVALID_RATING)
    if db.get(Movie, body.movie_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")

    now = utcnow()
    for _attempt in range(2):   # retry once if two requests race on the unique key
        existing = db.scalar(select(Rating).where(Rating.user_id == user.id, Rating.movie_id == body.movie_id))
        if existing is not None:
            existing.rating = value
            existing.created_at = now
        else:
            db.add(Rating(user_id=user.id, movie_id=body.movie_id, rating=value, created_at=now))
        try:
            db.commit()
            break
        except IntegrityError:
            db.rollback()
    else:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Please try again")
    return {"movie_id": body.movie_id, "rating": value, "created_at": iso(now)}


@router.get("/me")
def my_ratings(user: User = Depends(get_current_user), state=Depends(get_model_state),
               db: Session = Depends(get_db)):
    rows = db.execute(
        select(Rating.movie_id, Rating.rating, Rating.created_at)
        .where(Rating.user_id == user.id).order_by(Rating.created_at.desc())
    ).all()
    stats = rating_stats.get_stats(db)
    items = []
    for movie_id, rating, created_at in rows:
        card = card_for(state, db, movie_id, stats)
        if card is not None:
            items.append({"movie": card, "rating": float(rating), "created_at": iso(created_at)})
    return json_response({"items": items})


@router.delete("/{movie_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rating(movie_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(delete(Rating).where(Rating.user_id == user.id, Rating.movie_id == movie_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
