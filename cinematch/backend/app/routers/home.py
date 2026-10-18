"""
GET /api/home — the streaming-style home page: a hero item plus rows
(CONTRACT 5.6). The user state (fold-in, taste, behaviour) is computed ONCE
and reused for every row, so the whole page stays well under 2 s.

Every row carries a `filter`: the Context preset that reproduces the row in
the Mood Mixer ("See all" -> POST /api/recommendations with that context).
Rows with fewer than 4 items are skipped.
"""
import logging
import time

import numpy as np
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, get_model_state
from app.models import PlaybackSession, Rating, User
from app.routers.context import build_context_info
from app.services import rating_stats
from app.services.behavior import completion_ratio
from app.services.cards import card_for, json_response, rec_items
from app.services.explain import stars
from app.services.logging import log_recommendation
from app.services.recommender import (
    build_user_state, db_popularity_fallback, engine_slot, load_user_rows, popularity_fallback, prepare,
    recommend,
)
from app.services.rules import WEATHER_ADJECTIVE
from app.vocab import FESTIVAL_INFO, TIME_OF_DAY_WORDS

log = logging.getLogger("cinematch.api")
router = APIRouter(prefix="/api", tags=["home"])

ROW_LIMIT = 20
MIN_ROW_ITEMS = 4
REPEAT_PENALTY = 0.05     # items already shown in an earlier row sink a little (more variety)
ONBOARDING_MIN_RATINGS = 5


def continue_watching(db: Session, user: User, state, stats: dict) -> list[dict]:
    """Latest unfinished session per title (watched < 90 %), newest first."""
    sessions = db.scalars(
        select(PlaybackSession).where(PlaybackSession.user_id == user.id)
        .order_by(PlaybackSession.started_at.desc()).limit(300)
    ).all()
    seen, items = set(), []
    for s in sessions:
        if s.movie_id in seen:
            continue
        seen.add(s.movie_id)          # only the most recent session of each title counts
        ratio = completion_ratio(s)
        if ratio is None or s.completed or ratio >= 0.9 or not s.drop_off_sec:
            continue
        card = card_for(state, db, s.movie_id, stats)
        if card is None:
            continue
        minutes = int(s.drop_off_sec // 60)
        card.update({"score": round(ratio, 4), "reason": f"Continue from {minutes} min",
                     "progress": round(ratio, 4), "resume_sec": float(s.drop_off_sec)})
        items.append(card)
        if len(items) >= ROW_LIMIT:
            break
    return items


def _favourite_decade(state, us) -> int:
    """Decade of the titles this user rates highest (default: the 90s)."""
    decades = [int(state.decade[i]) for i, r in us.rated.items()
               if r >= 4.0 and not np.isnan(state.decade[i])]
    if decades:
        best = max(set(decades), key=decades.count)
        if 1950 <= best <= 2010:
            return best
    return 1990


def _time_fit_minutes(us) -> int:
    """90 minutes, or shorter if this user usually stops watching early."""
    typical = us.profile.typical_drop_off_min if us is not None else None
    if typical and typical < 85:
        return 60 if typical < 65 else 90
    return 90


def popularity_rows(state, us, stats: dict) -> list[dict]:
    """Rows used when there is no model (or the engine failed): simple
    popularity / quality lists that still respect each row's filter."""
    rows = []
    simple_rows = [
        ("trending", "Trending now", "Popular right now", {"preset": "trending"}, None),
        ("acclaimed", "Critically acclaimed", "Loved by critics and audiences", {"preset": "acclaimed"},
         state.quality),
        ("series_binge", "Series to binge", "One more episode…", {"content_type": "series"}, None),
    ]
    for row_id, title, subtitle, row_filter, order in simple_rows:
        ctx = {k: v for k, v in row_filter.items() if k != "preset"}
        result = popularity_fallback(state, us, prepare(state, ctx), ROW_LIMIT, order=order)
        items = rec_items(state, result, stats)
        if len(items) >= MIN_ROW_ITEMS:
            rows.append({"id": row_id, "title": title, "subtitle": subtitle, "filter": row_filter, "items": items})
    return rows


def personalised_rows(db: Session, user: User, state, info: dict, stats: dict, rows: list[dict]) -> bool:
    """Append every personalised row to `rows`. Returns needs_onboarding.
    The user state (fold-in, taste, behaviour) is computed once for all rows."""
    tod = info["time_of_day"]
    us = build_user_state(db, user.id, state)
    needs_onboarding = us.rating_count < ONBOARDING_MIN_RATINGS
    shown = np.zeros(state.n, dtype=np.float32)   # 1 = already shown in an earlier row

    def add_row(row_id: str, title: str, subtitle: str, row_filter: dict) -> None:
        prep = prepare(state, row_filter)
        result = recommend(state, us, prep, ROW_LIMIT, penalty=REPEAT_PENALTY * shown)
        if result is None or len(result.items) < MIN_ROW_ITEMS:
            return
        for item in result.items:
            shown[item[0]] = 1.0
        rows.append({"id": row_id, "title": title, "subtitle": subtitle,
                     "filter": row_filter, "items": rec_items(state, result, stats)})

    has_ratings = us.rating_count > 0
    add_row("for_you", "Recommended for you",
            "Based on your ratings" if has_ratings else "Popular picks to get you started", {})

    recent_loved = db.execute(
        select(Rating.movie_id, Rating.rating).where(Rating.user_id == user.id, Rating.rating >= 4.0)
        .order_by(Rating.created_at.desc()).limit(2)
    ).all()
    for movie_id, rating in recent_loved:
        i = state.idx(movie_id)
        if i is not None:
            add_row(f"because_{movie_id}", f"Because you rated {state.title[i]}",
                    f"You gave it {stars(float(rating))}", {"reference_movie_ids": [int(movie_id)]})

    weather = info["weather"]
    if weather:
        word = TIME_OF_DAY_WORDS.get(tod, "day")
        where = f" in {weather['city']}" if weather.get("city") else ""
        temp = f", {weather['temp_c']:.0f}°C" if weather.get("temp_c") is not None else ""
        add_row("weather", f"Perfect for this {WEATHER_ADJECTIVE[weather['id']]} {word}",
                f"{weather['label']}{temp}{where}", {"weather": weather["id"], "time_of_day": tod})

    minutes = _time_fit_minutes(us)
    add_row("time_fit", f"Fits in {minutes} minutes", "Short on time? These finish in time",
            {"time_available_min": minutes})

    festival = info["upcoming_festival"]
    if festival:
        days = festival["days_away"]
        when = "is today" if days == 0 else "is tomorrow" if days == 1 else f"is in {days} days"
        add_row("festival", f"For {FESTIVAL_INFO[festival['id']][0]}",
                f"{festival['label']} {when}", {"festival": festival["id"]})

    add_row("trending", "Trending now", "What everyone is watching", {"preset": "trending"})
    add_row("acclaimed", "Critically acclaimed", "Loved by critics and audiences", {"preset": "acclaimed"})
    add_row("hidden_gems", "Hidden gems", "Brilliant titles you may have missed", {"preset": "hidden_gems"})
    add_row("feel_good", "Feel-good picks", "Guaranteed to end on a high", {"end_emotion": "joy"})
    decade = _favourite_decade(state, us)
    add_row("nostalgia", f"{str(decade)[2:]}s nostalgia", f"Back to the {decade}s",
            {"nostalgia_decade": decade})
    add_row("series_binge", "Series to binge", "One more episode…", {"content_type": "series"})
    add_row("date_night", "Date night", "Romance, laughs and good vibes", {"occasion": "date_night"})
    add_row("mind_bending", "Mind-bending", "Films that mess with your head", {"preset": "mind_bending"})
    return needs_onboarding


@router.get("/home")
def home(request: Request, lat: str | None = None, lon: str | None = None, hour: str | None = None,
         user: User = Depends(get_current_user), state=Depends(get_model_state),
         db: Session = Depends(get_db)):
    started = time.perf_counter()
    info = build_context_info(lat, lon, hour)
    stats = rating_stats.get_stats(db)
    tod = info["time_of_day"]
    rows: list[dict] = []
    fallback = state is None or not state.has_model

    with engine_slot():   # bounded number of heavy requests at once
        cw_items = continue_watching(db, user, state, stats)
        if len(cw_items) >= MIN_ROW_ITEMS:
            rows.append({"id": "continue_watching", "title": "Continue watching",
                         "subtitle": "Pick up where you left off", "filter": {}, "items": cw_items})

        if state is None:
            ratings, dismissed, _, _ = load_user_rows(db, user.id)
            needs_onboarding = len(ratings) < ONBOARDING_MIN_RATINGS
            result = db_popularity_fallback(db, {}, {m for m, _ in ratings}, dismissed, ROW_LIMIT)
            items = rec_items(state, result, stats)
            if items:
                rows.append({"id": "trending", "title": "Trending now", "subtitle": "Popular right now",
                             "filter": {"preset": "trending"}, "items": items})
        elif not state.has_model:
            us = build_user_state(db, user.id, state)
            needs_onboarding = us.rating_count < ONBOARDING_MIN_RATINGS
            rows += popularity_rows(state, us, stats)
        else:
            try:
                needs_onboarding = personalised_rows(db, user, state, info, stats, rows)
            except Exception:   # never a 500 for the home page: fall back to popularity rows
                log.exception("personalised home rows failed - using popularity rows")
                fallback = True
                us = build_user_state(db, user.id, state)
                needs_onboarding = us.rating_count < ONBOARDING_MIN_RATINGS
                rows = [r for r in rows if r["id"] == "continue_watching"] + popularity_rows(state, us, stats)

    # hero: the first personalised pick that has a big backdrop image
    hero = None
    for row in rows:
        if row["id"] == "continue_watching":
            continue
        hero = next((c for c in row["items"][:5] if c.get("backdrop_url")), row["items"][0] if row["items"] else None)
        if hero:
            break

    request_id = request.state.request_id
    all_ids = list(dict.fromkeys(c["movie_id"] for row in rows for c in row["items"]))
    log_context = {"time_of_day": tod, "hour": info["hour"], "weather_status": info["weather_status"]}
    if info["weather"]:
        log_context["weather"] = info["weather"]["id"]
    if info["upcoming_festival"]:
        log_context["festival"] = info["upcoming_festival"]["id"]
    log_context["rows"] = [row["id"] for row in rows]
    latency = (time.perf_counter() - started) * 1000
    log_recommendation(db, request_id, user.id, "/api/home", log_context, all_ids, fallback, latency)

    return json_response({
        "request_id": str(request_id),
        "context": info,
        "needs_onboarding": needs_onboarding,
        "hero": hero,
        "rows": rows,
    })
