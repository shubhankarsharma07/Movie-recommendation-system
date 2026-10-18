"""
Turns catalog indexes / DB rows into the JSON shapes of CONTRACT 5.1 and 5.2.
"""
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import iso
from app.deps import is_admin
from app.models import Movie, Rating, User
from app.services.model_store import card_from_movie_row


def user_json(db: Session, user: User) -> dict:
    rating_count = db.scalar(select(func.count(Rating.id)).where(Rating.user_id == user.id)) or 0
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "is_admin": is_admin(user),
        "created_at": iso(user.created_at),
        "rating_count": int(rating_count),
    }


def users_json(db: Session, users: list[User]) -> list[dict]:
    """Same as user_json for several users with ONE count query."""
    ids = [u.id for u in users]
    counts = dict(db.execute(
        select(Rating.user_id, func.count(Rating.id)).where(Rating.user_id.in_(ids)).group_by(Rating.user_id)
    ).all()) if ids else {}
    return [{
        "id": str(u.id), "email": u.email, "display_name": u.display_name, "is_admin": is_admin(u),
        "created_at": iso(u.created_at), "rating_count": int(counts.get(u.id, 0)),
    } for u in users]


def card_for(state, db: Session, movie_id: int, stats: dict) -> dict | None:
    """MovieCard from the in-memory catalog, or from the movies table as a backup."""
    if state is not None:
        i = state.idx(movie_id)
        if i is not None:
            return state.card(i, stats)
    movie = db.get(Movie, movie_id)
    return card_from_movie_row(movie, stats) if movie is not None else None


def rec_items(state, result, stats: dict) -> list[dict]:
    """RecResult items -> [MovieCard + score + reason (+ member_scores)]."""
    out = []
    for item in result.items:
        target, score, reason = item[0], item[1], item[2]
        card = card_from_movie_row(target, stats) if result.from_db else state.card(target, stats)
        card["score"] = round(float(score), 4)
        card["reason"] = reason
        if len(item) > 3:
            card["member_scores"] = item[3]
        out.append(card)
    return out


def movie_ids_of(items: list[dict]) -> list[int]:
    return [int(c["movie_id"]) for c in items]


def json_response(data, status_code: int = 200) -> JSONResponse:
    """Return already-JSON-safe data directly (skips FastAPI's slower encoder;
    handy for big payloads like /api/home)."""
    return JSONResponse(content=data, status_code=status_code)
