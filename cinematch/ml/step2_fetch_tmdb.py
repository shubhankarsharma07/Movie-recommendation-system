"""
step2_fetch_tmdb.py - download movie + series details from TMDB and turn them into one table.

What it does
  1. For every MovieLens movie with a tmdbId:
        GET /3/movie/{id}?append_to_response=credits,keywords,release_dates,videos
     The raw JSON is cached in data/raw/tmdb/movie/{id}.json. Cached files are skipped, so you
     can stop the script at any time (Ctrl+C) and run it again later - it resumes.
  2. Finds popular + top-rated TV series (TMDB_TV_PAGES pages of each, default 25) plus extra
     Indian series (discover, origin country IN) and fetches
        GET /3/tv/{id}?append_to_response=credits,keywords,content_ratings,videos,external_ids
     into data/raw/tmdb/tv/{id}.json   (external_ids gives the IMDb id needed by step3).
  3. Saves a dated popularity snapshot data/raw/tmdb/snapshots/popularity_YYYYMMDD.csv
     (from TMDB's free daily ID export file). With 2+ snapshots, step4 can compute how fast
     each title's popularity is changing ("trending velocity").
  4. Parses all cached JSON into data/processed/tmdb_meta.parquet (one row per movie/series).

Being polite to the API: max ~35 requests/second (TMDB_RATE_LIMIT), 16 at a time, and
automatic retries with exponential backoff on 429 (too many requests) and 5xx errors.

Auth: put TMDB_READ_TOKEN (v4 "API Read Access Token", sent as a Bearer header) or
TMDB_API_KEY (v3 key, sent as ?api_key=) in the .env file. No key -> the step is skipped
with a warning and the pipeline continues without posters/overviews.

Time: first run for ml-25m (~32k movies with >= 20 ratings) ~ 15-20 min at 35 req/s; re-runs
only fetch what is missing (seconds).
With --sample it makes no network calls: it converts ml/sample_data/metadata.json instead.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import os
import random
import statistics
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import config
from utils import banner, fail, join_list, load_json, log, save_json, warn

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = None

MOVIE_APPEND = "credits,keywords,release_dates,videos"
TV_APPEND = "credits,keywords,content_ratings,videos,external_ids"
CERT_COUNTRIES = ("IN", "US", "GB")           # the countries step4 knows how to map

# TMDB genre names -> MovieLens genre names (CONTRACT uses MovieLens names everywhere)
TMDB_TO_ML_GENRES = {
    "Action": ["Action"], "Adventure": ["Adventure"], "Animation": ["Animation"],
    "Comedy": ["Comedy"], "Crime": ["Crime"], "Documentary": ["Documentary"], "Drama": ["Drama"],
    "Family": ["Children"], "Fantasy": ["Fantasy"], "History": ["Drama"], "Horror": ["Horror"],
    "Music": ["Musical"], "Mystery": ["Mystery"], "Romance": ["Romance"],
    "Science Fiction": ["Sci-Fi"], "Thriller": ["Thriller"], "War": ["War"], "Western": ["Western"],
    "TV Movie": [],
    # TV-only genre names
    "Action & Adventure": ["Action", "Adventure"], "Kids": ["Children"], "News": [], "Reality": [],
    "Sci-Fi & Fantasy": ["Sci-Fi", "Fantasy"], "Soap": ["Drama"], "Talk": [], "War & Politics": ["War"],
}

TMDB_META_COLUMNS = [
    "movie_id", "content_type", "tmdb_id", "imdb_id", "title", "original_title", "year", "overview",
    "poster_path", "backdrop_path", "runtime", "seasons", "original_language", "genres", "tmdb_genres",
    "certifications", "directors", "cast", "keywords", "collection_name", "tmdb_popularity",
    "tmdb_vote_avg", "tmdb_vote_count", "trailer_key",
]


class AuthError(Exception):
    pass


# ----------------------------------------------------------------------------------------------
# Talking to the API
# ----------------------------------------------------------------------------------------------
def tmdb_auth() -> tuple[dict, dict] | None:
    """Return (headers, params) for TMDB, or None when no key is configured."""
    token, key = config.TMDB_READ_TOKEN, config.TMDB_API_KEY
    if not token and key.startswith("eyJ"):        # someone pasted the v4 token into TMDB_API_KEY
        token, key = key, ""
    if token:
        return {"Authorization": f"Bearer {token}", "accept": "application/json"}, {}
    if key:
        return {"accept": "application/json"}, {"api_key": key}
    return None


class RateLimiter:
    """Spaces out request starts so we never go above `rate` requests per second."""

    def __init__(self, rate: float):
        self.interval = 1.0 / max(rate, 0.1)
        self.next_time = 0.0
        self.lock = asyncio.Lock()

    async def wait(self):
        async with self.lock:
            now = time.monotonic()
            self.next_time = max(self.next_time, now)
            delay = self.next_time - now
            self.next_time += self.interval
        if delay > 0:
            await asyncio.sleep(delay)


async def get_json(client, url, params, limiter, semaphore, max_tries: int = 6):
    """GET with retries. Returns (status, data) where status is 'ok', 'not_found' or 'failed'."""
    for attempt in range(max_tries):
        await limiter.wait()
        try:
            async with semaphore:
                response = await client.get(url, params=params)
        except (httpx.TimeoutException, httpx.TransportError):
            await asyncio.sleep(min(60, 2 ** attempt + random.random()))
            continue
        code = response.status_code
        if code == 200:
            return "ok", response.json()
        if code == 404:
            return "not_found", None
        if code == 401:
            raise AuthError("TMDB rejected the key (HTTP 401). Check TMDB_API_KEY / TMDB_READ_TOKEN in .env")
        if code == 429 or code >= 500:
            retry_after = response.headers.get("Retry-After", "")
            wait = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else 2 ** attempt
            await asyncio.sleep(min(60, wait + random.random()))
            continue
        return "failed", None                       # other 4xx: retrying will not help
    return "failed", None


def write_json_atomic(path: Path, data) -> None:
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


async def fetch_details(kind: str, ids: list[int], auth, out_dir: Path) -> dict:
    """Fetch /movie/{id} or /tv/{id} for every id that is not cached yet."""
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = [i for i in ids if not (out_dir / f"{i}.json").exists()]
    stats = {"cached": len(ids) - len(todo), "ok": 0, "not_found": 0, "failed": 0}
    if not todo:
        log(f"{kind}: all {len(ids):,} already cached")
        return stats
    eta = len(todo) / config.TMDB_RATE_LIMIT
    log(f"{kind}: {stats['cached']:,} cached, fetching {len(todo):,} "
        f"(estimated {eta / 60:.1f} min at {config.TMDB_RATE_LIMIT:.0f} req/s)")

    headers, base_params = auth
    append = MOVIE_APPEND if kind == "movie" else TV_APPEND
    params = {**base_params, "append_to_response": append, "language": config.TMDB_LANGUAGE}
    limiter = RateLimiter(config.TMDB_RATE_LIMIT)
    semaphore = asyncio.Semaphore(config.TMDB_CONCURRENCY)
    limits = httpx.Limits(max_connections=config.TMDB_CONCURRENCY,
                          max_keepalive_connections=config.TMDB_CONCURRENCY)

    async def one(tmdb_id: int) -> str:
        status, data = await get_json(client, f"{config.TMDB_BASE_URL}/{kind}/{tmdb_id}",
                                      params, limiter, semaphore)
        if status == "ok":
            write_json_atomic(out_dir / f"{tmdb_id}.json", data)
        elif status == "not_found":                 # remember it so we do not ask again
            write_json_atomic(out_dir / f"{tmdb_id}.json", {"_not_found": True, "id": tmdb_id})
        return status

    bar = tqdm(total=len(todo), desc=f"TMDB {kind}", unit="req") if tqdm else None
    async with httpx.AsyncClient(headers=headers, timeout=30.0, limits=limits) as client:
        for start in range(0, len(todo), 2000):      # chunks keep memory small
            tasks = [asyncio.create_task(one(i)) for i in todo[start:start + 2000]]
            for finished in asyncio.as_completed(tasks):
                stats[await finished] += 1
                if bar:
                    bar.update(1)
    if bar:
        bar.close()
    log(f"{kind}: fetched {stats['ok']:,}, not found {stats['not_found']:,}, failed {stats['failed']:,}"
        + (" (re-run later to retry the failed ones)" if stats["failed"] else ""))
    return stats


async def discover_tv_ids(auth) -> list[int]:
    """Collect series ids from the popular / top-rated lists (+ discover by origin country)."""
    headers, base_params = auth
    limiter = RateLimiter(config.TMDB_RATE_LIMIT)
    semaphore = asyncio.Semaphore(config.TMDB_CONCURRENCY)
    requests = []
    for list_name in ("popular", "top_rated"):
        for page in range(1, config.TMDB_TV_PAGES + 1):
            requests.append((f"{config.TMDB_BASE_URL}/tv/{list_name}",
                             {**base_params, "page": page, "language": config.TMDB_LANGUAGE}))
    for country in [c.strip() for c in config.TMDB_TV_DISCOVER_COUNTRIES.split(",") if c.strip()]:
        for page in range(1, config.TMDB_TV_DISCOVER_PAGES + 1):
            requests.append((f"{config.TMDB_BASE_URL}/discover/tv",
                             {**base_params, "page": page, "with_origin_country": country,
                              "sort_by": "popularity.desc", "vote_count.gte": config.TMDB_MIN_SERIES_VOTES,
                              "language": config.TMDB_LANGUAGE}))
    ids: set[int] = set()
    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        results = await asyncio.gather(*[get_json(client, url, params, limiter, semaphore)
                                         for url, params in requests])
    for status, data in results:
        if status == "ok":
            ids.update(int(item["id"]) for item in data.get("results", []))
    # Keep ids found in earlier runs too, so the catalog never shrinks between runs
    id_file = config.TMDB_RAW_DIR / "tv_ids.json"
    ids.update(load_json(id_file, []))
    save_json(id_file, sorted(ids))
    log(f"Series list: {len(ids):,} TV ids ({len(requests)} list pages requested)")
    return sorted(ids)


# ----------------------------------------------------------------------------------------------
# Popularity snapshot
# ----------------------------------------------------------------------------------------------
def save_popularity_snapshot(movie_ids: set[int], tv_ids: set[int]) -> None:
    """Write data/raw/tmdb/snapshots/popularity_YYYYMMDD.csv.

    Preferred source: TMDB's daily export files (one download each, no API key needed) which
    hold the current popularity of EVERY title. If they cannot be downloaded, fall back to the
    popularity inside JSON files fetched in the last 2 days (older cached values are stale).
    """
    config.SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for back in range(3):                          # exports appear ~08:00 UTC, try earlier days
        day = datetime.now(timezone.utc).date() - timedelta(days=back)
        target = config.SNAPSHOT_DIR / f"popularity_{day:%Y%m%d}.csv"
        if target.exists():
            log(f"Popularity snapshot for {day} already exists")
            return
        try:
            for kind, wanted, content_type in (("movie", movie_ids, "movie"), ("tv_series", tv_ids, "series")):
                url = f"{config.TMDB_EXPORT_URL}/{kind}_ids_{day:%m_%d_%Y}.json.gz"
                with httpx.Client(timeout=120.0, follow_redirects=True) as client:
                    response = client.get(url)
                response.raise_for_status()
                for line in gzip.decompress(response.content).splitlines():
                    item = json.loads(line)
                    if item.get("id") in wanted:
                        rows.append((content_type, item["id"], item.get("popularity", 0.0)))
            log(f"Downloaded TMDB daily export for {day}")
            break
        except Exception as error:                 # not published yet / offline -> try next
            rows = []
            last_error = error
    else:
        warn(f"Could not download TMDB daily export ({last_error}); using recently fetched JSON instead")
        day = datetime.now(timezone.utc).date()
        cutoff = time.time() - 2 * 86_400
        for content_type, folder, wanted in (("movie", "movie", movie_ids), ("series", "tv", tv_ids)):
            for tmdb_id in wanted:
                path = config.TMDB_RAW_DIR / folder / f"{tmdb_id}.json"
                if path.exists() and path.stat().st_mtime >= cutoff:
                    data = load_json(path, {})
                    if "popularity" in data:
                        rows.append((content_type, tmdb_id, data["popularity"]))
    if not rows:
        warn("No fresh popularity values - snapshot skipped (velocity falls back to MovieLens)")
        return
    snap = pd.DataFrame(rows, columns=["content_type", "tmdb_id", "popularity"]).drop_duplicates()
    snap.to_csv(config.SNAPSHOT_DIR / f"popularity_{day:%Y%m%d}.csv", index=False)
    n_snaps = len(list(config.SNAPSHOT_DIR.glob("popularity_*.csv")))
    log(f"Saved popularity snapshot ({len(snap):,} titles); {n_snaps} snapshot(s) on disk")


# ----------------------------------------------------------------------------------------------
# Parsing the cached JSON into one table
# ----------------------------------------------------------------------------------------------
def map_genres(tmdb_genres: list[str]) -> str:
    out = []
    for name in tmdb_genres:
        out.extend(TMDB_TO_ML_GENRES.get(name, []))
    return join_list(sorted(set(out), key=config.GENRES.index))


def pick_trailer(videos: dict) -> str:
    """YouTube trailer key: official trailers first, then the most viewed size, then oldest."""
    found = [v for v in (videos or {}).get("results", [])
             if v.get("site") == "YouTube" and v.get("type") == "Trailer" and v.get("key")]
    found.sort(key=lambda v: (not v.get("official", False), -(v.get("size") or 0), v.get("published_at", "")))
    return found[0]["key"] if found else ""


def movie_certifications(release_dates: dict) -> str:
    """'IN:UA|US:PG-13' - for each country prefer the theatrical (type 3) certificate."""
    out = []
    by_country = {r.get("iso_3166_1"): r.get("release_dates", []) for r in (release_dates or {}).get("results", [])}
    for country in CERT_COUNTRIES:
        dates = sorted(by_country.get(country, []), key=lambda d: (d.get("type") != 3, d.get("type", 9)))
        cert = next((d.get("certification", "").strip() for d in dates if d.get("certification", "").strip()), "")
        if cert:
            out.append(f"{country}:{cert}")
    return "|".join(out)


def tv_certifications(content_ratings: dict) -> str:
    ratings = {r.get("iso_3166_1"): (r.get("rating") or "").strip()
               for r in (content_ratings or {}).get("results", [])}
    return "|".join(f"{c}:{ratings[c]}" for c in CERT_COUNTRIES if ratings.get(c))


def _year(text) -> int | None:
    return int(text[:4]) if text and len(text) >= 4 and text[:4].isdigit() else None


def _people(credits: dict) -> str:
    cast = sorted((credits or {}).get("cast", []), key=lambda c: c.get("order", 999))
    return join_list((c.get("name") for c in cast), limit=5)


def parse_movie(data: dict) -> dict:
    crew = (data.get("credits") or {}).get("crew", [])
    tmdb_genres = [g["name"] for g in data.get("genres", [])]
    collection = data.get("belongs_to_collection") or {}
    return {
        "content_type": "movie", "tmdb_id": data["id"], "imdb_id": data.get("imdb_id") or "",
        "title": data.get("title") or "", "original_title": data.get("original_title") or "",
        "year": _year(data.get("release_date")), "overview": data.get("overview") or "",
        "poster_path": data.get("poster_path") or "", "backdrop_path": data.get("backdrop_path") or "",
        "runtime": data.get("runtime") or None, "seasons": None,
        "original_language": data.get("original_language") or "",
        "genres": map_genres(tmdb_genres), "tmdb_genres": join_list(tmdb_genres),
        "certifications": movie_certifications(data.get("release_dates")),
        "directors": join_list(c["name"] for c in crew if c.get("job") == "Director"),
        "cast": _people(data.get("credits")),
        "keywords": join_list(k["name"].lower() for k in (data.get("keywords") or {}).get("keywords", [])),
        "collection_name": collection.get("name") or "",
        "tmdb_popularity": data.get("popularity"), "tmdb_vote_avg": data.get("vote_average"),
        "tmdb_vote_count": data.get("vote_count"), "trailer_key": pick_trailer(data.get("videos")),
    }


def parse_tv(data: dict) -> dict:
    runtimes = [r for r in data.get("episode_run_time") or [] if r]
    runtime = int(statistics.median(runtimes)) if runtimes else (
        (data.get("last_episode_to_air") or {}).get("runtime") or None)
    creators = [c["name"] for c in data.get("created_by", [])]
    if not creators:                                # some shows list no creator
        creators = [c["name"] for c in (data.get("credits") or {}).get("crew", [])
                    if c.get("job") in ("Director", "Series Director")]
    tmdb_genres = [g["name"] for g in data.get("genres", [])]
    return {
        "movie_id": config.SERIES_ID_OFFSET + int(data["id"]),
        "content_type": "series", "tmdb_id": data["id"],
        "imdb_id": (data.get("external_ids") or {}).get("imdb_id") or "",
        "title": data.get("name") or "", "original_title": data.get("original_name") or "",
        "year": _year(data.get("first_air_date")), "overview": data.get("overview") or "",
        "poster_path": data.get("poster_path") or "", "backdrop_path": data.get("backdrop_path") or "",
        "runtime": runtime, "seasons": data.get("number_of_seasons"),
        "original_language": data.get("original_language") or "",
        "genres": map_genres(tmdb_genres), "tmdb_genres": join_list(tmdb_genres),
        "certifications": tv_certifications(data.get("content_ratings")),
        "directors": join_list(creators, limit=4), "cast": _people(data.get("credits")),
        "keywords": join_list(k["name"].lower() for k in (data.get("keywords") or {}).get("results", [])),
        "collection_name": "",
        "tmdb_popularity": data.get("popularity"), "tmdb_vote_avg": data.get("vote_average"),
        "tmdb_vote_count": data.get("vote_count"), "trailer_key": pick_trailer(data.get("videos")),
    }


def parse_cache(movies: pd.DataFrame, tv_ids: list[int]) -> pd.DataFrame:
    """Read every cached JSON we need and build the tmdb_meta table (keyed by movie_id)."""
    rows = []
    links = movies.dropna(subset=["tmdb_id"])[["movieId", "tmdb_id"]]
    tmdb_to_movies: dict[int, list[int]] = {}
    for movie_id, tmdb_id in zip(links["movieId"], links["tmdb_id"]):
        tmdb_to_movies.setdefault(int(tmdb_id), []).append(int(movie_id))   # a few ids are shared

    log(f"Parsing cached JSON for {len(tmdb_to_movies):,} movies and {len(tv_ids):,} series")
    for tmdb_id, movie_ids in tmdb_to_movies.items():
        data = load_json(config.TMDB_RAW_DIR / "movie" / f"{tmdb_id}.json")
        if not data or data.get("_not_found"):
            continue
        row = parse_movie(data)
        for movie_id in movie_ids:
            rows.append({**row, "movie_id": movie_id})
    for tmdb_id in tv_ids:
        data = load_json(config.TMDB_RAW_DIR / "tv" / f"{tmdb_id}.json")
        if data and not data.get("_not_found"):
            rows.append(parse_tv(data))
    return pd.DataFrame(rows, columns=TMDB_META_COLUMNS)


def sample_metadata() -> pd.DataFrame:
    """--sample: the demo dataset already contains the parsed fields (no network)."""
    meta = load_json(config.SAMPLE_DIR / "metadata.json")
    if meta is None:
        fail("ml/sample_data/metadata.json not found -> run: python make_sample_data.py")
    df = pd.DataFrame(meta["items"])
    df["original_title"] = df["title"]
    df["tmdb_genres"] = ""
    log(f"Loaded demo metadata for {len(df):,} titles (no network used)")
    return df[TMDB_META_COLUMNS]


def save_table(df: pd.DataFrame, out_dir: Path) -> None:
    for col in ("tmdb_id", "year", "runtime", "seasons", "tmdb_vote_count"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in ("tmdb_popularity", "tmdb_vote_avg"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    df["movie_id"] = df["movie_id"].astype("int64")
    text_cols = [c for c in TMDB_META_COLUMNS if df[c].dtype == object or str(df[c].dtype) in ("str", "string")]
    df[text_cols] = df[text_cols].fillna("")
    df.to_parquet(out_dir / "tmdb_meta.parquet", index=False)
    counts = df["content_type"].value_counts().to_dict()
    log(f"Saved {out_dir / 'tmdb_meta.parquet'}: {counts.get('movie', 0):,} movies, "
        f"{counts.get('series', 0):,} series")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Step 2 - fetch TMDB metadata (cached, resumable)")
    parser.add_argument("--sample", action="store_true", help="use bundled demo metadata (offline)")
    parser.add_argument("--skip-tv", action="store_true", help="do not fetch TV series")
    parser.add_argument("--limit", type=int, default=0, help="only fetch the first N movies (testing)")
    parser.add_argument("--parse-only", action="store_true", help="do not call the API, just parse the cache")
    args = parser.parse_args(argv)

    banner("Step 2/9 - Fetch TMDB metadata")
    out_dir = config.processed_dir(args.sample)
    if args.sample:
        save_table(sample_metadata(), out_dir)
        return

    movies_path = out_dir / "movies.parquet"
    if not movies_path.exists():
        fail(f"{movies_path} not found -> run step1_prepare_movielens.py first")
    movies = pd.read_parquet(movies_path)
    movie_ids = [int(x) for x in movies["tmdb_id"].dropna().unique()]
    if args.limit:
        movie_ids = movie_ids[: args.limit]
    tv_ids = load_json(config.TMDB_RAW_DIR / "tv_ids.json", [])

    auth = tmdb_auth()
    if args.parse_only:
        log("--parse-only: no API calls")
    elif auth is None:
        warn("No TMDB_API_KEY / TMDB_READ_TOKEN in .env - skipping downloads.\n"
             "          Get a free key at https://www.themoviedb.org/settings/api and re-run this step.\n"
             "          (The pipeline still works: the catalog just has no posters/overviews.)")
    elif httpx is None:
        fail("httpx is not installed -> pip install -r requirements.txt")
    else:
        try:
            log(f"Using TMDB {'bearer token' if 'Authorization' in auth[0] else 'api_key'} auth")
            asyncio.run(fetch_details("movie", movie_ids, auth, config.TMDB_RAW_DIR / "movie"))
            if not args.skip_tv:
                tv_ids = asyncio.run(discover_tv_ids(auth))
                asyncio.run(fetch_details("tv", tv_ids, auth, config.TMDB_RAW_DIR / "tv"))
            save_popularity_snapshot(set(movie_ids), set(tv_ids))
        except AuthError as error:
            fail(str(error))
        except KeyboardInterrupt:
            fail("Interrupted - everything fetched so far is cached. Run the step again to resume.", 130)

    if args.skip_tv:
        tv_ids = []
    save_table(parse_cache(movies, tv_ids), out_dir)


if __name__ == "__main__":
    main()
