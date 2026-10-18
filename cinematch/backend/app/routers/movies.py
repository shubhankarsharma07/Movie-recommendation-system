"""
Catalog browser (FR-1.3, FR-1.4): list with filters, title search, details,
and the onboarding picks for new users (cold start).
"""
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_model_state, get_optional_user
from app.models import Dismissal, Movie, Rating
from app.services import rating_stats
from app.services.cards import json_response
from app.services.model_store import card_from_movie_row
from app.services.recommender import engine_slot
from app.vocab import GENRES

router = APIRouter(prefix="/api", tags=["movies"])

SORTS = ("popular", "rating", "year", "title")
RATING_PRIOR_COUNT = 25     # "rating" sort uses a Bayesian average so 1 vote of 5★ doesn't win
RATING_PRIOR_MEAN = 3.0


def _int_or_none(value: str | None, name: str) -> int | None:
    """Query params may arrive as empty strings (?year_from=) -> treat as 'not set'."""
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{name} must be a whole number")


def _genre_name(value: str | None) -> str | None:
    if not value:
        return None
    lookup = {g.lower(): g for g in GENRES}
    return lookup.get(value.strip().lower(), value.strip())


def _merged_rating_arrays(state, stats: dict):
    """Vectorised avg rating (MovieLens + in-app) for the 'rating' sort."""
    has_ml = (state.ml_count > 0) & ~np.isnan(state.ml_mean)
    total = np.where(has_ml, state.ml_mean * state.ml_count, 0.0).astype(np.float64)
    count = np.where(has_ml, state.ml_count, 0).astype(np.float64)
    for movie_id, (s, c) in stats.items():
        i = state.idx(movie_id)
        if i is not None:
            total[i] += s
            count[i] += c
    return (total + RATING_PRIOR_MEAN * RATING_PRIOR_COUNT) / (count + RATING_PRIOR_COUNT)


@router.get("/movies")
def list_movies(
    q: str = Query("", max_length=200),
    genre: str | None = None,
    year_from: str | None = None,
    year_to: str | None = None,
    language: str | None = None,
    content_type: str | None = None,
    sort: str = "popular",
    page: str | None = None,
    page_size: str | None = None,
    state=Depends(get_model_state),
    db: Session = Depends(get_db),
):
    year_from_i = _int_or_none(year_from, "year_from")
    year_to_i = _int_or_none(year_to, "year_to")
    page_i = max(1, _int_or_none(page, "page") or 1)
    size = min(100, max(1, _int_or_none(page_size, "page_size") or 40))
    sort = sort if sort in SORTS else "popular"
    genre = _genre_name(genre)
    language = (language or "").strip().lower() or None
    content_type = content_type if content_type in ("movie", "series") else None
    q = q.strip().lower()
    stats = rating_stats.get_stats(db)

    if state is None:   # no catalog in memory -> read the movies table
        return _list_from_db(db, q, genre, year_from_i, year_to_i, language, content_type,
                             sort, page_i, size, stats)

    n = state.n
    mask = np.ones(n, dtype=bool)
    if q:
        mask &= np.fromiter((q in t for t in state.title_lower), dtype=bool, count=n)
    if genre:
        mask &= state.genre_matrix[:, GENRES.index(genre)] if genre in GENRES else False
    if year_from_i is not None:
        mask &= state.year >= year_from_i
    if year_to_i is not None:
        mask &= state.year <= year_to_i
    if language:
        mask &= (state.lang_idx == state.lang_codes.index(language)) if language in state.lang_codes else False
    if content_type:
        mask &= state.is_series if content_type == "series" else ~state.is_series

    if sort == "popular":
        order = state.order_popular[mask[state.order_popular]]
    elif sort == "title":
        order = state.order_title[mask[state.order_title]]
    else:
        rows = np.flatnonzero(mask)
        if sort == "rating":
            key = _merged_rating_arrays(state, stats)[rows]
        else:  # year, newest first, unknown years last
            key = np.nan_to_num(state.year[rows], nan=-1.0)
        order = rows[np.lexsort((-state.popularity[rows], -key))]

    total = int(len(order))
    page_rows = order[(page_i - 1) * size: page_i * size]
    items = [state.card(int(i), stats) for i in page_rows]
    return json_response({"items": items, "total": total, "page": page_i, "page_size": size})


def _list_from_db(db, q, genre, year_from, year_to, language, content_type, sort, page, size, stats):
    query = select(Movie)
    if q:
        query = query.where(func.lower(Movie.title).contains(q))
    if genre:
        query = query.where(Movie.genres.contains(genre))
    if year_from is not None:
        query = query.where(Movie.year >= year_from)
    if year_to is not None:
        query = query.where(Movie.year <= year_to)
    if language:
        query = query.where(Movie.original_language == language)
    if content_type:
        query = query.where(Movie.content_type == content_type)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    order = {
        "popular": [Movie.popularity_score.desc()],
        "rating": [Movie.ml_rating_mean.desc()],
        "year": [Movie.year.desc()],
        "title": [Movie.title.asc()],
    }[sort]
    rows = db.scalars(query.order_by(*order, Movie.movie_id).offset((page - 1) * size).limit(size)).all()
    return {"items": [card_from_movie_row(m, stats) for m in rows], "total": int(total),
            "page": page, "page_size": size}


@router.get("/movies/search")
def search_movies(q: str = Query("", max_length=200), limit: int = Query(10, ge=1, le=50),
                  state=Depends(get_model_state), db: Session = Depends(get_db)):
    """Title search box: titles starting with q (or a word starting with q)
    first, then titles containing q; most popular first in each group."""
    q = q.strip().lower()
    if not q:
        return {"items": []}
    stats = rating_stats.get_stats(db)
    if state is None:
        rows = db.scalars(select(Movie).where(func.lower(Movie.title).contains(q))
                          .order_by(Movie.popularity_score.desc()).limit(limit)).all()
        return {"items": [card_from_movie_row(m, stats) for m in rows]}
    prefix, contains = [], []
    for i in state.order_popular:
        title = state.title_lower[i]
        if q not in title:
            continue
        if title.startswith(q) or (" " + q) in title:
            prefix.append(int(i))
            if len(prefix) >= limit:
                break
        elif len(contains) < limit:
            contains.append(int(i))
    chosen = (prefix + contains)[:limit]
    return json_response({"items": [state.card(i, stats) for i in chosen]})


def similar_items(state, i: int, k: int = 12) -> list[int]:
    """'More like this': CF item-factor cosine blended 50/50 with plot-embedding
    cosine (whichever exists if only one does; genre overlap as a last resort)."""
    inter = np.zeros(state.n, dtype=np.float32)
    for j in np.flatnonzero(state.genre_matrix[i]):       # only this title's genres
        inter += state.genre_matrix[:, j]
    union = state.genre_count + state.genre_count[i] - inter
    genre_sim = np.where(union > 0, inter / np.maximum(union, 1.0), 0.0)
    sim = 0.3 * genre_sim
    if state.has_model:
        cf = (state.Q @ state.Q[i]) / (state.q_norm * state.q_norm[i] + 1e-9)
        cf_ok = state.has_cf & state.has_cf[i]
        if state.emb is not None and state.has_emb[i]:
            em = state.emb_dot(state.emb_rows([i])[0])
            em_ok = state.has_emb
        else:
            em, em_ok = np.zeros(state.n, np.float32), np.zeros(state.n, bool)
        model_sim = np.where(cf_ok & em_ok, 0.5 * cf + 0.5 * em,
                             np.where(cf_ok, cf, np.where(em_ok, em, np.nan)))
        sim = np.where(np.isnan(model_sim), sim, model_sim)
    sim = sim + 0.01 * state.popularity       # tie-break: popular first
    sim[i] = -np.inf
    k = min(k, state.n - 1)
    if k <= 0:
        return []
    top = np.argpartition(-sim, k)[:k] if state.n > k + 1 else np.arange(state.n)
    top = top[np.argsort(-sim[top])]
    return [int(j) for j in top if j != i][:k]


@router.get("/movies/{movie_id}")
def movie_details(movie_id: int, user=Depends(get_optional_user),
                  state=Depends(get_model_state), db: Session = Depends(get_db)):
    stats = rating_stats.get_stats(db)
    i = state.idx(movie_id) if state is not None else None
    if i is not None:
        data = state.card(i, stats)
        data.update(state.details(i))
        with engine_slot():
            similar = similar_items(state, i)
        data["similar"] = [state.card(j, stats) for j in similar]
    else:
        movie = db.get(Movie, movie_id)
        if movie is None:
            raise HTTPException(status_code=404, detail="Movie not found")
        data = card_from_movie_row(movie, stats)
        data.update({"directors": [], "cast": [], "keywords": [], "emotion_arc": None, "decade": None,
                     "quality_score": None, "popularity_score": movie.popularity_score,
                     "trending_velocity": None, "imdb_rating": None, "similar": []})
    data["user_rating"] = None
    data["dismissed"] = False
    if user is not None:
        rating = db.scalar(select(Rating.rating).where(Rating.user_id == user.id, Rating.movie_id == movie_id))
        data["user_rating"] = float(rating) if rating is not None else None
        data["dismissed"] = db.scalar(
            select(Dismissal.id).where(Dismissal.user_id == user.id, Dismissal.movie_id == movie_id)
        ) is not None
    return json_response(data)


@router.get("/onboarding/movies")
def onboarding_movies(user=Depends(get_optional_user), state=Depends(get_model_state),
                      db: Session = Depends(get_db)):
    """30 popular but DIVERSE titles for a new user to rate (cold start):
    at most 3 per main genre, preferring titles the CF model knows."""
    stats = rating_stats.get_stats(db)
    rated = set()
    if user is not None:
        rated = set(db.scalars(select(Rating.movie_id).where(Rating.user_id == user.id)).all())
    if state is None:
        rows = db.scalars(select(Movie).order_by(Movie.popularity_score.desc()).limit(60)).all()
        return {"items": [card_from_movie_row(m, stats) for m in rows if m.movie_id not in rated][:30]}

    pool = state.order_popular[:max(600, 30)]
    if state.has_model:   # titles with CF data first: rating them teaches the model the most
        pool = np.concatenate([pool[state.has_cf[pool]], pool[~state.has_cf[pool]]])
    chosen, per_genre = [], {}
    for i in pool:
        i = int(i)
        if int(state.movie_ids[i]) in rated:
            continue
        genres = state.genres_text[i].split("|")
        main = genres[0] if genres and genres[0] else "Other"
        if per_genre.get(main, 0) >= 3:
            continue
        per_genre[main] = per_genre.get(main, 0) + 1
        chosen.append(i)
        if len(chosen) >= 30:
            break
    if len(chosen) < 30:   # small catalogs: top up with the next most popular
        for i in state.order_popular:
            i = int(i)
            if i not in chosen and int(state.movie_ids[i]) not in rated:
                chosen.append(i)
                if len(chosen) >= 30:
                    break
    return json_response({"items": [state.card(i, stats) for i in chosen]})
