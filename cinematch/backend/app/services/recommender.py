"""
The recommendation engine. Everything is vectorised numpy over ALL N items, so
one request costs a handful of array operations even for 65,000 titles (NFR-1).

Pipeline for one request
------------------------
1. User state (built once per request, reused by every /api/home row):
     * CF by FOLD-IN: the item factors q_i are fixed; we solve for this user's
       bias b_u and vector p_u from their in-app ratings (+ behaviour
       pseudo-ratings with a lower weight). So the list changes right after
       every new rating - no retraining needed.
           b_u = Σ w(r − μ − b_i) / (Σw + 5)
           p_u = (QᵀWQ + λ·n·I)⁻¹ QᵀW(r − μ − b_u − b_i)
           cf_pred = μ + b_u + b_i + q_i·p_u        cf_norm = (cf_pred − 0.5) / 4.5
     * content taste = weighted mean embedding of liked titles minus disliked ones
     * behaviour vector (behavior.py)
2. Request preparation (no user needed): context signals (rules.py), reference
   film similarity, hard filters, label.
3. score = Σ w·component / Σ w   (components that are absent get weight 0)
4. Hard filters, relaxed in a fixed order if fewer than `limit` items survive
   (exact matches stay on top).
5. MMR diversity re-rank of the top 200 -> `limit` items, each with a reason.
6. Fallback: popularity list "Trending now" (model missing / nothing usable).
"""
import logging
import math
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Dismissal, Event, Movie, PlaybackSession, Rating
from app.services import explain, rules
from app.services.behavior import BehaviorProfile, behavior_vector, build_profile
from app.vocab import (
    AGE_RATINGS, EMOTION_LABELS, FESTIVAL_INFO, GENRES, OCCASION_INFO, TIME_OF_DAY_WORDS,
)

log = logging.getLogger("cinematch.recommender")

PSEUDO_RATING_WEIGHT = 0.5      # behaviour pseudo-ratings count half as much as real ones
LIKED = 3.5
DISLIKED = 2.0
CANDIDATE_POOL = 200            # MMR re-ranks this many top items
MMR_LAMBDA = 0.75
MMR_LAMBDA_UNDECIDED = 0.65     # long browse-to-select -> more diverse list
UNDECIDED_MS = 60_000
STRICT_BOOST = 1.0              # after relaxing, exact matches still come first

# At most this many requests run the heavy numpy scoring at the same time.
# Each one needs ~10-20 MB of temporary arrays on a 65k catalog: unlimited
# parallel requests could run a 512 MB server out of memory, and with a
# fraction of a CPU more parallel number crunching would not be faster anyway.
ENGINE_SLOTS = threading.BoundedSemaphore(4)


@contextmanager
def engine_slot():
    """Wrap any heavy scoring work: `with engine_slot(): ...`"""
    with ENGINE_SLOTS:
        yield


# Order in which hard filters are relaxed when too few items match (CONTRACT 5.6 / brief).
RELAX_ORDER = ["actors", "directors", "language", "franchise", "runtime", "preset"]
LAST_RESORT = ["content_type", "age"]   # only if NOTHING at all would be left
FILTER_NAMES = {"actors": "actor", "directors": "director", "language": "language",
                "franchise": "franchise", "runtime": "time", "preset": "preset",
                "content_type": "content type", "age": "age rating"}


# ================================================================================== user state
@dataclass
class UserState:
    user_id: object = None
    rated: dict = field(default_factory=dict)          # catalog index -> explicit rating
    rated_ids: set = field(default_factory=set)        # every movie_id the user rated
    dismissed_ids: set = field(default_factory=set)
    profile: BehaviorProfile = field(default_factory=BehaviorProfile)
    cf_pred: np.ndarray | None = None                  # predicted stars for every item
    cf_norm: np.ndarray | None = None                  # 0..1, None = cold start
    content: np.ndarray | None = None                  # 0..1 plot similarity to taste
    behavior: np.ndarray | None = None                 # 0..1, None = no viewing data
    liked_idx: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    liked_ratings: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    exclude_mask: np.ndarray | None = None             # rated or dismissed
    dismissed_mask: np.ndarray | None = None
    rated_mask: np.ndarray | None = None
    mmr_lambda: float = MMR_LAMBDA

    @property
    def rating_count(self) -> int:
        return len(self.rated_ids)


def load_user_rows(db: Session, user_id):
    """The four small queries that describe a user."""
    ratings = db.execute(select(Rating.movie_id, Rating.rating).where(Rating.user_id == user_id)).all()
    dismissed = db.scalars(select(Dismissal.movie_id).where(Dismissal.user_id == user_id)).all()
    sessions = db.scalars(
        select(PlaybackSession).where(PlaybackSession.user_id == user_id)
        .order_by(PlaybackSession.started_at.desc()).limit(500)
    ).all()
    events = db.scalars(
        select(Event).where(Event.user_id == user_id, Event.type.in_(["select", "binge_next"]))
        .order_by(Event.created_at.desc()).limit(500)
    ).all()
    return [(int(m), float(r)) for m, r in ratings], set(int(m) for m in dismissed), sessions, events


def build_user_state(db: Session, user_id, state) -> UserState:
    ratings, dismissed, sessions, events = load_user_rows(db, user_id)
    return compute_user_state(state, user_id, ratings, dismissed, sessions, events)


def _fold_in(state, idx: np.ndarray, r: np.ndarray, w: np.ndarray):
    """Solve this user's (b_u, p_u) against the FIXED item factors."""
    keep = state.has_cf[idx]
    idx, r, w = idx[keep], r[keep], w[keep]
    if len(idx) == 0:
        return None
    mu = state.global_mean
    b_i = state.item_bias[idx].astype(np.float64)
    n = float(w.sum())
    b_u = float((w * (r - mu - b_i)).sum() / (n + 5.0))
    residual = r - mu - b_u - b_i
    Qr = state.Q[idx].astype(np.float64)
    Wq = Qr * w[:, None]
    k = Qr.shape[1]
    A = Wq.T @ Qr + (state.fold_in_reg * n + 1e-6) * np.eye(k)
    p_u = np.linalg.solve(A, Wq.T @ residual)
    return b_u, p_u.astype(np.float32)


def compute_user_state(state, user_id, ratings, dismissed, sessions, events) -> UserState:
    """Pure function (no DB): everything about the user the scorer needs."""
    us = UserState(user_id=user_id)
    us.rated_ids = {m for m, _ in ratings}
    us.dismissed_ids = set(dismissed)
    us.profile = build_profile(sessions, events, state)
    if us.profile.avg_browse_to_select_ms and us.profile.avg_browse_to_select_ms > UNDECIDED_MS:
        us.mmr_lambda = MMR_LAMBDA_UNDECIDED

    n = state.n
    us.rated_mask = np.zeros(n, dtype=bool)
    us.dismissed_mask = np.zeros(n, dtype=bool)
    for movie_id, value in ratings:
        i = state.idx(movie_id)
        if i is not None:
            us.rated[i] = value
            us.rated_mask[i] = True
    for movie_id in us.dismissed_ids:
        i = state.idx(movie_id)
        if i is not None:
            us.dismissed_mask[i] = True
    us.exclude_mask = us.rated_mask | us.dismissed_mask

    # liked titles (for reasons), best first
    liked = sorted(((i, r) for i, r in us.rated.items() if r >= LIKED), key=lambda x: -x[1])
    us.liked_idx = np.array([i for i, _ in liked], dtype=np.int64)
    us.liked_ratings = np.array([r for _, r in liked], dtype=np.float32)

    if not state.has_model:
        return us

    # explicit ratings (weight 1) + behaviour pseudo-ratings (weight 0.5); explicit wins
    training = [(i, r, 1.0) for i, r in us.rated.items()]
    for movie_id, r in us.profile.pseudo_ratings.items():
        i = state.idx(movie_id)
        if i is not None and i not in us.rated:
            training.append((i, r, PSEUDO_RATING_WEIGHT))
    idx = np.array([t[0] for t in training], dtype=np.int64)
    vals = np.array([t[1] for t in training], dtype=np.float64)
    wts = np.array([t[2] for t in training], dtype=np.float64)

    # --- 1. collaborative filtering (fold-in)
    solved = _fold_in(state, idx, vals, wts) if len(idx) else None
    if solved is not None:
        b_u, p_u = solved
        pred = state.global_mean + b_u + state.item_bias + state.Q @ p_u
        us.cf_pred = np.clip(pred, 0.5, 5.0).astype(np.float32)     # stars, for display
        # For RANKING we use the unclipped prediction: clipping at 5★ would make
        # every "very likely to love it" item tie with the others.
        us.cf_norm = np.maximum((pred - 0.5) / 4.5, 0.0).astype(np.float32)
    else:
        # cold start: baseline prediction only (used for party star estimates)
        us.cf_pred = np.clip(state.global_mean + state.item_bias, 0.5, 5.0).astype(np.float32)

    # --- 2. content taste vector
    if state.emb is not None and len(idx):
        has = state.has_emb[idx]
        good = has & (vals >= LIKED)
        bad = has & (vals <= DISLIKED)
        taste = None
        if good.any():
            weight = (vals[good] - 3.0) * wts[good]
            taste = (state.emb_rows(idx[good]) * weight[:, None]).sum(0) / weight.sum()
        if bad.any():
            weight = (3.0 - vals[bad]) * wts[bad]
            negative = (state.emb_rows(idx[bad]) * weight[:, None]).sum(0) / weight.sum()
            taste = (-0.5 * negative) if taste is None else taste - 0.5 * negative
        if taste is not None and np.linalg.norm(taste) > 1e-6:
            taste = taste / np.linalg.norm(taste)
            sims = np.clip(state.emb_dot(taste), 0.0, None)
            sims[~state.has_emb] = 0.0
            top = float(sims.max())
            if top > 0:
                us.content = (sims / top).astype(np.float32)

    # --- 3. behaviour
    us.behavior = behavior_vector(state, us.profile)
    return us


# ================================================================================== request preparation
@dataclass
class Prepared:
    ctx: dict                                  # effective context (returned as context_used)
    parts: list = field(default_factory=list)  # rules.CtxPart list
    ctx_score: np.ndarray | None = None
    ref_idx: list = field(default_factory=list)
    ref_sim: np.ndarray | None = None
    ref_best: np.ndarray | None = None
    filters: dict = field(default_factory=dict)   # name -> bool mask (True = allowed)
    ref_exclude: np.ndarray | None = None
    weights: dict = field(default_factory=dict)
    label: str = "Recommended for you"


def _rows_for_names(index, names: list[str], n: int) -> np.ndarray:
    """Items made by ANY of the given people (index = state.directors / state.actors)."""
    mask = np.zeros(n, dtype=bool)
    for name in names:
        rows = index.rows(name)
        if rows is not None:
            mask[rows] = True
    return mask


def hard_filters(state, ctx: dict) -> dict:
    """Every hard filter in the context as a boolean mask over all items."""
    n = state.n
    filters = {}
    if ctx.get("content_type") in ("movie", "series"):
        filters["content_type"] = state.is_series if ctx["content_type"] == "series" else ~state.is_series
    cap = ctx.get("max_age_rating")
    if cap in AGE_RATINGS:
        cap_i = AGE_RATINGS.index(cap)
        known_ok = (state.age_idx >= 0) & (state.age_idx <= cap_i)
        if cap_i >= AGE_RATINGS.index("UA 16+"):
            unknown_ok = state.age_idx < 0
        else:
            # strict caps (kids/family): an unrated title only passes if it is
            # clearly made for children
            kid_cols = [GENRES.index("Animation"), GENRES.index("Children")]
            unknown_ok = (state.age_idx < 0) & state.genre_matrix[:, kid_cols].any(axis=1)
        filters["age"] = known_ok | unknown_ok
    if ctx.get("time_available_min"):
        limit = ctx["time_available_min"] * 1.10   # 10 % grace
        runtime = state.runtime
        filters["runtime"] = ~np.isnan(runtime) & (runtime <= limit)
    if ctx.get("language"):
        code = ctx["language"]
        if code in state.lang_codes:
            filters["language"] = state.lang_idx == state.lang_codes.index(code)
        else:
            filters["language"] = np.zeros(n, dtype=bool)
    if ctx.get("franchise_mode") == "only":
        filters["franchise"] = state.in_collection.copy()
    elif ctx.get("franchise_mode") == "exclude":
        filters["franchise"] = ~state.in_collection
    if ctx.get("directors"):
        filters["directors"] = _rows_for_names(state.directors, ctx["directors"], n)
    if ctx.get("actors"):
        filters["actors"] = _rows_for_names(state.actors, ctx["actors"], n)
    preset = rules.PRESET_RULES.get(ctx.get("preset") or "")
    if preset and ("min_quality_pct" in preset or "max_popularity_pct" in preset):
        mask = np.ones(n, dtype=bool)
        if "min_quality_pct" in preset:
            mask &= state.quality >= np.quantile(state.quality, preset["min_quality_pct"])
        if "max_popularity_pct" in preset:
            mask &= state.popularity <= np.quantile(state.popularity, preset["max_popularity_pct"])
        filters["preset"] = mask
    return filters


def apply_filters(filters: dict, base: np.ndarray, limit: int):
    """AND all filters together; if fewer than `limit` items survive, drop
    filters in RELAX_ORDER until enough do. Returns (mask, strict_mask, relaxed)."""
    def combine(names):
        mask = base.copy()
        for name in names:
            mask &= filters[name]
        return mask

    active = list(filters)
    strict = combine(active)
    mask = strict
    relaxed = []
    for name in RELAX_ORDER:
        if mask.sum() >= limit:
            break
        if name in active:
            active.remove(name)
            relaxed.append(name)
            mask = combine(active)
    if not mask.any():
        for name in LAST_RESORT:
            if name in active:
                active.remove(name)
                relaxed.append(name)
                mask = combine(active)
    return mask, strict, relaxed


def _make_label(state, ctx: dict, ref_idx: list) -> str:
    preset = rules.PRESET_RULES.get(ctx.get("preset") or "")
    if preset:
        return preset["label"]
    if ctx.get("occasion"):
        return f"{OCCASION_INFO[ctx['occasion']][0]} picks"
    if ctx.get("festival"):
        return f"For {FESTIVAL_INFO[ctx['festival']][0]}"
    if ref_idx:
        return f"Because you picked {state.title[ref_idx[0]]}"
    if ctx.get("weather"):
        word = TIME_OF_DAY_WORDS.get(ctx.get("time_of_day"), "day")
        return f"Perfect for a {rules.WEATHER_ADJECTIVE[ctx['weather']]} {word}"
    if ctx.get("start_emotion") and ctx.get("end_emotion"):
        return (f"Starts {EMOTION_LABELS[ctx['start_emotion']].lower()}, "
                f"ends {EMOTION_LABELS[ctx['end_emotion']].lower()}")
    if ctx.get("end_emotion"):
        return f"Leaves you {EMOTION_LABELS[ctx['end_emotion']].lower()}"
    if ctx.get("nostalgia_decade"):
        return f"{str(ctx['nostalgia_decade'])[2:]}s nostalgia"
    if ctx.get("genres"):
        return " & ".join(ctx["genres"][:2]) + " picks"
    if ctx.get("directors"):
        return f"Films by {ctx['directors'][0]}"
    if ctx.get("actors"):
        return f"Starring {ctx['actors'][0]}"
    if ctx.get("content_type") == "series":
        return "Series for you"
    if ctx.get("time_available_min"):
        return f"Fits in {ctx['time_available_min']} minutes"
    return "Recommended for you"


def prepare(state, ctx: dict) -> Prepared:
    """Everything about the request that does not depend on the user."""
    ctx = dict(ctx)
    cap = rules.stricter_age(ctx.get("max_age_rating"), rules.occasion_age_cap(ctx.get("occasion")))
    if cap:
        ctx["max_age_rating"] = cap
    prep = Prepared(ctx=ctx)

    # reference films ("more like these")
    refs = []
    for movie_id in ctx.get("reference_movie_ids", []):
        i = state.idx(movie_id)
        if i is not None and i not in refs:
            refs.append(i)
    prep.ref_idx = refs
    prep.ref_exclude = np.zeros(state.n, dtype=bool)
    if refs:
        prep.ref_exclude[refs] = True
    if refs and state.has_model:
        prep.ref_sim, prep.ref_best = _reference_similarity(state, refs)

    prep.parts = rules.context_parts(state, ctx)
    prep.ctx_score = rules.combine_parts(prep.parts)
    prep.filters = hard_filters(state, ctx)

    weights = dict(getattr(state, "blend_weights", {}) or {})
    preset = rules.PRESET_RULES.get(ctx.get("preset") or "")
    if preset:
        weights.update(preset.get("weights", {}))
    prep.weights = weights
    prep.label = _make_label(state, ctx, refs)
    return prep


def _reference_similarity(state, refs: list[int]):
    """ref_sim = max over references of 0.5·cos(item factors) + 0.5·cos(plot emb).
    If one side is missing for a pair, the other side is used alone."""
    refs = np.asarray(refs)
    # CF side
    q_ref = state.Q[refs]                                         # [R, k]
    cf = (state.Q @ q_ref.T) / (state.q_norm[:, None] * state.q_norm[refs][None, :] + 1e-9)
    cf_ok = state.has_cf[:, None] & state.has_cf[refs][None, :]
    # content side
    if state.emb is not None:
        em = state.emb_dot(state.emb_rows(refs).T)                # [N, R]
        em_ok = state.has_emb[:, None] & state.has_emb[refs][None, :]
    else:
        em = np.zeros_like(cf)
        em_ok = np.zeros_like(cf_ok)
    both = cf_ok & em_ok
    sim = np.where(both, 0.5 * cf + 0.5 * em, np.where(cf_ok, cf, np.where(em_ok, em, 0.0)))
    best = np.argmax(sim, axis=1)
    sim = np.clip(sim.max(axis=1), 0.0, None)
    top = float(sim.max()) if sim.size else 0.0
    if top <= 0:
        return None, None
    return (sim / top).astype(np.float32), best


# ================================================================================== scoring
def score_items(state, us: UserState, prep: Prepared):
    """Blend all available components. Returns (score[N], components, weights)."""
    comps = {}
    if us.cf_norm is not None:
        comps["cf"] = us.cf_norm
    if us.content is not None:
        comps["content"] = us.content
    if prep.ref_sim is not None:
        comps["ref"] = prep.ref_sim
    if prep.ctx_score is not None:
        comps["ctx"] = prep.ctx_score
    comps["quality"] = state.quality
    comps["trend"] = state.trend
    if us.behavior is not None:
        comps["behavior"] = us.behavior
    weights = {k: float(prep.weights.get(k, 0.0)) for k in comps}
    comps = {k: v for k, v in comps.items() if weights[k] > 0}
    total = sum(weights[k] for k in comps) or 1.0
    score = np.zeros(state.n, dtype=np.float32)
    for k, arr in comps.items():
        score += (weights[k] / total) * arr
    return score, comps, {k: weights[k] / total for k in comps}


def _top_candidates(final: np.ndarray, mask: np.ndarray, k: int) -> np.ndarray:
    valid = np.flatnonzero(mask)
    if len(valid) > k:
        valid = valid[np.argpartition(-final[valid], k)[:k]]
    return valid[np.argsort(-final[valid], kind="stable")]


def mmr(state, candidates: np.ndarray, relevance: np.ndarray, limit: int, lam: float) -> list[int]:
    """Maximal Marginal Relevance: pick items one by one, trading relevance
    against similarity to what is already picked (genre Jaccard + plot cosine)."""
    if len(candidates) <= 1:
        return [int(c) for c in candidates[:limit]]
    rel = relevance.astype(np.float32)
    span = float(rel.max() - rel.min())
    rel = (rel - rel.min()) / span if span > 0 else np.ones_like(rel)

    G = state.genre_matrix[candidates].astype(np.float32)
    inter = G @ G.T
    sizes = G.sum(axis=1)
    union = sizes[:, None] + sizes[None, :] - inter
    jaccard = np.where(union > 0, inter / np.maximum(union, 1e-9), 0.0)
    if state.has_model and state.emb is not None:
        E = state.emb_rows(candidates)
        ok = state.has_emb[candidates]
        cos = np.clip(E @ E.T, 0.0, 1.0) * (ok[:, None] & ok[None, :])
        sim = 0.5 * jaccard + 0.5 * cos
    else:
        sim = jaccard

    picked = [0]
    max_sim = sim[0].copy()
    available = np.ones(len(candidates), dtype=bool)
    available[0] = False
    while len(picked) < min(limit, len(candidates)):
        value = lam * rel - (1.0 - lam) * max_sim
        value[~available] = -np.inf
        j = int(np.argmax(value))
        picked.append(j)
        available[j] = False
        max_sim = np.maximum(max_sim, sim[j])
    return [int(candidates[j]) for j in picked]


def _pick(state, pool, final, strict, relaxed, limit, lam) -> list[int]:
    """MMR over the pool. After relaxing filters, exact matches are picked
    first (guaranteed), then the relaxed ones fill the remaining places."""
    if not relaxed:
        return mmr(state, pool, final[pool], limit, lam)
    exact = pool[strict[pool]]
    chosen = mmr(state, exact, final[exact], limit, lam) if len(exact) else []
    if len(chosen) < limit:
        rest = pool[~strict[pool]]
        chosen += mmr(state, rest, final[rest], limit - len(chosen), lam) if len(rest) else []
    return chosen


@dataclass
class RecResult:
    items: list            # [(catalog index or Movie row, score, reason)]
    label: str
    fallback: bool
    context_used: dict
    relaxed: list = field(default_factory=list)
    from_db: bool = False  # items are Movie rows (no catalog in memory)


def _relaxed_label(label: str, relaxed: list) -> str:
    if not relaxed:
        return label
    names = ", ".join(FILTER_NAMES[r] for r in relaxed)
    plural = "s" if len(relaxed) > 1 else ""
    return f"{label} · relaxed {names} filter{plural}"


def recommend(state, us: UserState, prep: Prepared, limit: int = 20,
              penalty: np.ndarray | None = None) -> RecResult | None:
    """Personalised ranked list, or None if nothing usable (caller falls back)."""
    if not state.has_model:
        return None
    base = ~us.exclude_mask & ~prep.ref_exclude
    mask, strict, relaxed = apply_filters(prep.filters, base, limit)
    if not mask.any():
        return None
    score, comps, weights = score_items(state, us, prep)
    final = score.copy()
    if relaxed:
        final += STRICT_BOOST * strict
    if penalty is not None:
        final -= penalty
    pool = _top_candidates(final, mask, CANDIDATE_POOL)
    chosen = _pick(state, pool, final, strict, relaxed, limit, us.mmr_lambda)
    reasons = explain.reasons_for(state, us, prep, comps, weights, chosen, pool)
    items = [(i, float(score[i]), reason) for i, reason in zip(chosen, reasons)]
    return RecResult(items, _relaxed_label(prep.label, relaxed), False, prep.ctx, relaxed)


# ================================================================================== fallback
TRENDING = "Trending now"


def popularity_fallback(state, us: UserState | None, prep: Prepared, limit: int = 20,
                        order: np.ndarray | None = None) -> RecResult:
    """FR-4.4 / AC-3: popularity list that respects the (relaxable) hard filters.
    Never empty while the catalog has items the user has not dismissed."""
    n = state.n
    dismissed = us.dismissed_mask if us is not None and us.dismissed_mask is not None else np.zeros(n, bool)
    rated = us.rated_mask if us is not None and us.rated_mask is not None else np.zeros(n, bool)
    ref_ex = prep.ref_exclude if prep.ref_exclude is not None else np.zeros(n, bool)
    base = ~dismissed & ~rated & ~ref_ex
    if not base.any():
        base = ~dismissed            # user rated everything: show rated ones again
    mask, strict, relaxed = apply_filters(prep.filters, base, limit)
    value = (order if order is not None else state.popularity).astype(np.float32) + STRICT_BOOST * 10 * strict
    pool = _top_candidates(value, mask, limit)
    items = [(int(i), float(state.popularity[i]), TRENDING) for i in pool]
    return RecResult(items, TRENDING, True, prep.ctx, relaxed)


def db_popularity_fallback(db: Session, ctx: dict, exclude_ids: set, dismissed_ids: set,
                           limit: int = 20) -> RecResult:
    """Last line of defence when no catalog is in memory at all: popularity
    order straight from the `movies` table (filled from an earlier version).
    Same filter rules as the catalog fallback (only the columns the table has)."""
    ctx = dict(ctx)
    cap = rules.stricter_age(ctx.get("max_age_rating"), rules.occasion_age_cap(ctx.get("occasion")))
    if cap:
        ctx["max_age_rating"] = cap
    rows = db.scalars(select(Movie).order_by(Movie.popularity_score.desc()).limit(3000)).all()
    rows = [m for m in rows if m.movie_id not in dismissed_ids]
    fresh = [m for m in rows if m.movie_id not in exclude_ids]
    rows = fresh or rows

    def keep(m, names):
        if "content_type" in names and ctx.get("content_type") in ("movie", "series") \
                and m.content_type != ctx["content_type"]:
            return False
        if "age" in names and ctx.get("max_age_rating") in AGE_RATINGS:
            if m.age_rating not in AGE_RATINGS or \
                    AGE_RATINGS.index(m.age_rating) > AGE_RATINGS.index(ctx["max_age_rating"]):
                return False
        if "runtime" in names and ctx.get("time_available_min"):
            if m.runtime is None or m.runtime > ctx["time_available_min"] * 1.1:
                return False
        if "language" in names and ctx.get("language") and m.original_language != ctx["language"]:
            return False
        return True

    active = ["content_type", "age", "runtime", "language"]
    relaxed = []
    chosen = [m for m in rows if keep(m, active)]
    for name in ["language", "runtime", "content_type", "age"]:
        too_few = len(chosen) < limit if name in ("language", "runtime") else not chosen
        if not too_few:      # content type / age are only dropped if NOTHING is left
            continue
        active.remove(name)
        relaxed.append(name)
        seen = {m.movie_id for m in chosen}
        chosen += [m for m in rows if m.movie_id not in seen and keep(m, active)]
    items = [(m, float(m.popularity_score or 0.0), TRENDING) for m in chosen[:limit]]
    return RecResult(items, TRENDING, True, ctx, relaxed, from_db=True)


# ================================================================================== watch party
def party_recommend(state, members: list, prep: Prepared, limit: int = 20) -> RecResult | None:
    """members: [(display_name, UserState)]. 'Average without misery':
    z-normalise each member's scores, take mean − 0.5·std (disagreement
    penalty), and drop items any member WITH ratings is predicted to rate < 2.5."""
    if not state.has_model or not members:
        return None
    n = state.n
    dismissed_any = np.zeros(n, dtype=bool)
    rated_all = np.ones(n, dtype=bool)
    for _, us in members:
        dismissed_any |= us.dismissed_mask       # FR-4.5 holds for every member
        rated_all &= us.rated_mask                # everyone has already seen it
    base = ~dismissed_any & ~rated_all & ~prep.ref_exclude
    mask, strict, relaxed = apply_filters(prep.filters, base, limit)
    if not mask.any():
        return None

    z_rows = []
    for _, us in members:
        score, _, _ = score_items(state, us, prep)
        values = score[mask]
        sd = float(values.std()) or 1.0
        z_rows.append((score - float(values.mean())) / sd)
    Z = np.stack(z_rows)
    group = Z.mean(axis=0) - 0.5 * Z.std(axis=0)

    misery = np.zeros(n, dtype=bool)
    for _, us in members:
        if us.cf_norm is not None:            # only members with ratings can veto
            predicted = us.cf_pred.copy()
            for i, rating in us.rated.items():   # a real rating beats a prediction
                predicted[i] = rating
            misery |= predicted < 2.5
    mask = mask & ~misery
    if not mask.any():
        return None

    final = group + 10.0 * STRICT_BOOST * strict if relaxed else group
    pool = _top_candidates(final, mask, CANDIDATE_POOL)
    lam = min(us.mmr_lambda for _, us in members)
    chosen = _pick(state, pool, final, strict, relaxed, limit, lam)

    # display score: squash the group z-score into 0..1
    items = []
    for i in chosen:
        member_scores = {}
        for name, us in members:
            predicted = us.rated.get(i, float(us.cf_pred[i]))
            member_scores[name] = round(float(predicted), 1)
        low = min(member_scores.values())
        reason = "Everyone should enjoy this" if low >= 3.5 else "A good compromise for the group"
        display = 1.0 / (1.0 + math.exp(-float(group[i])))
        items.append((i, display, reason, member_scores))
    label = _relaxed_label("Watch party picks", relaxed)
    return RecResult(items, label, False, prep.ctx, relaxed)
