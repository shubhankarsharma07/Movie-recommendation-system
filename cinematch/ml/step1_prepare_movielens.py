"""
step1_prepare_movielens.py - read MovieLens and save compact, cleaned parquet files.

Input  (MOVIELENS_DIR, or ml/sample_data with --sample):
    ratings.csv  userId,movieId,rating,timestamp
    movies.csv   movieId,title,genres
    links.csv    movieId,imdbId,tmdbId
    tags.csv     userId,movieId,tag,timestamp      (optional - used as extra keywords)
Works for ml-25m, ml-32m and ml-latest-small (same file format).

Output (data/processed/ or data/processed_sample/):
    ratings.parquet   userId int32, movieId int32, rating float32, timestamp int64
    movies.parquet    movieId, title, year, genres, imdb_id, tmdb_id, ml_rating_mean, ml_rating_count,
                      ml_recent_count, ml_prev_count, ml_velocity, ml_tags
    movielens_info.json  dataset name + counts (used later for model_meta.json)

Memory: 25M ratings x (4+4+4+8 bytes) = ~500 MB in RAM with these compact types (instead of
~1.6 GB with pandas defaults). Measured peak for 25M ratings: ~1.5 GB, so an 8 GB laptop is fine.
Time: ml-25m takes ~0.5-2 minutes, ml-latest-small a few seconds.
"""
from __future__ import annotations

import argparse
import re
import time

import numpy as np
import pandas as pd

import config
from utils import banner, fail, human_minutes, join_list, log, save_json

RATING_DTYPES = {"userId": "int32", "movieId": "int32", "rating": "float32", "timestamp": "int64"}
YEAR_AT_END = re.compile(r"\s*\((\d{4})(?:[-–]\d{0,4})?\)\s*$")          # "... (1995)" or "(2007-2009)"
TRAILING_ARTICLE = re.compile(r"^(.*), (The|A|An|Les|La|Le|L'|Il|El|Das|Der|Die)$")


def read_ratings(path) -> pd.DataFrame:
    """Read ratings.csv with compact dtypes.

    We use pandas' normal C reader on purpose: on 25M ratings it is about as fast as the pyarrow
    reader but peaks at ~1.5 GB RAM instead of ~4 GB (measured), which matters on an 8 GB laptop.
    """
    size_mb = path.stat().st_size / 1e6
    log(f"Reading {path.name} ({size_mb:,.0f} MB) - estimated {human_minutes(size_mb / 25)}")
    return pd.read_csv(path, dtype=RATING_DTYPES, usecols=list(RATING_DTYPES))


def clean_title(raw: str) -> tuple[str, int | None]:
    """'Shawshank Redemption, The (1994)' -> ('The Shawshank Redemption', 1994)."""
    raw = str(raw).strip()
    match = YEAR_AT_END.search(raw)
    year = int(match.group(1)) if match else None
    title = YEAR_AT_END.sub("", raw).strip()
    # Move a trailing article to the front. If there is an alternative title in brackets at the
    # end ("City of Lost Children, The (Cité des enfants perdus, La)"), only fix the main part.
    alt = ""
    alt_match = re.search(r"\s(\([^()]*\))$", title)
    if alt_match:
        alt = " " + alt_match.group(1)
        title = title[: alt_match.start()]
    art = TRAILING_ARTICLE.match(title)
    if art:
        sep = "" if art.group(2).endswith("'") else " "
        title = f"{art.group(2)}{sep}{art.group(1)}"
    return (title + alt).strip(), year


def clean_genres(raw: str) -> str:
    """Keep MovieLens genre names, drop the '(no genres listed)' placeholder."""
    parts = [g for g in str(raw).split("|") if g and g != "(no genres listed)"]
    return join_list(parts)


def rating_velocity(ratings: pd.DataFrame, window_days: int) -> pd.DataFrame:
    """How fast is each movie being rated lately?

    Compare the number of ratings in the last `window_days` of the dataset with the window
    before it.  velocity = (recent - previous) / (previous + 5)
    (+5 smooths tiny numbers: going from 1 to 3 ratings is not a 200% trend.)
    """
    end = int(ratings["timestamp"].max())
    window = window_days * 86_400
    ts = ratings["timestamp"].to_numpy()
    movie = ratings["movieId"].to_numpy()
    recent_mask = ts > end - window
    prev_mask = (ts > end - 2 * window) & ~recent_mask
    recent = pd.Series(movie[recent_mask]).value_counts()
    prev = pd.Series(movie[prev_mask]).value_counts()
    out = pd.DataFrame({"ml_recent_count": recent, "ml_prev_count": prev}).fillna(0).astype("int32")
    out["ml_velocity"] = ((out["ml_recent_count"] - out["ml_prev_count"])
                          / (out["ml_prev_count"] + 5.0)).round(4)
    out.index.name = "movieId"
    return out


def top_tags(tags_path, keep_movies, per_movie: int = 10) -> pd.Series:
    """Most common user tags per movie (lowercase), e.g. 'mind-bending|twist ending'."""
    log("Reading tags.csv (optional user tags -> extra keywords)")
    tags = pd.read_csv(tags_path, usecols=["movieId", "tag"], dtype={"movieId": "int32", "tag": "str"})
    tags = tags[tags["movieId"].isin(keep_movies)].dropna()
    tags["tag"] = tags["tag"].str.lower().str.strip()
    tags = tags[tags["tag"].str.len().between(2, 40)]
    counts = tags.groupby(["movieId", "tag"]).size().rename("n").reset_index()
    counts = counts[counts["n"] >= 2].sort_values(["movieId", "n"], ascending=[True, False])
    return counts.groupby("movieId")["tag"].apply(lambda s: join_list(s.head(per_movie).tolist()))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Step 1 - prepare MovieLens ratings and movies")
    parser.add_argument("--sample", action="store_true", help="use the bundled demo data")
    args = parser.parse_args(argv)

    banner("Step 1/9 - Prepare MovieLens")
    start = time.time()
    source = config.movielens_dir(args.sample)
    out_dir = config.processed_dir(args.sample)
    for name in ("ratings.csv", "movies.csv", "links.csv"):
        if not (source / name).exists():
            hint = ("run: python make_sample_data.py" if args.sample else
                    "download https://files.grouplens.org/datasets/movielens/ml-25m.zip, unzip it and "
                    "set MOVIELENS_DIR in .env to that folder")
            fail(f"{source / name} not found.\n          -> {hint}")
    log(f"MovieLens folder: {source}")

    # ---- ratings -------------------------------------------------------------------------
    ratings = read_ratings(source / "ratings.csv")
    log(f"Loaded {len(ratings):,} ratings from {ratings['userId'].nunique():,} users "
        f"({ratings.memory_usage(deep=True).sum() / 1e6:,.0f} MB in memory)")

    counts = ratings["movieId"].value_counts()
    keep = counts[counts >= config.MIN_RATINGS].index
    dropped = len(counts) - len(keep)
    ratings = ratings[ratings["movieId"].isin(keep)].reset_index(drop=True)
    log(f"Kept {len(keep):,} movies with >= {config.MIN_RATINGS} ratings "
        f"(dropped {dropped:,} rarely-rated movies) -> {len(ratings):,} ratings")

    # ---- movies + links ------------------------------------------------------------------
    movies = pd.read_csv(source / "movies.csv", dtype={"movieId": "int32", "title": "str", "genres": "str"})
    links = pd.read_csv(source / "links.csv", dtype={"movieId": "int32", "imdbId": "str", "tmdbId": "str"})
    movies = movies[movies["movieId"].isin(keep)].merge(links, on="movieId", how="left")

    parsed = movies["title"].map(clean_title)
    movies["title"] = parsed.map(lambda t: t[0])
    movies["year"] = pd.array(parsed.map(lambda t: t[1]).tolist(), dtype="Int64")
    movies["genres"] = movies["genres"].map(clean_genres)
    # IMDb ids in links.csv are numbers without 'tt' -> 'tt' + 7 digits (zero padded)
    imdb_num = pd.to_numeric(movies["imdbId"], errors="coerce")
    movies["imdb_id"] = ["" if pd.isna(x) else f"tt{int(x):07d}" for x in imdb_num]
    movies["tmdb_id"] = pd.to_numeric(movies["tmdbId"], errors="coerce").astype("Int64")
    movies = movies.drop(columns=["imdbId", "tmdbId"])

    # ---- per-movie statistics ---------------------------------------------------------------
    stats = ratings.groupby("movieId")["rating"].agg(ml_rating_mean="mean", ml_rating_count="size")
    stats["ml_rating_mean"] = stats["ml_rating_mean"].round(3)
    movies = movies.merge(stats, left_on="movieId", right_index=True, how="left")
    velocity = rating_velocity(ratings, config.VELOCITY_WINDOW_DAYS)
    movies = movies.merge(velocity, left_on="movieId", right_index=True, how="left")
    for col in ("ml_recent_count", "ml_prev_count"):
        movies[col] = movies[col].fillna(0).astype("int32")
    movies["ml_velocity"] = movies["ml_velocity"].fillna(0.0)

    if (source / "tags.csv").exists():
        movies = movies.merge(top_tags(source / "tags.csv", keep).rename("ml_tags"),
                              left_on="movieId", right_index=True, how="left")
    movies["ml_tags"] = movies.get("ml_tags", pd.Series("", index=movies.index)).fillna("")
    movies = movies.sort_values("movieId").reset_index(drop=True)

    # ---- save ---------------------------------------------------------------------------
    ratings.to_parquet(out_dir / "ratings.parquet", index=False)
    movies.to_parquet(out_dir / "movies.parquet", index=False)
    first = pd.to_datetime(int(ratings["timestamp"].min()), unit="s").date()
    last = pd.to_datetime(int(ratings["timestamp"].max()), unit="s").date()
    name = "CineMatch demo ratings (synthetic)" if args.sample else _dataset_name(source.name)
    save_json(out_dir / "movielens_info.json", {
        "name": name, "folder": str(source), "n_ratings": int(len(ratings)),
        "n_users": int(ratings["userId"].nunique()), "n_movies": int(len(movies)),
        "min_ratings": config.MIN_RATINGS, "first_rating": str(first), "last_rating": str(last),
        "sample": bool(args.sample),
    })
    log(f"Ratings from {first} to {last}; mean rating {ratings['rating'].mean():.3f}")
    log(f"Saved {out_dir / 'ratings.parquet'} and movies.parquet ({len(movies):,} movies)")
    log(f"Step 1 done in {time.time() - start:.1f}s")


def _dataset_name(folder: str) -> str:
    """'ml-25m' -> 'MovieLens 25M', 'ml-latest-small' -> 'MovieLens latest-small'."""
    tail = folder.lower().replace("ml-", "", 1)
    return f"MovieLens {tail.upper() if tail[:1].isdigit() else tail}"


if __name__ == "__main__":
    main()
