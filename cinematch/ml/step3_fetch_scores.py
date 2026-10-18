"""
step3_fetch_scores.py - IMDb ratings (+ optional Metascore / Rotten Tomatoes) for every title.

1. IMDb publishes free daily files for non-commercial use. We download
   https://datasets.imdbws.com/title.ratings.tsv.gz (~8 MB, cached in data/raw/imdb/ and
   re-downloaded after IMDB_MAX_AGE_DAYS) and join on the IMDb id ('tt' + 7 digits, zero padded).
2. Optional: if OMDB_API_KEY is set, ask OMDb for the Metascore and Rotten Tomatoes score.
   The free key allows 1000 calls/day, so we make at most OMDB_DAILY_LIMIT new calls per day
   (most popular titles first) and cache every answer in data/raw/omdb/{imdb_id}.json.
   Run the step again on later days to fill in more titles.

Output: data/processed/scores.parquet  movie_id, imdb_id, imdb_rating, imdb_votes, metascore, rt_score
With --sample: scores come from ml/sample_data/metadata.json (no network).
Time: < 1 min for IMDb; OMDb ~ 2-3 min per 900 calls.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date
from pathlib import Path

import pandas as pd

import config
from utils import banner, fail, load_json, log, save_json, warn

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None

SCORE_COLUMNS = ["movie_id", "imdb_id", "imdb_rating", "imdb_votes", "metascore", "rt_score"]


def normalise_imdb_id(value) -> str:
    """'114709', 'tt114709', 114709 -> 'tt0114709'. Anything else -> ''."""
    text = str(value or "").strip().lower()
    digits = text[2:] if text.startswith("tt") else text
    return f"tt{int(digits):07d}" if digits.isdigit() else ""


def title_ids(out_dir: Path) -> pd.DataFrame:
    """One row per catalog title with its IMDb id (MovieLens links first, TMDB as backup)."""
    movies = pd.read_parquet(out_dir / "movies.parquet", columns=["movieId", "imdb_id"])
    ids = movies.rename(columns={"movieId": "movie_id"})
    ids["movie_id"] = ids["movie_id"].astype("int64")
    tmdb_path = out_dir / "tmdb_meta.parquet"
    if tmdb_path.exists():
        tmdb = pd.read_parquet(tmdb_path, columns=["movie_id", "imdb_id", "content_type"])
        ids = ids.merge(tmdb[["movie_id", "imdb_id"]].rename(columns={"imdb_id": "tmdb_imdb"}),
                        on="movie_id", how="left")
        ids["imdb_id"] = ids["imdb_id"].where(ids["imdb_id"].fillna("") != "", ids["tmdb_imdb"])
        series = tmdb.loc[tmdb["content_type"] == "series", ["movie_id", "imdb_id"]]
        ids = pd.concat([ids[["movie_id", "imdb_id"]], series], ignore_index=True)
    ids["imdb_id"] = ids["imdb_id"].map(normalise_imdb_id)
    return ids.drop_duplicates("movie_id")


def download_imdb_ratings() -> Path | None:
    """Download title.ratings.tsv.gz unless a fresh copy is already cached."""
    config.IMDB_RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = config.IMDB_RAW_DIR / "title.ratings.tsv.gz"
    if path.exists() and time.time() - path.stat().st_mtime < config.IMDB_MAX_AGE_DAYS * 86_400:
        log(f"Using cached {path.name} (less than {config.IMDB_MAX_AGE_DAYS} days old)")
        return path
    if httpx is None:
        warn("httpx not installed - cannot download IMDb ratings")
        return path if path.exists() else None
    log(f"Downloading {config.IMDB_RATINGS_URL}")
    tmp = path.with_suffix(".tmp")
    try:
        with httpx.stream("GET", config.IMDB_RATINGS_URL, timeout=120.0, follow_redirects=True) as response:
            response.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in response.iter_bytes(1 << 20):
                    f.write(chunk)
        os.replace(tmp, path)
        log(f"Saved {path} ({path.stat().st_size / 1e6:.1f} MB)")
    except Exception as error:
        warn(f"IMDb download failed ({error})" + ("; using the older cached copy" if path.exists() else ""))
    return path if path.exists() else None


def read_imdb_ratings(path: Path, wanted: set[str]) -> pd.DataFrame:
    df = pd.read_csv(path, sep="\t", compression="gzip", na_values="\\N",
                     dtype={"tconst": "str", "averageRating": "float32", "numVotes": "float64"})
    df = df[df["tconst"].isin(wanted)]
    return df.rename(columns={"tconst": "imdb_id", "averageRating": "imdb_rating", "numVotes": "imdb_votes"})


# ----------------------------------------------------------------------------------------------
# OMDb (optional)
# ----------------------------------------------------------------------------------------------
def fetch_omdb(imdb_ids: list[str]) -> None:
    """Fetch up to OMDB_DAILY_LIMIT uncached titles today (keeps a small usage counter file)."""
    config.OMDB_RAW_DIR.mkdir(parents=True, exist_ok=True)
    usage_file = config.OMDB_RAW_DIR / "_usage.json"
    usage = load_json(usage_file, {})
    today = date.today().isoformat()
    used = usage.get("calls", 0) if usage.get("date") == today else 0
    budget = max(0, config.OMDB_DAILY_LIMIT - used)
    todo = [i for i in imdb_ids if not (config.OMDB_RAW_DIR / f"{i}.json").exists()]
    log(f"OMDb: {len(imdb_ids) - len(todo):,} cached, {len(todo):,} missing, {budget} calls left today")
    if not todo or budget == 0:
        return
    calls, errors_in_a_row = 0, 0
    with httpx.Client(timeout=20.0) as client:
        for imdb_id in todo[:budget]:
            try:
                response = client.get(config.OMDB_BASE_URL, params={"i": imdb_id, "apikey": config.OMDB_API_KEY})
                calls += 1
                data = response.json()
                errors_in_a_row = 0
            except Exception as error:
                errors_in_a_row += 1
                warn(f"OMDb request failed for {imdb_id}: {error}")
                if errors_in_a_row >= 5:
                    warn("OMDb failed 5 times in a row - stopping for now (run step3 again later)")
                    break
                time.sleep(2)
                continue
            if data.get("Response") == "False" and "limit" in str(data.get("Error", "")).lower():
                warn("OMDb daily limit reached - run again tomorrow to continue")
                break
            if response.status_code == 401:
                warn("OMDb rejected the key (401) - check OMDB_API_KEY")
                break
            tmp = config.OMDB_RAW_DIR / f"{imdb_id}.json.tmp"
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, config.OMDB_RAW_DIR / f"{imdb_id}.json")
            time.sleep(0.1)                            # be polite
            if calls % 100 == 0:
                log(f"OMDb: {calls} calls done")
    save_json(usage_file, {"date": today, "calls": used + calls})
    log(f"OMDb: made {calls} calls today (total {used + calls})")


def read_omdb_cache(imdb_ids: list[str]) -> pd.DataFrame:
    rows = []
    for imdb_id in imdb_ids:
        data = load_json(config.OMDB_RAW_DIR / f"{imdb_id}.json")
        if not data or data.get("Response") == "False":
            continue
        meta = str(data.get("Metascore", "")).strip()
        rt = next((r.get("Value", "") for r in data.get("Ratings", []) if r.get("Source") == "Rotten Tomatoes"), "")
        rows.append({
            "imdb_id": imdb_id,
            "metascore": float(meta) if meta.isdigit() else None,
            "rt_score": float(rt.rstrip("%")) if rt.rstrip("%").isdigit() else None,
        })
    return pd.DataFrame(rows, columns=["imdb_id", "metascore", "rt_score"])


def sample_scores() -> pd.DataFrame:
    meta = load_json(config.SAMPLE_DIR / "metadata.json")
    if meta is None:
        fail("ml/sample_data/metadata.json not found -> run: python make_sample_data.py")
    df = pd.DataFrame(meta["items"])
    log(f"Loaded demo scores for {len(df):,} titles (no network used)")
    return df[SCORE_COLUMNS]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Step 3 - IMDb ratings + optional OMDb critic scores")
    parser.add_argument("--sample", action="store_true", help="use bundled demo scores (offline)")
    parser.add_argument("--no-omdb", action="store_true", help="skip OMDb even if a key is set")
    args = parser.parse_args(argv)

    banner("Step 3/9 - Fetch IMDb / critic scores")
    out_dir = config.processed_dir(args.sample)
    if args.sample:
        scores = sample_scores()
    else:
        if not (out_dir / "movies.parquet").exists():
            fail("movies.parquet not found -> run step1_prepare_movielens.py first")
        ids = title_ids(out_dir)
        wanted = set(ids["imdb_id"]) - {""}
        log(f"{len(ids):,} titles, {len(wanted):,} with an IMDb id")
        scores = ids.copy()
        path = download_imdb_ratings()
        if path is not None:
            imdb = read_imdb_ratings(path, wanted)
            scores = scores.merge(imdb, on="imdb_id", how="left")
            log(f"IMDb ratings found for {scores['imdb_rating'].notna().sum():,} titles")
        else:
            scores["imdb_rating"], scores["imdb_votes"] = None, None

        if config.OMDB_API_KEY and not args.no_omdb and httpx is not None:
            order = scores[scores["imdb_id"] != ""].sort_values("imdb_votes", ascending=False)
            fetch_omdb(order["imdb_id"].drop_duplicates().tolist())
        elif not config.OMDB_API_KEY:
            log("No OMDB_API_KEY - skipping Metascore / Rotten Tomatoes (optional)")
        omdb = read_omdb_cache(sorted(wanted)) if config.OMDB_RAW_DIR.exists() else pd.DataFrame(
            columns=["imdb_id", "metascore", "rt_score"])
        scores = scores.merge(omdb, on="imdb_id", how="left")

    for col in ("imdb_rating", "imdb_votes", "metascore", "rt_score"):
        scores[col] = pd.to_numeric(scores[col], errors="coerce").astype("float64")
    scores["movie_id"] = scores["movie_id"].astype("int64")
    scores["imdb_id"] = scores["imdb_id"].fillna("")
    scores = scores[SCORE_COLUMNS]
    scores.to_parquet(out_dir / "scores.parquet", index=False)
    log(f"Saved {out_dir / 'scores.parquet'}: imdb {scores['imdb_rating'].notna().sum():,}, "
        f"metascore {scores['metascore'].notna().sum():,}, rotten tomatoes {scores['rt_score'].notna().sum():,}")


if __name__ == "__main__":
    main()
