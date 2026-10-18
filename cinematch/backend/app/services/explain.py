"""
Reason strings (FR-4.3): one short sentence per recommended item.

We pick the component that did the most to lift THIS item above the other
candidates (weight x (item value - average value in the candidate pool)) and
turn it into text:

    cf        -> "Because you rated Inception 5★"
    content   -> "Because you liked Interstellar"
    ref       -> "Because you picked The Dark Knight"
    ctx       -> the context signal that fits best, e.g. "Perfect for a rainy evening",
                 "Starts tense, ends happy", "Great for date night"
    quality   -> "Critics love it (92)"
    trend     -> "Trending now"
    behavior  -> "You finish most Thriller films"
"""
import math

import numpy as np

from app.services.behavior import best_genre_for


def stars(rating: float) -> str:
    """4.0 -> '4★', 4.5 -> '4.5★'."""
    return f"{rating:g}★"


def _most_similar_liked(state, us, i: int, use_factors: bool) -> int | None:
    """Position (in us.liked_idx) of the liked item most similar to item i."""
    if len(us.liked_idx) == 0:
        return None
    if use_factors and state.has_model and state.has_cf[i]:
        liked = us.liked_idx[state.has_cf[us.liked_idx]]
        if len(liked) > 0:
            sims = (state.Q[liked] @ state.Q[i]) / (state.q_norm[liked] * state.q_norm[i] + 1e-9)
            return int(np.flatnonzero(us.liked_idx == liked[int(np.argmax(sims))])[0])
    if state.has_model and state.emb is not None and state.has_emb[i]:
        liked = us.liked_idx[state.has_emb[us.liked_idx]]
        if len(liked) > 0:
            sims = state.emb_rows(liked) @ state.emb_rows([i])[0]
            return int(np.flatnonzero(us.liked_idx == liked[int(np.argmax(sims))])[0])
    return 0  # fall back to their top-rated title


def quality_reason(state, i: int) -> str:
    critic = float(state.critic_score[i])
    if not math.isnan(critic) and critic >= 60:
        return f"Critics love it ({int(round(critic))})"
    mean = float(state.ml_mean[i])
    if not math.isnan(mean) and state.ml_count[i] >= 20:
        return f"Highly rated ({mean:.1f}★)"
    return "Highly rated"


def reason_for_component(state, us, prep, key: str, i: int) -> str:
    if key == "cf":
        pos = _most_similar_liked(state, us, i, use_factors=True)
        if pos is None:
            return "Matches your taste"
        j = int(us.liked_idx[pos])
        return f"Because you rated {state.title[j]} {stars(float(us.liked_ratings[pos]))}"
    if key == "content":
        pos = _most_similar_liked(state, us, i, use_factors=False)
        if pos is None:
            return "Similar to what you enjoy"
        return f"Because you liked {state.title[int(us.liked_idx[pos])]}"
    if key == "ref" and prep.ref_idx:
        ref = prep.ref_idx[int(prep.ref_best[i])] if prep.ref_best is not None else prep.ref_idx[0]
        return f"Because you picked {state.title[ref]}"
    if key == "ctx" and prep.parts:
        best = max(prep.parts, key=lambda p: p.weight * float(p.values[i]))
        return best.reason(state, i)
    if key == "quality":
        return quality_reason(state, i)
    if key == "behavior":
        genre = best_genre_for(state, us.profile, i)
        if genre:
            return f"You finish most {genre} films"
        if state.is_series[i] and us.profile.binge_score > 0:
            return "Great for a binge"
        return "Fits how you watch"
    return "Trending now"


def reasons_for(state, us, prep, comps: dict, weights: dict, chosen, pool) -> list[str]:
    """One reason per chosen item (see module docstring)."""
    pool = np.asarray(pool)
    pool_means = {k: float(arr[pool].mean()) for k, arr in comps.items()}
    out = []
    for i in chosen:
        lifts = {k: weights.get(k, 0.0) * (float(arr[i]) - pool_means[k]) for k, arr in comps.items()}
        # tiny tie-break so a cold-start list without context still varies its reasons
        best = max(lifts, key=lambda k: (lifts[k], k == "quality"))
        out.append(reason_for_component(state, us, prep, best, int(i)))
    return out
