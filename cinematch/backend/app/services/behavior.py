"""
Behaviour profile: what a user's VIEWING tells us (Module 3), on top of ratings.

From playback_sessions + events we learn:
  * per-genre engagement   finishing films of a genre (and rewatching them) = up,
                           dropping off early = down
  * seek_forward_rate      "skippy" users (lots of fast-forwarding) get faster genres
                           (Action/Thriller) boosted and slow-burners damped
  * typical drop-off min   if they often stop ~X minutes in, prefer shorter runtimes
  * binge score            >= 3 sessions of series / the same franchise within 24 h
                           -> boost series and franchises
  * browse-to-select time  long browsing = undecided -> show a more diverse list
  * pseudo-ratings         completed (>= 90 %) -> 4.0, rewatch -> 4.5, early drop-off
                           -> 2.0. They feed the CF fold-in with a lower weight.
"""
from dataclasses import dataclass, field
from datetime import timedelta

import numpy as np

from app.database import as_utc
from app.vocab import GENRES, MOOD_TAGS

EARLY_DROP_RATIO = 0.25      # stopped in the first quarter
COMPLETE_RATIO = 0.90
FAST_GENRES = ["Action", "Thriller", "Adventure"]


@dataclass
class BehaviorProfile:
    sessions_count: int = 0
    completion_rate: float | None = None
    genre_engagement: dict = field(default_factory=dict)   # genre -> -1..1
    seek_forward_rate: float = 0.0                          # fast-forwards per session
    typical_drop_off_min: float | None = None
    binge_score: float = 0.0                                # 0..1
    avg_browse_to_select_ms: float | None = None
    rewatch_count: int = 0
    pseudo_ratings: dict = field(default_factory=dict)      # movie_id -> 2.0 / 4.0 / 4.5
    finished_movie_ids: set = field(default_factory=set)

    @property
    def has_data(self) -> bool:
        return self.sessions_count > 0


def completion_ratio(session) -> float | None:
    """How much of the title was watched in a session (None if still playing)."""
    if session.completed:
        return 1.0
    if session.drop_off_sec is None:
        return None
    if session.duration_sec and session.duration_sec > 0:
        return float(min(1.0, max(0.0, session.drop_off_sec / session.duration_sec)))
    return None


def build_profile(sessions: list, events: list, state=None) -> BehaviorProfile:
    """sessions: PlaybackSession rows, events: Event rows (select / binge_next)."""
    profile = BehaviorProfile()
    profile.sessions_count = len(sessions)

    # browse-to-select time comes from "select" events (value = milliseconds)
    selects = [e.value for e in events if e.type == "select" and e.value is not None and e.value >= 0]
    if selects:
        profile.avg_browse_to_select_ms = float(np.mean(selects))
    binge_next = sum(1 for e in events if e.type == "binge_next")

    if not sessions:
        profile.binge_score = min(1.0, 0.1 * binge_next)
        return profile

    ratios, drop_minutes = [], []
    genre_sum = np.zeros(len(GENRES), dtype=np.float64)
    genre_cnt = np.zeros(len(GENRES), dtype=np.float64)
    seek_forward = 0
    strongest: dict[int, float] = {}   # movie_id -> pseudo rating

    for s in sessions:
        seek_forward += s.seek_forward_count or 0
        if s.is_rewatch:
            profile.rewatch_count += 1
            strongest[s.movie_id] = 4.5
        ratio = completion_ratio(s)
        if ratio is None:
            continue
        ratios.append(ratio)
        early = (not s.completed) and ratio < EARLY_DROP_RATIO
        if ratio >= COMPLETE_RATIO:
            profile.finished_movie_ids.add(s.movie_id)
            if strongest.get(s.movie_id, 0) < 4.0:
                strongest[s.movie_id] = 4.0
        elif early and s.movie_id not in strongest:
            strongest[s.movie_id] = 2.0
        if not s.completed and ratio < COMPLETE_RATIO and s.drop_off_sec:
            drop_minutes.append(s.drop_off_sec / 60.0)

        # engagement for this session: how far they got, + rewatch, - early quit
        engagement = ratio + (0.3 if s.is_rewatch else 0.0) - (0.3 if early else 0.0)
        if state is not None:
            i = state.idx(s.movie_id)
            if i is not None:
                row = state.genre_matrix[i]
                genre_sum[row] += engagement
                genre_cnt[row] += 1

    profile.pseudo_ratings = strongest
    profile.seek_forward_rate = seek_forward / max(1, len(sessions))
    if ratios:
        profile.completion_rate = float(np.mean(ratios))
    if len(drop_minutes) >= 3:
        profile.typical_drop_off_min = float(np.median(drop_minutes))
    for j, genre in enumerate(GENRES):
        if genre_cnt[j] > 0:
            # mean engagement 0..1.3 -> -1..1, shrunk a bit towards 0 for few sessions
            mean = genre_sum[j] / genre_cnt[j]
            shrink = genre_cnt[j] / (genre_cnt[j] + 1.0)
            profile.genre_engagement[genre] = float(np.clip((mean - 0.5) * 2.0, -1, 1) * shrink)

    profile.binge_score = min(1.0, _binge_windows(sessions, state) / 3.0 + 0.1 * binge_next)
    return profile


def _binge_windows(sessions: list, state) -> int:
    """Count sessions that had >= 2 other sessions of series / the same franchise
    in the 24 hours before them (i.e. 3 in a row = a binge)."""
    if state is None:
        return 0
    marked = []
    for s in sessions:
        i = state.idx(s.movie_id)
        if i is None:
            continue
        group = "series" if state.is_series[i] else (
            f"coll:{state.coll_idx[i]}" if state.coll_idx[i] >= 0 else None)
        if group:
            marked.append((as_utc(s.started_at), group))
    marked.sort(key=lambda x: x[0])
    windows = 0
    for k, (when, group) in enumerate(marked):
        recent = [g for t, g in marked[:k] if when - t <= timedelta(hours=24) and g == group]
        if len(recent) >= 2:
            windows += 1
    return windows


def behavior_vector(state, profile: BehaviorProfile) -> np.ndarray | None:
    """Behaviour component (0..1, 0.5 = neutral) for every item, or None if we
    know nothing about this user's viewing."""
    if not profile.has_data and profile.binge_score <= 0:
        return None
    score = np.full(state.n, 0.5, dtype=np.float32)

    if profile.genre_engagement:
        # mean engagement over each item's genres (looping over the genres the
        # user actually watched keeps memory small)
        total = np.zeros(state.n, dtype=np.float32)
        for genre, value in profile.genre_engagement.items():
            total += value * state.genre_matrix[:, GENRES.index(genre)]
        score += 0.35 * total / np.maximum(state.genre_count, 1.0)

    if profile.seek_forward_rate > 1.5:   # skippy viewer
        fast = state.genre_matrix[:, [GENRES.index(g) for g in FAST_GENRES]].any(axis=1)
        slow = state.mood_matrix[:, MOOD_TAGS.index("slow-burn")]
        score += 0.10 * fast - 0.15 * slow

    if profile.typical_drop_off_min:
        limit = profile.typical_drop_off_min
        runtime = state.runtime
        known = ~np.isnan(runtime)
        score -= 0.15 * (known & (runtime > 1.2 * limit))
        score += 0.05 * (known & (runtime <= limit))

    if profile.binge_score > 0:
        score += 0.20 * profile.binge_score * state.is_series
        score += 0.10 * profile.binge_score * state.in_collection

    return np.clip(score, 0.0, 1.0).astype(np.float32)


def best_genre_for(state, profile: BehaviorProfile, i: int) -> str | None:
    """The item's genre this user engages with most (for the reason text)."""
    best, best_value = None, 0.2
    for j, genre in enumerate(GENRES):
        if state.genre_matrix[i, j] and profile.genre_engagement.get(genre, -1) > best_value:
            best, best_value = genre, profile.genre_engagement[genre]
    return best
