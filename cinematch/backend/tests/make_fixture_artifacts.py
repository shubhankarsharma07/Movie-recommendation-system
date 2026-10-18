"""
Generates SYNTHETIC model artifacts in exactly the CONTRACT section 2 format,
so the backend can be tested without the real ML pipeline.

    python tests/make_fixture_artifacts.py                     # 120 items -> tests/fixtures/artifacts
    python tests/make_fixture_artifacts.py --n 65000 --out /tmp/big --k 100 --d 384

The data has real structure: item factors and plot embeddings are built from
the genres (+ noise), so "users who like Horror" really get Horror back.
A few fixed facts the tests rely on:
  * "Christopher Nolan" directs several films
  * "Toy Saga Collection" is a franchise
  * ~15 % of items are series (no CF data, as in the real pipeline)
  * Animation/Children titles are rated U or UA 7+, Horror titles are A
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

GENRES = ["Action", "Adventure", "Animation", "Children", "Comedy", "Crime", "Documentary", "Drama",
          "Fantasy", "Film-Noir", "Horror", "IMAX", "Musical", "Mystery", "Romance", "Sci-Fi",
          "Thriller", "War", "Western"]
GENRE_WEIGHTS = np.array([8, 6, 4, 3, 10, 5, 2, 12, 4, 1, 5, 1, 2, 4, 7, 5, 7, 2, 1], dtype=float)
MOODS_FOR_GENRE = {
    "Action": ["action-packed", "epic", "thrilling"], "Adventure": ["epic", "feel-good"],
    "Animation": ["family", "feel-good", "light"], "Children": ["family", "light"],
    "Comedy": ["funny", "light", "feel-good"], "Crime": ["dark", "thrilling"],
    "Documentary": ["inspiring"], "Drama": ["melancholic", "heartwarming", "slow-burn"],
    "Fantasy": ["epic", "cozy"], "Film-Noir": ["dark", "slow-burn"], "Horror": ["scary", "dark"],
    "IMAX": ["epic"], "Musical": ["feel-good", "romantic"], "Mystery": ["mind-bending", "slow-burn"],
    "Romance": ["romantic", "feel-good", "cozy"], "Sci-Fi": ["mind-bending", "epic"],
    "Thriller": ["thrilling", "dark"], "War": ["epic", "dark"], "Western": ["epic", "slow-burn"],
}
EMOTION_FOR_GENRE = {  # (start, end)
    "Horror": ("fear", "fear"), "Thriller": ("fear", "surprise"), "Comedy": ("joy", "joy"),
    "Romance": ("sadness", "joy"), "Drama": ("sadness", "sadness"), "Animation": ("joy", "joy"),
    "Children": ("joy", "joy"), "Action": ("anger", "joy"), "Crime": ("anger", "disgust"),
    "Mystery": ("surprise", "surprise"), "Sci-Fi": ("neutral", "surprise"), "War": ("fear", "sadness"),
}
VALENCE = {"joy": 1, "surprise": 1, "neutral": 0, "sadness": -1, "fear": -1, "anger": -1, "disgust": -1}
LANGUAGES = ["en", "hi", "ko", "fr", "ja", "ta"]
LANG_P = [0.6, 0.15, 0.08, 0.07, 0.05, 0.05]
DIRECTORS = ["Christopher Nolan", "Greta Gerwig", "Bong Joon-ho", "Zoya Akhtar", "Hayao Miyazaki",
             "Denis Villeneuve", "Jordan Peele", "Mani Ratnam", "Céline Sciamma", "Taika Waititi",
             "Rajkumar Hirani", "Sofia Coppola", "Park Chan-wook", "Wes Anderson", "Ava DuVernay",
             "Guillermo del Toro", "Karan Johar", "Kathryn Bigelow", "Ari Aster", "Pete Docter",
             "S. S. Rajamouli", "Agnès Varda", "James Wan", "Nora Ephron", "Ang Lee"]
FIRST = ["Aarav", "Maya", "Leo", "Priya", "Noah", "Zara", "Kenji", "Sofia", "Ravi", "Emma", "Omar",
         "Lena", "Arjun", "Chloe", "Ishaan", "Mira", "Lucas", "Ananya", "Felix", "Tara"]
LAST = ["Sharma", "Kim", "Martin", "Rossi", "Tanaka", "Khan", "Dubois", "Patel", "Silva", "Brown"]
KEYWORDS = ["christmas", "halloween", "rain", "haunted house", "love", "summer", "family", "diwali",
            "snow", "ghost", "friendship", "heist", "time travel", "space", "revenge", "school",
            "road trip", "dragon", "detective", "music", "war", "island", "robot", "small town"]
COLLECTIONS = ["Toy Saga Collection", "Star Voyage Collection", "Midnight Files Collection",
               "Desi Dhamaal Collection"]
ADJ = ["Silent", "Golden", "Last", "Hidden", "Broken", "Crimson", "Electric", "Lost", "Wild", "Frozen",
       "Midnight", "Paper", "Velvet", "Burning", "Secret", "Little", "Endless", "Neon", "Hollow", "Brave"]
NOUN = ["River", "Kingdom", "Signal", "Garden", "Promise", "Horizon", "Echo", "Harbor", "Monsoon",
        "Orbit", "Lantern", "Carnival", "Mirror", "Voyage", "Letter", "Storm", "Circus", "Summer",
        "Station", "Melody"]


def make_artifacts(out_dir: Path, n_items: int = 120, k: int = 16, d: int = 32, seed: int = 7,
                   version: str = "v20261001_120000", write_current: bool = True) -> Path:
    rng = np.random.default_rng(seed)
    out_dir = Path(out_dir)
    folder = out_dir / version
    folder.mkdir(parents=True, exist_ok=True)
    n = n_items
    G = len(GENRES)

    is_series = rng.random(n) < 0.15
    genre_matrix = np.zeros((n, G), dtype=bool)
    probs = GENRE_WEIGHTS / GENRE_WEIGHTS.sum()
    for i in range(n):
        count = rng.integers(1, 4)
        genre_matrix[i, rng.choice(G, size=count, replace=False, p=probs)] = True

    rows = []
    nolan_rows = set(range(3, n, max(4, n // 8)))          # several Nolan films
    for i in range(n):
        genres = [GENRES[j] for j in np.flatnonzero(genre_matrix[i])]
        kids = any(g in ("Animation", "Children") for g in genres)
        if kids:
            age = rng.choice(["U", "UA 7+"])
        elif "Horror" in genres:
            age = "A"
        else:
            age = rng.choice(["UA 7+", "UA 13+", "UA 16+", "A", ""], p=[0.15, 0.4, 0.3, 0.1, 0.05])
        main = genres[0]
        start, end = EMOTION_FOR_GENRE.get(main, (rng.choice(list(VALENCE)), rng.choice(list(VALENCE))))
        delta = VALENCE[end] - VALENCE[start]
        arc = "rise" if delta > 0 else "fall" if delta < 0 else "steady"
        moods = sorted({m for g in genres for m in MOODS_FOR_GENRE.get(g, [])[:2]})
        year = int(rng.integers(1955, 2026))
        series = bool(is_series[i])
        lang = rng.choice(LANGUAGES, p=LANG_P)
        director = "Christopher Nolan" if i in nolan_rows and not series else DIRECTORS[rng.integers(len(DIRECTORS))]
        cast = [f"{FIRST[rng.integers(len(FIRST))]} {LAST[rng.integers(len(LAST))]}" for _ in range(5)]
        keywords = list(rng.choice(KEYWORDS, size=3, replace=False))
        if "Horror" in genres and "halloween" not in keywords:
            keywords.append("halloween")
        collection = COLLECTIONS[i % 4] if (i % 9 == 0 and not series) else ""
        if collection == "Toy Saga Collection":
            genres_text = "|".join(sorted(set(genres) | {"Animation"}))
            age = "U"
        else:
            genres_text = "|".join(genres)
        ml_count = 0 if series else int(rng.lognormal(6, 1.5))
        ml_mean = "" if series else round(float(np.clip(rng.normal(3.5, 0.45), 1.0, 4.9)), 3)
        critic = round(float(rng.uniform(35, 98)), 1) if rng.random() < 0.7 else ""
        pop = float(rng.beta(1.2, 4.0))
        quality = float(np.clip((float(ml_mean or 3.5) - 1) / 4 * 0.6 + (float(critic or 60) / 100) * 0.4, 0, 1))
        title = f"{ADJ[i % len(ADJ)]} {NOUN[(i // len(ADJ)) % len(NOUN)]}"
        if i >= len(ADJ) * len(NOUN):
            title += f" {i // (len(ADJ) * len(NOUN)) + 1}"
        rows.append({
            "movie_id": 10_000_000 + i if series else i + 1,
            "content_type": "series" if series else "movie",
            "tmdb_id": 1000 + i, "imdb_id": f"tt{1000000 + i}", "title": title, "year": year,
            "genres": genres_text,
            "overview": f"A {moods[0] if moods else 'gripping'} {main.lower()} story about the {title.lower()}.",
            "poster_path": f"/p{i}.jpg", "backdrop_path": f"/b{i}.jpg" if i % 10 else "",
            "runtime": int(rng.integers(22, 61)) if series else int(rng.integers(80, 181)),
            "seasons": int(rng.integers(1, 7)) if series else "",
            "original_language": lang, "age_rating": age, "certification_raw": f"US:{age or 'NR'}",
            "directors": director, "cast": "|".join(cast), "keywords": "|".join(keywords),
            "collection_name": collection, "ml_rating_mean": ml_mean, "ml_rating_count": ml_count,
            "tmdb_popularity": round(pop * 100, 2), "tmdb_vote_avg": round(float(rng.uniform(5, 9)), 1),
            "tmdb_vote_count": int(rng.integers(10, 20000)),
            "imdb_rating": round(float(rng.uniform(5, 9)), 1), "imdb_votes": int(rng.integers(100, 900000)),
            "critic_score": critic, "popularity_score": round(pop, 5),
            "trending_velocity": round(float(rng.normal(0, 0.3)), 4), "quality_score": round(quality, 4),
            "start_emotion": start, "end_emotion": end, "emotion_arc": arc, "mood_tags": "|".join(moods),
            "decade": (year // 10) * 10, "trailer_key": f"yt{i:09d}",
        })
    df = pd.DataFrame(rows)
    genre_matrix = np.array([[g in r.split("|") for g in GENRES] for r in df["genres"]], dtype=bool)

    # CF factors from genres + noise (series have no CF data, like the real pipeline)
    W = rng.normal(0, 1, size=(G, k)).astype(np.float32)
    gv = genre_matrix.astype(np.float32)
    gv /= np.maximum(gv.sum(axis=1, keepdims=True), 1) ** 0.5
    Q = (gv @ W + 0.35 * rng.normal(0, 1, size=(n, k))).astype(np.float32) * 0.3
    has_cf = ~is_series & (rng.random(n) > 0.03)
    Q[~has_cf] = 0
    bias = np.where(has_cf, rng.normal(0, 0.3, size=n), 0).astype(np.float32)

    # plot embeddings, also genre-structured, L2-normalised, float16
    W2 = rng.normal(0, 1, size=(G, d)).astype(np.float32)
    E = gv @ W2 + 0.6 * rng.normal(0, 1, size=(n, d)).astype(np.float32)
    E /= np.linalg.norm(E, axis=1, keepdims=True)
    has_emb = rng.random(n) > 0.04
    E[~has_emb] = 0

    df.to_csv(folder / "catalog.csv", index=False, encoding="utf-8")
    np.save(folder / "item_factors.npy", Q)
    np.save(folder / "item_bias.npy", bias)
    np.save(folder / "has_cf.npy", has_cf)
    np.save(folder / "plot_emb.npy", E.astype(np.float16))
    np.save(folder / "has_emb.npy", has_emb)
    meta = {
        "version": version, "trained_at": "2026-10-01T12:00:00Z",
        "algorithm": "SVD (synthetic test fixture)", "n_factors": k, "n_epochs": 0,
        "lr_all": 0.005, "reg_all": 0.02, "global_mean": 3.5, "fold_in_reg": 0.1,
        "n_items": n, "n_cf_items": int(has_cf.sum()), "n_train_ratings": 0, "n_users_trained": 0,
        "embedding_model": "synthetic", "emotion_model": "synthetic",
        "metrics": {"rmse": 0.0, "mae": 0.0},
        "blend_weights": {"cf": 0.45, "content": 0.15, "ref": 0.35, "ctx": 0.25, "quality": 0.12,
                          "trend": 0.05, "behavior": 0.10},
        "data_sources": ["synthetic"], "dataset_mode": "sample",
    }
    (folder / "model_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    if write_current:
        set_current(out_dir, version)
    return folder


def set_current(out_dir: Path, version: str) -> None:
    """Atomic write of current.txt, exactly like the ml/ pipeline does."""
    tmp = Path(out_dir) / "current.txt.tmp"
    tmp.write_text(version, encoding="utf-8")
    os.replace(tmp, Path(out_dir) / "current.txt")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(Path(__file__).parent / "fixtures" / "artifacts"))
    parser.add_argument("--n", type=int, default=120)
    parser.add_argument("--k", type=int, default=16)
    parser.add_argument("--d", type=int, default=32)
    parser.add_argument("--version", default="v20261001_120000")
    args = parser.parse_args()
    path = make_artifacts(Path(args.out), args.n, args.k, args.d, version=args.version)
    print(f"wrote {path}")
