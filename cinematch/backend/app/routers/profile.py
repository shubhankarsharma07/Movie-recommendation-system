"""
GET /api/profile/insights — "your taste" page: top genres, viewing habits and
a one-line taste summary built from ratings + behaviour.
"""
from collections import Counter

import numpy as np
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, get_model_state
from app.models import User
from app.services.recommender import build_user_state, engine_slot, load_user_rows
from app.vocab import GENRES, MOOD_TAGS

router = APIRouter(prefix="/api/profile", tags=["profile"])

# "You love mind-bending sci-fi and feel-good comedies"
GENRE_NOUNS = {
    "Action": "action films", "Adventure": "adventures", "Animation": "animated films",
    "Children": "kids' films", "Comedy": "comedies", "Crime": "crime stories",
    "Documentary": "documentaries", "Drama": "dramas", "Fantasy": "fantasy", "Film-Noir": "film noir",
    "Horror": "horror", "IMAX": "big-screen spectacles", "Musical": "musicals", "Mystery": "mysteries",
    "Romance": "romances", "Sci-Fi": "sci-fi", "Thriller": "thrillers", "War": "war films",
    "Western": "westerns",
}


def _r(value, digits=3):
    return None if value is None else round(float(value), digits)


@router.get("/insights")
def insights(user: User = Depends(get_current_user), state=Depends(get_model_state),
             db: Session = Depends(get_db)):
    if state is None:
        ratings, _, sessions, _ = load_user_rows(db, user.id)
        return {"top_genres": [], "completion_rate": None, "avg_browse_to_select_ms": None,
                "rewatch_count": sum(1 for s in sessions if s.is_rewatch), "binge_score": 0.0,
                "seek_forward_rate": 0.0, "favourite_decade": None, "ratings_count": len(ratings),
                "sessions_count": len(sessions),
                "taste_summary": "Rate a few titles and we'll learn your taste."}

    with engine_slot():
        us = build_user_state(db, user.id, state)
    profile = us.profile

    # genre score: how much above "average" (2.5★) the user rates each genre,
    # plus how much they finish it; shrunk towards 0 for few data points
    total = np.zeros(len(GENRES))
    count = np.zeros(len(GENRES))
    for i, rating in us.rated.items():
        row = state.genre_matrix[i]
        total[row] += (rating - 2.5) / 2.5
        count[row] += 1
    for j, genre in enumerate(GENRES):
        if genre in profile.genre_engagement:
            total[j] += 0.5 * profile.genre_engagement[genre]
            count[j] += 0.5
    raw = total / (count + 2.0)
    score = 0.5 + 0.5 * np.tanh(2.0 * raw)
    ranked = [j for j in np.argsort(-score) if count[j] > 0 and raw[j] > 0][:5]
    top_genres = [{"genre": GENRES[j], "score": round(float(score[j]), 3)} for j in ranked]

    # favourite decade from loved + finished titles
    loved = [i for i, r in us.rated.items() if r >= 4.0]
    loved += [state.idx(m) for m in profile.finished_movie_ids if state.idx(m) is not None]
    decades = [int(state.decade[i]) for i in loved if not np.isnan(state.decade[i])]
    favourite_decade = Counter(decades).most_common(1)[0][0] if decades else None

    return {
        "top_genres": top_genres,
        "completion_rate": _r(profile.completion_rate),
        "avg_browse_to_select_ms": _r(profile.avg_browse_to_select_ms, 1),
        "rewatch_count": profile.rewatch_count,
        "binge_score": _r(profile.binge_score),
        "seek_forward_rate": _r(profile.seek_forward_rate),
        "favourite_decade": favourite_decade,
        "ratings_count": us.rating_count,
        "sessions_count": profile.sessions_count,
        "taste_summary": taste_summary(state, [GENRES[j] for j in ranked[:2]], loved),
    }


def taste_summary(state, genres: list[str], loved: list[int]) -> str:
    """'You love mind-bending sci-fi and feel-good comedies.'"""
    if not genres:
        return "Rate a few titles and we'll learn your taste."
    phrases = []
    for genre in genres:
        g = GENRES.index(genre)
        moods = Counter()
        for i in loved:
            if state.genre_matrix[i, g]:
                for m in np.flatnonzero(state.mood_matrix[i]):
                    moods[MOOD_TAGS[m]] += 1
        used = {p.split(" ")[0] for p in phrases}
        mood = next((m for m, _ in moods.most_common() if m not in used), None)
        noun = GENRE_NOUNS.get(genre, genre.lower())
        phrases.append(f"{mood} {noun}" if mood else noun)
    return "You love " + " and ".join(phrases) + "."
