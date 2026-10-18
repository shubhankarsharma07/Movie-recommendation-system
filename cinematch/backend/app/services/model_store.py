"""
Model store: loads the ML artifacts (CONTRACT section 2) into memory.

    artifacts/
      current.txt        -> e.g. "v20261002_103000"
      v20261002_103000/  -> catalog.csv, item_factors.npy, item_bias.npy, has_cf.npy,
                            plot_emb.npy, has_emb.npy, model_meta.json

Rules:
  * Every array is aligned to the ROW ORDER of catalog.csv (row i == index i).
  * Hot reload: at most every 30 s we look at current.txt. If it changed, the new
    version is loaded in a background thread while the old one keeps serving.
  * NFR-4: if loading the new version fails, we keep serving the old one.
  * If nothing can be loaded, `model_loaded` is False and the API falls back to a
    popularity list ("Trending now"). If only the .npy files are broken but
    catalog.csv is fine, we still load the catalog so browsing works.

Memory (Render free = 512 MB): after loading there is no pandas DataFrame,
only numpy arrays and compact columns (TextColumn / CodedColumn / PeopleIndex
below). The plot embeddings stay float16 when they are big and are converted
chunk by chunk during dot products. 65,000 titles use ~180 MB.
"""
import ctypes
import gc
import json
import logging
import math
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd

from app.config import settings
from app.services.rules import ALL_RULE_KEYWORDS
from app.vocab import AGE_RATINGS, ARCS, EMOTIONS, GENRES, MOOD_TAGS

log = logging.getLogger("cinematch.model")

DEFAULT_BLEND_WEIGHTS = {
    "cf": 0.45, "content": 0.15, "ref": 0.35, "ctx": 0.25,
    "quality": 0.12, "trend": 0.05, "behavior": 0.10,
}
TMDB_POSTER = "https://image.tmdb.org/t/p/w342"
TMDB_BACKDROP = "https://image.tmdb.org/t/p/w1280"
RELOAD_CHECK_SECONDS = 30
EMB_FLOAT32_LIMIT_BYTES = 64 * 1024 * 1024   # keep float16 above this (saves RAM)
EMB_CHUNK_ROWS = 4096           # 4096 x 384 x 4 bytes = 6 MB temporary per chunk

CATALOG_COLUMNS = [
    "movie_id", "content_type", "tmdb_id", "imdb_id", "title", "year", "genres", "overview",
    "poster_path", "backdrop_path", "runtime", "seasons", "original_language", "age_rating",
    "certification_raw", "directors", "cast", "keywords", "collection_name", "ml_rating_mean",
    "ml_rating_count", "tmdb_popularity", "tmdb_vote_avg", "tmdb_vote_count", "imdb_rating",
    "imdb_votes", "critic_score", "popularity_score", "trending_velocity", "quality_score",
    "start_emotion", "end_emotion", "emotion_arc", "mood_tags", "decade", "trailer_key",
]
REQUIRED_COLUMNS = ["movie_id", "title"]


class ArtifactError(Exception):
    """Raised when an artifact version is missing files or has bad data."""


def _split(value: str) -> list[str]:
    """'a|b|c' -> ['a', 'b', 'c'] (empty string -> [])."""
    if not value:
        return []
    return [part.strip() for part in value.split("|") if part.strip()]


def _num_or_none(value, as_int: bool = False, digits: int = 4):
    """numpy number -> plain Python number (JSON safe), NaN -> None.
    Rounded, so float32 noise like 74.80000305 shows as 74.8."""
    if value is None:
        return None
    value = float(value)
    if math.isnan(value) or math.isinf(value):
        return None
    return int(round(value)) if as_int else round(value, digits)


def _multi_hot(values: list[str], vocab: list[str], lower: bool = False) -> np.ndarray:
    """Pipe lists -> bool matrix [N, len(vocab)]."""
    position = {(v.lower() if lower else v): j for j, v in enumerate(vocab)}
    matrix = np.zeros((len(values), len(vocab)), dtype=bool)
    for i, text in enumerate(values):
        if not text:
            continue
        for part in text.split("|"):
            part = part.strip()
            j = position.get(part.lower() if lower else part)
            if j is not None:
                matrix[i, j] = True
    return matrix


class PeopleIndex:
    """Directors (or actors) -> the catalog rows they appear in.

    Stored compactly because a real catalog has ~150,000 different cast names:
      ids       lower-case name -> person number
      display   person number -> name as written ("Bong Joon-ho")
      postings  all row numbers, person after person (one numpy array)
      offsets   person p's rows are postings[offsets[p]:offsets[p + 1]]
      ranked    person numbers, most popular first (sum of their titles' popularity)
    """

    def __init__(self, values: list[str], popularity: np.ndarray):
        self.ids: dict[str, int] = {}
        self.display: list[str] = []
        rows_of: list[list[int]] = []
        pop: list[float] = []
        for i, text in enumerate(values):
            if not text:
                continue
            for name in text.split("|"):
                name = name.strip()
                if not name:
                    continue
                key = name.lower()
                person = self.ids.get(key)
                if person is None:
                    person = len(self.display)
                    self.ids[key] = person
                    self.display.append(name)
                    rows_of.append([])
                    pop.append(0.0)
                rows_of[person].append(i)
                pop[person] += float(popularity[i])
        lengths = np.array([len(r) for r in rows_of], dtype=np.int64)
        self.offsets = np.zeros(len(rows_of) + 1, dtype=np.int64)
        np.cumsum(lengths, out=self.offsets[1:])
        self.postings = np.fromiter((i for rows in rows_of for i in rows), dtype=np.int32,
                                    count=int(lengths.sum()))
        self.ranked = np.argsort(-np.array(pop, dtype=np.float64), kind="stable").astype(np.int32)

    def rows(self, name: str) -> np.ndarray | None:
        """Catalog rows for a name (case-insensitive), or None if unknown."""
        person = self.ids.get(name.strip().lower())
        if person is None:
            return None
        return self.postings[self.offsets[person]:self.offsets[person + 1]]

    def top(self, limit: int) -> list[str]:
        return [self.display[p] for p in self.ranked[:limit]]

    def search(self, query: str, limit: int) -> list[str]:
        """Word-prefix matches first, then 'contains'; most popular first."""
        query = query.strip().lower()
        if not query:
            return self.top(limit)
        prefix, contains = [], []
        for person in self.ranked:
            name = self.display[person]
            key = name.lower()
            if query not in key:
                continue
            if key.startswith(query) or (" " + query) in key:
                prefix.append(name)
                if len(prefix) >= limit:
                    break
            elif len(contains) < limit:
                contains.append(name)
        return (prefix + contains)[:limit]


class ModelState:
    """Everything loaded from ONE artifact version. Read-only after loading, so
    all requests can share it without locks."""

    def __init__(self, version: str, folder: Path):
        self.version = version
        self.folder = folder
        self.meta: dict = {}
        self.has_model = False      # False = catalog only (popularity fallback)
        self.n = 0

    # ------------------------------------------------------------------ helpers
    @property
    def dataset_mode(self) -> str | None:
        return self.meta.get("dataset_mode")

    def idx(self, movie_id: int) -> int | None:
        return self.idx_of.get(int(movie_id))

    def emb_dot(self, vectors: np.ndarray) -> np.ndarray:
        """plot_emb @ vectors for ALL items (vectors: float32 [d] or [d, m]).
        float16 embeddings are converted in chunks so we never hold a full
        float32 copy in memory."""
        vectors = np.asarray(vectors, dtype=np.float32)
        if self.emb is None:
            return np.zeros((self.n,) + vectors.shape[1:], dtype=np.float32)
        if self.emb.dtype == np.float32:
            return self.emb @ vectors
        out = np.empty((self.n,) + vectors.shape[1:], dtype=np.float32)
        for start in range(0, self.n, EMB_CHUNK_ROWS):
            stop = start + EMB_CHUNK_ROWS
            out[start:stop] = self.emb[start:stop].astype(np.float32) @ vectors
        return out

    def emb_rows(self, rows) -> np.ndarray:
        """float32 copy of a few embedding rows."""
        if self.emb is None:
            return np.zeros((len(rows), 1), dtype=np.float32)
        return self.emb[np.asarray(rows)].astype(np.float32)

    def poster_url(self, i: int) -> str | None:
        path = self.poster_path[i]
        return TMDB_POSTER + path if path else None

    def backdrop_url(self, i: int) -> str | None:
        path = self.backdrop_path[i]
        return TMDB_BACKDROP + path if path else None

    def merged_rating(self, i: int, stats: dict | None) -> tuple[float | None, int]:
        """avg_rating / rating_count = MovieLens stats merged with in-app ratings.
        Series have no MovieLens data; if nobody rated them in the app yet we
        show the TMDB vote average (converted from /10 to /5) so cards are not blank."""
        movie_id = int(self.movie_ids[i])
        app_sum, app_count = (stats or {}).get(movie_id, (0.0, 0))
        ml_mean = float(self.ml_mean[i])
        ml_count = int(self.ml_count[i])
        if ml_count > 0 and not math.isnan(ml_mean):
            total, count = ml_mean * ml_count + app_sum, ml_count + app_count
        elif app_count > 0:
            total, count = app_sum, app_count
        else:
            tmdb_avg = float(self.tmdb_vote_avg[i])
            tmdb_count = float(self.tmdb_vote_count[i])
            if not math.isnan(tmdb_avg) and not math.isnan(tmdb_count) and tmdb_count > 0:
                return round(tmdb_avg / 2.0, 2), int(tmdb_count)
            return None, 0
        return round(total / count, 2), int(count)

    def card(self, i: int, stats: dict | None = None) -> dict:
        """CONTRACT 5.2 MovieCard for catalog row i."""
        avg, count = self.merged_rating(i, stats)
        return {
            "movie_id": int(self.movie_ids[i]),
            "title": self.title[i],
            "year": _num_or_none(self.year[i], as_int=True),
            "content_type": self.content_type[i],
            "genres": _split(self.genres_text[i]),
            "poster_url": self.poster_url(i),
            "backdrop_url": self.backdrop_url(i),
            "avg_rating": avg,
            "rating_count": count,
            "runtime": _num_or_none(self.runtime[i], as_int=True),
            "age_rating": self.age_rating[i] or None,
            "language": self.language[i] or None,
            "critic_score": _num_or_none(self.critic_score[i]),
            "mood_tags": _split(self.mood_text[i]),
            "start_emotion": self.start_emotion[i] or None,
            "end_emotion": self.end_emotion[i] or None,
            "overview": self.overview[i],
            "trailer_key": self.trailer_key[i] or None,
            "collection_name": self.collection_name[i] or None,
        }

    def details(self, i: int) -> dict:
        """Extra fields for GET /api/movies/{id} (on top of the card)."""
        return {
            "directors": _split(self.directors_text[i]),
            "cast": _split(self.cast_text[i]),
            "keywords": _split(self.keywords_text[i]),
            "emotion_arc": self.emotion_arc[i] or None,
            "decade": _num_or_none(self.decade[i], as_int=True),
            "quality_score": _num_or_none(self.quality[i]),
            "popularity_score": _num_or_none(self.popularity[i]),
            "trending_velocity": _num_or_none(self.velocity[i]),
            "imdb_rating": _num_or_none(self.imdb_rating[i]),
            "seasons": _num_or_none(self.seasons[i], as_int=True),
            "certification_raw": self.certification_raw[i] or None,
        }

    def people_matching(self, role: str, query: str, limit: int) -> list[str]:
        """Director/actor name search for the Mood Mixer autocomplete."""
        index = self.directors if role == "director" else self.actors
        return index.search(query, limit)


def card_from_movie_row(movie, stats: dict | None = None) -> dict:
    """MovieCard built from a `movies` table row. Only used when no catalog is
    in memory (fallback), so some fields are simply unknown (null / [])."""
    app_sum, app_count = (stats or {}).get(movie.movie_id, (0.0, 0))
    avg, count = None, 0
    if movie.ml_rating_count and movie.ml_rating_mean is not None:
        count = movie.ml_rating_count + app_count
        avg = round((movie.ml_rating_mean * movie.ml_rating_count + app_sum) / count, 2)
    elif app_count:
        avg, count = round(app_sum / app_count, 2), app_count
    return {
        "movie_id": movie.movie_id,
        "title": movie.title,
        "year": movie.year,
        "content_type": movie.content_type or "movie",
        "genres": _split(movie.genres or ""),
        "poster_url": TMDB_POSTER + movie.poster_path if movie.poster_path else None,
        "backdrop_url": TMDB_BACKDROP + movie.backdrop_path if movie.backdrop_path else None,
        "avg_rating": avg,
        "rating_count": count,
        "runtime": movie.runtime,
        "age_rating": movie.age_rating or None,
        "language": movie.original_language or None,
        "critic_score": None,
        "mood_tags": [],
        "start_emotion": None,
        "end_emotion": None,
        "overview": "",
        "trailer_key": None,
        "collection_name": None,
    }


# ---------------------------------------------------------------------------- loading
def _read_catalog(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise ArtifactError(f"missing {path.name}")
    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False, encoding="utf-8")
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ArtifactError(f"catalog.csv is missing columns: {missing}")
    for col in CATALOG_COLUMNS:          # tolerate optional columns being absent
        if col not in df.columns:
            df[col] = ""
    return df


class TextColumn:
    """A column of strings stored as ONE utf-8 blob + an offsets array.
    65,000 separate Python str objects cost ~50 bytes of overhead each; this
    keeps only the characters. Works like a list: column[i] -> str."""

    def __init__(self, values: list[str]):
        encoded = [v.encode("utf-8") for v in values]
        self.offsets = np.zeros(len(encoded) + 1, dtype=np.int64)
        np.cumsum([len(b) for b in encoded], out=self.offsets[1:])
        self.blob = b"".join(encoded)

    def __getitem__(self, i) -> str:
        i = int(i)
        return self.blob[self.offsets[i]:self.offsets[i + 1]].decode("utf-8")

    def __len__(self) -> int:
        return len(self.offsets) - 1

    def __iter__(self):
        for i in range(len(self)):
            yield self[i]


class CodedColumn:
    """A column with few distinct values (language, age rating, emotion ...):
    one small integer code per row + the list of distinct values.
    column[i] -> str ("" when empty); column.codes is used for fast filters."""

    def __init__(self, values: list[str]):
        series = pd.Series([v if v else None for v in values], dtype=object)
        codes, uniques = pd.factorize(series)          # empty -> code -1
        self.codes = codes.astype(np.int32)
        self.values = [str(u) for u in uniques]

    def __getitem__(self, i) -> str:
        code = self.codes[int(i)]
        return self.values[code] if code >= 0 else ""

    def __len__(self) -> int:
        return len(self.codes)

    def __iter__(self):
        for i in range(len(self)):
            yield self[i]


def _vocab_index(column: CodedColumn, vocab: list[str]) -> np.ndarray:
    """CodedColumn -> index into a fixed vocabulary (-1 = unknown value)."""
    lookup = np.array([vocab.index(v) if v in vocab else -1 for v in column.values] + [-1], dtype=np.int8)
    return lookup[column.codes]          # code -1 picks the last entry (-1)


def _fill_catalog(state: ModelState, df: pd.DataFrame) -> None:
    """Turn the catalog DataFrame into compact arrays. Each CSV column is
    removed from the DataFrame as soon as it is converted, to keep the peak
    memory low while loading."""
    n = len(df)
    state.n = n

    def text(col):
        return [s.strip() for s in df.pop(col).astype(str).tolist()]

    def number(col, dtype=np.float32):
        return pd.to_numeric(df.pop(col), errors="coerce").to_numpy(dtype=dtype)

    ids = pd.to_numeric(df.pop("movie_id"), errors="coerce")
    if ids.isna().any():
        raise ArtifactError("catalog.csv has rows with an invalid movie_id")
    state.movie_ids = ids.to_numpy(dtype=np.int64)
    state.idx_of = {int(m): i for i, m in enumerate(state.movie_ids)}
    if len(state.idx_of) != n:
        raise ArtifactError("catalog.csv has duplicate movie_id values")

    # --- numbers (NaN = unknown)
    state.year = number("year")
    state.runtime = number("runtime")
    state.seasons = number("seasons")
    decade = number("decade")
    from_year = np.floor(state.year / 10.0) * 10.0
    state.decade = np.where(np.isnan(decade), from_year, decade).astype(np.float32)
    state.ml_mean = number("ml_rating_mean")
    state.ml_count = np.nan_to_num(number("ml_rating_count"), nan=0.0).astype(np.int64)
    state.tmdb_vote_avg = number("tmdb_vote_avg")
    state.tmdb_vote_count = number("tmdb_vote_count")
    state.imdb_rating = number("imdb_rating")
    state.critic_score = number("critic_score")
    state.popularity = np.nan_to_num(number("popularity_score"), nan=0.0)
    state.velocity = np.nan_to_num(number("trending_velocity"), nan=0.0)
    quality = number("quality_score")
    fill = float(np.nanmedian(quality)) if np.isfinite(quality).any() else 0.5
    state.quality = np.clip(np.where(np.isnan(quality), fill, quality), 0.0, 1.0).astype(np.float32)

    # trend in 0..1: half "is it rising right now" (velocity squashed with tanh,
    # 0 velocity -> 0.5) and half "is it popular overall".
    rising = 0.5 + 0.5 * np.tanh(2.0 * state.velocity)
    state.trend = (0.5 * rising + 0.5 * np.clip(state.popularity, 0, 1)).astype(np.float32)

    # --- titles stay plain lists (searched on every keystroke)
    state.title = text("title")
    state.title_lower = [t.lower() for t in state.title]

    # --- few distinct values -> integer codes (fast vectorised filters)
    state.content_type = CodedColumn(["series" if s.lower() == "series" else "movie" for s in text("content_type")])
    state.is_series = state.content_type.codes == (state.content_type.values.index("series")
                                                   if "series" in state.content_type.values else -2)
    state.language = CodedColumn([s.lower() for s in text("original_language")])
    state.lang_idx = state.language.codes
    state.lang_codes = state.language.values
    state.age_rating = CodedColumn(text("age_rating"))
    state.age_idx = _vocab_index(state.age_rating, AGE_RATINGS)
    state.start_emotion = CodedColumn([s.lower() for s in text("start_emotion")])
    state.end_emotion = CodedColumn([s.lower() for s in text("end_emotion")])
    state.start_emo_idx = _vocab_index(state.start_emotion, EMOTIONS)
    state.end_emo_idx = _vocab_index(state.end_emotion, EMOTIONS)
    state.emotion_arc = CodedColumn([s.lower() for s in text("emotion_arc")])
    state.arc_idx = _vocab_index(state.emotion_arc, ARCS)
    state.collection_name = CodedColumn(text("collection_name"))
    state.coll_idx = state.collection_name.codes
    state.coll_names = state.collection_name.values
    state.in_collection = state.coll_idx >= 0

    # --- genres / mood tags: multi-hot matrices + compact text for the cards
    genres = text("genres")
    state.genre_matrix = _multi_hot(genres, GENRES)
    state.genre_count = state.genre_matrix.sum(axis=1).astype(np.float32)
    state.genres_text = TextColumn(genres)
    moods = text("mood_tags")
    state.mood_matrix = _multi_hot(moods, MOOD_TAGS, lower=True)
    state.mood_text = TextColumn(moods)
    del genres, moods

    # --- people indexes (filters "directors"/"actors", name search, top lists)
    pop = np.clip(state.popularity, 0, None) + 1e-3
    directors = text("directors")
    state.directors = PeopleIndex(directors, pop)
    state.directors_text = TextColumn(directors)
    cast = text("cast")
    state.actors = PeopleIndex(cast, pop)
    state.cast_text = TextColumn(cast)
    del directors, cast

    # keywords: we only index the ones that our context rules boost
    keywords = text("keywords")
    wanted = {k.lower() for k in ALL_RULE_KEYWORDS}
    keyword_index: dict[str, list[int]] = {}
    for i, text_value in enumerate(keywords):
        if not text_value:
            continue
        for kw in text_value.split("|"):
            kw = kw.strip().lower()
            if kw in wanted:
                keyword_index.setdefault(kw, []).append(i)
    state.keyword_index = {k: np.array(v, dtype=np.int64) for k, v in keyword_index.items()}
    state.keywords_text = TextColumn(keywords)
    del keywords

    # --- other per-item text, only read when a card/details page is built
    for col, attr in [("overview", "overview"), ("poster_path", "poster_path"),
                      ("backdrop_path", "backdrop_path"), ("certification_raw", "certification_raw"),
                      ("trailer_key", "trailer_key"), ("imdb_id", "imdb_id")]:
        setattr(state, attr, TextColumn(text(col)))

    # franchises ranked by total popularity
    if state.coll_names:
        coll_pop = np.bincount(state.coll_idx[state.in_collection],
                               weights=pop[state.in_collection], minlength=len(state.coll_names))
        order = np.argsort(-coll_pop)
        state.franchises_ranked = [state.coll_names[j] for j in order]
    else:
        state.franchises_ranked = []

    # pre-sorted orders for the catalog browser
    state.order_popular = np.argsort(-state.popularity, kind="stable")
    state.order_title = np.array(sorted(range(n), key=lambda i: state.title_lower[i]), dtype=np.int64)


def _load_npy(folder: Path, name: str) -> np.ndarray:
    path = folder / name
    if not path.is_file():
        raise ArtifactError(f"missing {name}")
    try:
        return np.load(path, allow_pickle=False)
    except Exception as exc:  # truncated / corrupt file
        raise ArtifactError(f"cannot read {name}: {exc}") from exc


def _load_arrays(state: ModelState, folder: Path) -> None:
    n = state.n

    Q = _load_npy(folder, "item_factors.npy").astype(np.float32, copy=False)
    if Q.ndim != 2 or Q.shape[0] != n:
        raise ArtifactError(f"item_factors.npy has shape {Q.shape}, expected ({n}, k)")
    if not np.isfinite(Q).all():
        raise ArtifactError("item_factors.npy contains NaN/inf")

    bias = _load_npy(folder, "item_bias.npy").astype(np.float32, copy=False).reshape(-1)
    if bias.shape[0] != n or not np.isfinite(bias).all():
        raise ArtifactError("item_bias.npy has the wrong length or NaN values")

    if (folder / "has_cf.npy").is_file():
        has_cf = _load_npy(folder, "has_cf.npy").astype(bool).reshape(-1)
    else:
        has_cf = np.abs(Q).sum(axis=1) > 0
    if has_cf.shape[0] != n:
        raise ArtifactError("has_cf.npy has the wrong length")

    emb = None
    has_emb = np.zeros(n, dtype=bool)
    if (folder / "plot_emb.npy").is_file():
        emb = _load_npy(folder, "plot_emb.npy")
        if emb.ndim != 2 or emb.shape[0] != n:
            raise ArtifactError(f"plot_emb.npy has shape {emb.shape}, expected ({n}, d)")
        emb = emb.astype(np.float16, copy=False) if emb.dtype != np.float32 else emb
        # re-normalise defensively (cosine = dot product only for unit vectors)
        norms = np.empty(n, dtype=np.float32)
        for start in range(0, n, EMB_CHUNK_ROWS):
            chunk = emb[start:start + EMB_CHUNK_ROWS].astype(np.float32)
            if not np.isfinite(chunk).all():
                raise ArtifactError("plot_emb.npy contains NaN/inf")
            norms[start:start + EMB_CHUNK_ROWS] = np.linalg.norm(chunk, axis=1)
        if (folder / "has_emb.npy").is_file():
            has_emb = _load_npy(folder, "has_emb.npy").astype(bool).reshape(-1)
            if has_emb.shape[0] != n:
                raise ArtifactError("has_emb.npy has the wrong length")
        else:
            has_emb = norms > 0
        has_emb = has_emb & (norms > 0)
        safe = np.where(norms > 0, norms, 1.0).astype(np.float32)
        if np.abs(safe[has_emb] - 1.0).max(initial=0.0) > 1e-2:
            emb = (emb.astype(np.float32) / safe[:, None]).astype(emb.dtype)
        if emb.dtype != np.float32 and emb.size * 4 <= EMB_FLOAT32_LIMIT_BYTES:
            emb = emb.astype(np.float32)   # small enough: float32 is much faster
    else:
        log.warning("plot_emb.npy not found in %s - content similarity disabled", folder.name)

    state.Q = Q
    state.q_norm = np.linalg.norm(Q, axis=1).astype(np.float32)
    state.item_bias = bias
    state.has_cf = has_cf & (state.q_norm > 0)
    state.emb = emb
    state.has_emb = has_emb
    state.has_model = True


def _apply_meta(state: ModelState) -> None:
    meta = state.meta
    if "global_mean" in meta:
        state.global_mean = float(meta["global_mean"])
    else:  # sensible default: mean MovieLens rating of the catalog
        ok = (state.ml_count > 0) & ~np.isnan(state.ml_mean)
        state.global_mean = float(np.average(state.ml_mean[ok], weights=state.ml_count[ok])) if ok.any() else 3.5
    state.fold_in_reg = float(meta.get("fold_in_reg", 0.1) or 0.1)
    weights = dict(DEFAULT_BLEND_WEIGHTS)
    for key, value in (meta.get("blend_weights") or {}).items():
        if key in weights:
            try:
                weights[key] = max(0.0, float(value))
            except (TypeError, ValueError):
                pass
    state.blend_weights = weights


def _release_memory() -> None:
    """Give the temporary memory used while parsing the CSV back to the OS
    (matters on a 512 MB server). malloc_trim only exists on Linux/glibc."""
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


def load_state(artifacts_dir: Path, version: str, catalog_only: bool = False) -> ModelState:
    """Load one artifact version. Raises ArtifactError (or any exception) on bad data."""
    if not version or "/" in version or "\\" in version or version.startswith("."):
        raise ArtifactError(f"invalid version name {version!r}")
    folder = artifacts_dir / version
    if not folder.is_dir():
        raise ArtifactError(f"artifact folder {folder} does not exist")
    started = time.perf_counter()
    state = ModelState(version, folder)
    meta_path = folder / "model_meta.json"
    if meta_path.is_file():
        try:
            state.meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ArtifactError(f"model_meta.json is not valid JSON: {exc}") from exc
        if not isinstance(state.meta, dict):
            raise ArtifactError("model_meta.json must contain a JSON object")
    _fill_catalog(state, _read_catalog(folder / "catalog.csv"))
    _apply_meta(state)
    if not catalog_only:
        _load_arrays(state, folder)
    _release_memory()
    log.info("loaded artifacts %s (%d items, model=%s) in %.1fs",
             version, state.n, state.has_model, time.perf_counter() - started)
    return state


# ---------------------------------------------------------------------------- the store
class ModelStore:
    def __init__(self, artifacts_dir: Path):
        self.artifacts_dir = Path(artifacts_dir)
        self.state: ModelState | None = None
        self.last_error: str | None = None
        self.check_interval = RELOAD_CHECK_SECONDS
        self._lock = threading.Lock()
        self._last_check = 0.0
        self._seen_marker = None
        self._listeners = []

    @property
    def model_loaded(self) -> bool:
        return self.state is not None and self.state.has_model

    def add_listener(self, fn) -> None:
        """fn(state) is called after a new version is loaded (used to sync the movies table)."""
        if fn not in self._listeners:
            self._listeners.append(fn)

    def configure(self, artifacts_dir: Path) -> None:
        self.artifacts_dir = Path(artifacts_dir)
        self._seen_marker = None

    def current_txt(self) -> Path:
        return self.artifacts_dir / "current.txt"

    def read_current_version(self) -> str | None:
        try:
            text = self.current_txt().read_text(encoding="utf-8").strip()
            return text or None
        except OSError:
            return None

    def _marker(self):
        try:
            st = self.current_txt().stat()
            return (st.st_mtime_ns, st.st_size, self.read_current_version())
        except OSError:
            return None

    def reload(self, force: bool = False) -> bool:
        """Load the version named in current.txt (blocking). Returns True if a
        full model is being served afterwards."""
        with self._lock:
            self._seen_marker = self._marker()
            version = self.read_current_version()
            if not version:
                self.last_error = f"no current.txt in {self.artifacts_dir}"
                log.warning(self.last_error)
                return self.model_loaded
            if not force and self.state is not None and self.state.version == version and self.state.has_model:
                return True
            try:
                new_state = load_state(self.artifacts_dir, version)
            except Exception as exc:
                self.last_error = f"failed to load {version}: {exc}"
                if self.state is not None:
                    # NFR-4: keep serving the last good version
                    log.error("%s - keeping version %s", self.last_error, self.state.version)
                    return self.model_loaded
                log.error("%s - trying catalog only", self.last_error)
                try:
                    new_state = load_state(self.artifacts_dir, version, catalog_only=True)
                except Exception as exc2:
                    log.error("catalog.csv of %s cannot be loaded either: %s", version, exc2)
                    return False
            else:
                self.last_error = None
            self.state = new_state
            for listener in self._listeners:
                try:
                    listener(new_state)
                except Exception:
                    log.exception("model listener failed")
            return new_state.has_model

    def maybe_reload(self) -> None:
        """Cheap check called on every request: at most every 30 s, look at
        current.txt and reload in a background thread if it changed."""
        now = time.monotonic()
        if now - self._last_check < self.check_interval:
            return
        self._last_check = now
        marker = self._marker()
        if marker is None or marker == self._seen_marker or self._lock.locked():
            return
        threading.Thread(target=self._reload_in_background, daemon=True).start()

    def _reload_in_background(self) -> None:
        try:
            self.reload()
        except Exception:
            log.exception("background model reload failed")


store = ModelStore(settings.artifacts_dir)
