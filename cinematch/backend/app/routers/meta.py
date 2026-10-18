"""
/api/meta — everything the Mood Mixer UI needs to draw its filter controls.
"""
from datetime import date

import numpy as np
from fastapi import APIRouter, Depends, Query

from app.deps import get_model_state
from app.services.festivals import next_date
from app.vocab import (
    AGE_RATINGS, CONTENT_TYPE, EMOTION_LABELS, EMOTIONS, FESTIVAL_INFO, FESTIVALS, GENRES,
    OCCASION_INFO, OCCASIONS, TIME_AVAILABLE_MIN, TIME_OF_DAY, WEATHER, WEATHER_INFO, language_name,
)

router = APIRouter(prefix="/api/meta", tags=["meta"])

_cache: dict = {}   # (version, today) -> response


def _time_label(minutes: int | None) -> str:
    if minutes is None:
        return "No limit"
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes / 60
    return f"{hours:g} hour" + ("" if hours == 1 else "s")


def _build_filters(state, today: date) -> dict:
    data = {
        "genres": list(GENRES),
        "languages": [],
        "age_ratings": list(AGE_RATINGS),
        "decades": [],
        "weather": [{"id": w, "label": WEATHER_INFO[w][0], "icon": WEATHER_INFO[w][1]} for w in WEATHER],
        "time_of_day": list(TIME_OF_DAY),
        "time_available": [{"minutes": m, "label": _time_label(m)} for m in TIME_AVAILABLE_MIN],
        "occasions": [{"id": o, "label": OCCASION_INFO[o][0], "icon": OCCASION_INFO[o][1]} for o in OCCASIONS],
        "festivals": [],
        "emotions": [{"id": e, "label": EMOTION_LABELS[e]} for e in EMOTIONS],
        "franchises": [],
        "directors": [],
        "actors": [],
        "content_types": list(CONTENT_TYPE),
    }
    for f in FESTIVALS:
        entry = {"id": f, "label": FESTIVAL_INFO[f][0], "icon": FESTIVAL_INFO[f][1]}
        day = next_date(f, today)
        if day is not None:
            entry["date"] = day.isoformat()
        data["festivals"].append(entry)

    if state is not None and state.n > 0:
        present = state.genre_matrix.any(axis=0)
        data["genres"] = [g for g, ok in zip(GENRES, present) if ok]
        counts = np.bincount(state.lang_idx[state.lang_idx >= 0], minlength=len(state.lang_codes))
        data["languages"] = [
            {"code": state.lang_codes[j], "name": language_name(state.lang_codes[j])}
            for j in np.argsort(-counts) if counts[j] > 0 and state.lang_codes[j]
        ]
        decades = state.decade[~np.isnan(state.decade)]
        data["decades"] = sorted({int(d) for d in decades})
        data["franchises"] = state.franchises_ranked[:50]
        data["directors"] = state.directors.top(100)
        data["actors"] = state.actors.top(150)
    return data


@router.get("/filters")
def filters(state=Depends(get_model_state)):
    today = date.today()
    key = (state.version if state is not None else None, today)
    if key not in _cache:
        _cache.clear()
        _cache[key] = _build_filters(state, today)
    return _cache[key]


@router.get("/people")
def people(role: str = Query("director", pattern="^(director|actor)$"),
           q: str = Query("", max_length=100),
           limit: int = Query(10, ge=1, le=50),
           state=Depends(get_model_state)):
    if state is None:
        return {"items": []}
    return {"items": state.people_matching(role, q, limit)}
