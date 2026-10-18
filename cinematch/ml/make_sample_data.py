"""
make_sample_data.py - build the bundled DEMO dataset in ml/sample_data/

Why: the real pipeline needs MovieLens (from grouplens.org) and the TMDB API. The demo dataset
lets you (and your examiner) run the WHOLE pipeline with no internet and no API keys:

    python make_sample_data.py          # writes ml/sample_data/
    python run_all.py --sample          # steps 1-9 offline -> backend/artifacts/<version>/

What it writes (all in MovieLens format where possible, so step1 reads it like the real thing):
    movies.csv      movieId,title,genres                 ("Matrix, The (1999)" style titles)
    links.csv       movieId,imdbId,tmdbId
    ratings.csv     userId,movieId,rating,timestamp       (~50k synthetic ratings, 800 users)
    metadata.json   stands in for TMDB + IMDb (what steps 2 and 3 would normally download)
    snapshots/      two TMDB-style popularity snapshots (so trending velocity can be computed)
    README.txt      reminder that this is demo data

Titles and facts come from sample_titles.py (hand-written, real titles, ORIGINAL overviews).
Ratings are SYNTHETIC: every fake user has a hidden taste profile (favourite genres, languages,
eras + some random hidden factors), and ratings are generated from that profile plus noise.
Because there is real structure in the data, collaborative filtering can learn something.
Everything uses a fixed random seed, so running this twice gives identical files.
"""
from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import config
import sample_titles
from utils import banner, log

SEED = 42
N_USERS = 800
MIN_RATINGS_PER_MOVIE = 25            # comfortably above MIN_RATINGS (20) so every title survives step1
DEMO_ID_START = 900_001               # demo ids for titles we do not know the MovieLens id of
DEMO_SERIES_ID_START = config.SERIES_ID_OFFSET + 900_001   # series with unknown TMDB id
SPAN_START = datetime(2024, 10, 1, tzinfo=timezone.utc)    # ratings are spread over two years
SPAN_END = datetime(2026, 9, 30, tzinfo=timezone.utc)

LANG_GROUPS = {"en": 0, "hi": 1, "ta": 2, "te": 2, "ml": 2, "kn": 2, "bn": 2, "mr": 2,
               "ja": 3, "ko": 3, "zh": 3}          # everything else (fr, es, de, ...) -> group 4
ARTICLES = ("The ", "A ", "An ")


# ----------------------------------------------------------------------------------------------
# 1. Read the hand-written title list
# ----------------------------------------------------------------------------------------------
def _num(text: str, kind=float):
    text = text.strip()
    return kind(text) if text else None


def parse_titles():
    movies, series = [], []
    next_demo_id = DEMO_ID_START
    for line in sample_titles.ALL_MOVIES.strip().splitlines():
        if not line.strip():
            continue
        (ml_id, title, year, genres, directors, cast, runtime, lang, cert, keywords, collection,
         tmdb, imdb, imdb_rating, meta, pop, overview) = [part.strip() for part in line.split(";")]
        if ml_id:
            movie_id = int(ml_id)
        else:
            movie_id, next_demo_id = next_demo_id, next_demo_id + 1
        movies.append(dict(
            movie_id=movie_id, content_type="movie", title=title, year=int(year), genres=genres,
            directors=directors, cast=cast, runtime=int(runtime), seasons=None, original_language=lang,
            certifications=cert, keywords=keywords, collection_name=collection,
            tmdb_id=_num(tmdb, int), imdb_id=imdb, imdb_rating=float(imdb_rating),
            metascore=_num(meta, float), pop=int(pop), overview=overview,
        ))

    next_demo_series = DEMO_SERIES_ID_START
    for line in sample_titles.SERIES.strip().splitlines():
        if not line.strip():
            continue
        (tmdb, title, year, genres, creators, cast, runtime, seasons, lang, cert, keywords, imdb,
         imdb_rating, pop, overview) = [part.strip() for part in line.split(";")]
        if tmdb:
            movie_id = config.SERIES_ID_OFFSET + int(tmdb)       # CONTRACT rule for series ids
        else:
            movie_id, next_demo_series = next_demo_series, next_demo_series + 1
        series.append(dict(
            movie_id=movie_id, content_type="series", title=title, year=int(year), genres=genres,
            directors=creators, cast=cast, runtime=int(runtime), seasons=int(seasons),
            original_language=lang, certifications=cert, keywords=keywords, collection_name="",
            tmdb_id=_num(tmdb, int), imdb_id=imdb, imdb_rating=float(imdb_rating), metascore=None,
            pop=int(pop), overview=overview,
        ))

    ids = [m["movie_id"] for m in movies + series]
    assert len(ids) == len(set(ids)), "duplicate movie ids in sample_titles.py"
    return movies, series


# ----------------------------------------------------------------------------------------------
# 2. Fake "TMDB / IMDb" numbers (plausible, clearly marked as demo data)
# ----------------------------------------------------------------------------------------------
def add_fake_scores(items, rng):
    for item in items:
        pop = item["pop"]
        noise = float(rng.lognormal(0.0, 0.35))
        item["tmdb_popularity_prev"] = round(1.5 * math.exp(0.42 * pop) * noise, 3)
        # "trend": newer titles are more likely to be rising right now
        trend = 0.35 * (item["year"] >= 2022) + float(rng.normal(0.0, 0.25))
        item["trend"] = trend
        item["tmdb_popularity"] = round(item["tmdb_popularity_prev"] * math.exp(0.6 * trend), 3)
        item["tmdb_vote_count"] = int(10 ** (1.2 + 0.33 * pop) * rng.lognormal(0, 0.25))
        item["tmdb_vote_avg"] = round(float(np.clip(item["imdb_rating"] - 0.4 + rng.normal(0, 0.15), 1, 10)), 1)
        item["imdb_votes"] = int(item["tmdb_vote_count"] * rng.uniform(15, 40))
        if item["metascore"] is not None and rng.random() < 0.6:
            item["rt_score"] = float(np.clip(round(item["metascore"] + 8 + rng.normal(0, 7)), 0, 100))
        else:
            item["rt_score"] = None


# ----------------------------------------------------------------------------------------------
# 3. Synthetic users and ratings
# ----------------------------------------------------------------------------------------------
def item_features(movies):
    genre_index = {g: i for i, g in enumerate(config.GENRES)}
    n = len(movies)
    genres = np.zeros((n, len(config.GENRES)))
    lang = np.zeros(n, dtype=int)
    era = np.zeros(n, dtype=int)
    for i, m in enumerate(movies):
        for g in m["genres"].split("|"):
            if g in genre_index:
                genres[i, genre_index[g]] = 1.0
        genres[i] /= max(1.0, math.sqrt(genres[i].sum()))
        lang[i] = LANG_GROUPS.get(m["original_language"], 4)
        y = m["year"]
        era[i] = 0 if y < 1970 else 1 if y < 2000 else 2 if y < 2015 else 3
    quality = np.array([m["imdb_rating"] for m in movies])
    pop = np.array([m["pop"] for m in movies], dtype=float)
    trend = np.array([m["trend"] for m in movies])
    return genres, lang, era, quality, pop, trend


def make_users(rng, n_genres):
    # Four kinds of viewer, each with a different language/era taste (+ personal noise)
    segments = ["indian", "global", "anime_asia", "cinephile"]
    seg_prob = [0.40, 0.35, 0.12, 0.13]
    lang_base = {                     # en, hi, south/other Indian, east asian, european
        "indian":     [0.2, 1.0, 0.6, -0.4, -0.5],
        "global":     [1.0, -0.4, -0.5, 0.0, 0.0],
        "anime_asia": [0.3, -0.3, -0.3, 1.3, 0.1],
        "cinephile":  [0.5, 0.1, 0.2, 0.6, 1.0],
    }
    era_base = {
        "indian": [-0.3, 0.1, 0.3, 0.5], "global": [-0.5, 0.1, 0.3, 0.5],
        "anime_asia": [-0.3, 0.2, 0.3, 0.4], "cinephile": [0.8, 0.5, 0.1, 0.0],
    }
    users = []
    for _ in range(N_USERS):
        seg = segments[rng.choice(4, p=seg_prob)]
        genre_aff = rng.normal(0, 0.45, n_genres)
        genre_aff[rng.choice(n_genres, 3, replace=False)] += 1.2      # favourite genres
        genre_aff[rng.choice(n_genres, 2, replace=False)] -= 1.0      # genres they avoid
        lang_aff = np.array(lang_base[seg]) + rng.normal(0, 0.3, 5)
        if seg == "indian" and rng.random() < 0.45:                   # many love South Indian films
            lang_aff[2] += 0.8
        users.append(dict(
            segment=seg, genre_aff=genre_aff, lang_aff=lang_aff,
            era_aff=np.array(era_base[seg]) + rng.normal(0, 0.25, 4),
            bias=rng.normal(0, 0.35),                                  # generous vs harsh raters
            n=int(np.clip(rng.lognormal(math.log(45), 0.8), 12, 400)), # long-tail activity
        ))
    return users


def generate_ratings(movies, rng):
    genres, lang, era, quality, pop, trend = item_features(movies)
    n_items = len(movies)
    k = 8                                                  # hidden taste factors
    item_latent = rng.normal(0, 1, (n_items, k))
    users = make_users(rng, genres.shape[1])
    span = (SPAN_END - SPAN_START).total_seconds()

    rows = []                                              # (user_idx, item_idx, rating, ts)
    rated = [set() for _ in range(N_USERS)]

    def affinity(u, items):
        return (genres[items] @ u["genre_aff"] + u["lang_aff"][lang[items]] + u["era_aff"][era[items]])

    def rating_for(u, user_latent, items):
        r = (2.75 + 0.42 * (quality[items] - 7.4) + u["bias"] + 0.55 * affinity(u, items)
             + 0.35 * (item_latent[items] @ user_latent) / math.sqrt(k)
             + rng.normal(0, 0.5, len(items)))
        return np.clip(np.round(r * 2) / 2, 0.5, 5.0)     # half stars, 0.5 .. 5.0

    def timestamps(u_start, u_end, items):
        # items that are "trending" get rated later in the window, falling ones earlier
        a = 1 + np.clip(trend[items], 0, None) * 2.5
        b = 1 + np.clip(-trend[items], 0, None) * 2.5
        frac = rng.beta(a, b)
        return (u_start + frac * (u_end - u_start)).astype(np.int64)

    latents = rng.normal(0, 1, (N_USERS, k))
    windows = []
    for ui, u in enumerate(users):
        start = SPAN_START.timestamp() + rng.uniform(0, 0.85) * span
        end = min(SPAN_END.timestamp(), start + rng.uniform(0.15, 1.0) * span)
        windows.append((start, end))
        # Which titles does this user watch? People watch what they like AND what is popular.
        # Gumbel-top-k = a neat trick to sample n items without replacement from these weights.
        logits = 0.9 * affinity(u, np.arange(n_items)) + 0.45 * pop + rng.gumbel(0, 1, n_items)
        items = np.argsort(-logits)[: min(u["n"], n_items)]
        for item, r, ts in zip(items, rating_for(u, latents[ui], items), timestamps(start, end, items)):
            rows.append((ui, int(item), float(r), int(ts)))
            rated[ui].add(int(item))

    # Top up rarely-rated titles so every one survives the MIN_RATINGS filter of step1
    counts = np.bincount([r[1] for r in rows], minlength=n_items)
    for item in np.where(counts < MIN_RATINGS_PER_MOVIE)[0]:
        need = MIN_RATINGS_PER_MOVIE - counts[item]
        candidates = [ui for ui in range(N_USERS) if item not in rated[ui]]
        scores = np.array([affinity(users[ui], np.array([item]))[0] for ui in candidates])
        chosen = np.array(candidates)[np.argsort(-(scores + rng.gumbel(0, 1, len(scores))))[:need]]
        for ui in chosen:
            r = rating_for(users[ui], latents[ui], np.array([item]))[0]
            ts = timestamps(*windows[ui], np.array([item]))[0]
            rows.append((int(ui), int(item), float(r), int(ts)))
            rated[ui].add(int(item))
    return rows, users


# ----------------------------------------------------------------------------------------------
# 4. Write the files
# ----------------------------------------------------------------------------------------------
def movielens_title(title: str, year: int) -> str:
    """'The Matrix', 1999 -> 'Matrix, The (1999)' (how MovieLens writes titles)."""
    for art in ARTICLES:
        if title.startswith(art) and ":" not in title:
            title = f"{title[len(art):]}, {art.strip()}"
            break
    return f"{title} ({year})"


def write_files(movies, series, rows, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    (out / "snapshots").mkdir(exist_ok=True)

    with open(out / "movies.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["movieId", "title", "genres"])
        for m in movies:
            w.writerow([m["movie_id"], movielens_title(m["title"], m["year"]), m["genres"]])

    with open(out / "links.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["movieId", "imdbId", "tmdbId"])
        for m in movies:
            imdb = m["imdb_id"][2:] if m["imdb_id"].startswith("tt") else ""
            w.writerow([m["movie_id"], imdb, m["tmdb_id"] or ""])

    rows = sorted(rows, key=lambda r: (r[0], r[3]))
    with open(out / "ratings.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["userId", "movieId", "rating", "timestamp"])
        for ui, item, rating, ts in rows:
            w.writerow([ui + 1, movies[item]["movie_id"], f"{rating:.1f}", ts])

    # "Pre-fetched metadata": the same fields steps 2 and 3 would extract from TMDB / IMDb
    records = []
    for m in movies + series:
        records.append({
            "movie_id": m["movie_id"], "content_type": m["content_type"], "tmdb_id": m["tmdb_id"],
            "imdb_id": m["imdb_id"], "title": m["title"], "year": m["year"], "genres": m["genres"],
            "overview": m["overview"], "poster_path": "", "backdrop_path": "", "runtime": m["runtime"],
            "seasons": m["seasons"], "original_language": m["original_language"],
            "certifications": m["certifications"], "directors": m["directors"], "cast": m["cast"],
            "keywords": m["keywords"], "collection_name": m["collection_name"],
            "tmdb_popularity": m["tmdb_popularity"], "tmdb_vote_avg": m["tmdb_vote_avg"],
            "tmdb_vote_count": m["tmdb_vote_count"], "trailer_key": "",
            "imdb_rating": m["imdb_rating"], "imdb_votes": m["imdb_votes"],
            "metascore": m["metascore"], "rt_score": m["rt_score"],
        })
    meta = {
        "about": "CineMatch DEMO metadata. Real titles and facts written by hand; overviews are original; "
                 "ratings, votes, popularity and critic numbers are plausible demo values, not live data.",
        "generated_by": "ml/make_sample_data.py", "seed": SEED, "items": records,
    }
    with open(out / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)

    # Two popularity snapshots one month apart -> step4 can compute trending_velocity
    for day, key in (("20260901", "tmdb_popularity_prev"), ("20261001", "tmdb_popularity")):
        with open(out / "snapshots" / f"popularity_{day}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["content_type", "tmdb_id", "popularity"])
            for m in movies + series:
                if m["tmdb_id"]:
                    w.writerow([m["content_type"], m["tmdb_id"], m[key]])

    (out / "README.txt").write_text(
        "CineMatch demo dataset (generated by ml/make_sample_data.py - do not edit by hand).\n"
        "Real, well-known titles with hand-written metadata and ORIGINAL one-line overviews.\n"
        "All ratings are SYNTHETIC (800 fake users with hidden taste profiles, fixed seed 42).\n"
        "Votes, popularity and critic numbers are plausible demo values, not live data.\n"
        "Used by: python run_all.py --sample   (fully offline, no API keys needed)\n",
        encoding="utf-8")


def main():
    banner("Make sample data: building the offline demo dataset")
    rng = np.random.default_rng(SEED)
    movies, series = parse_titles()
    log(f"Read {len(movies)} movies and {len(series)} series from sample_titles.py")
    add_fake_scores(movies + series, rng)
    rows, users = generate_ratings(movies, rng)
    ratings = np.array([r[2] for r in rows])
    log(f"Generated {len(rows):,} synthetic ratings from {N_USERS} users "
        f"(mean {ratings.mean():.2f}, std {ratings.std():.2f})")
    per_user = np.bincount([r[0] for r in rows])
    log(f"Ratings per user: min {per_user.min()}, median {int(np.median(per_user))}, max {per_user.max()}")
    write_files(movies, series, rows, config.SAMPLE_DIR)
    log(f"Wrote demo dataset to {config.SAMPLE_DIR}")
    print("Next: python run_all.py --sample", flush=True)


if __name__ == "__main__":
    main()
