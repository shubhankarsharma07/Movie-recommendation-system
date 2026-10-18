"""
config.py - every path and setting the ML pipeline uses, in one place.

Settings come from environment variables. The easiest way to set them is a `.env`
file in the repo root (cinematch/.env), which python-dotenv loads automatically.
Nothing secret is written in code: API keys only ever come from the environment.

The vocabularies at the bottom (EMOTIONS, ARCS, MOOD_TAGS, AGE_RATINGS, ...) are copied
from CONTRACT.md section 4. The backend uses exactly the same strings, so do not
rename them here without changing the contract.
"""
from __future__ import annotations

import os
from pathlib import Path

try:  # python-dotenv is in requirements.txt, but do not crash if it is missing
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

# ----------------------------------------------------------------------------------------------
# Folders
# ----------------------------------------------------------------------------------------------
ML_DIR = Path(__file__).resolve().parent          # cinematch/ml
REPO_ROOT = ML_DIR.parent                         # cinematch/

if load_dotenv is not None:
    load_dotenv(REPO_ROOT / ".env")               # silently does nothing if the file is absent


def _env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip().replace("_", "")
    return int(value) if value else default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    return float(value) if value else default


def _env_path(name: str, default: Path) -> Path:
    value = _env_str(name)
    if not value:
        return default
    path = Path(value).expanduser()
    # Relative paths in .env are taken relative to the repo root (not the current folder)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


DATA_DIR = _env_path("CINEMATCH_DATA_DIR", REPO_ROOT / "data")   # never committed (gitignore)
RAW_DIR = DATA_DIR / "raw"
TMDB_RAW_DIR = RAW_DIR / "tmdb"                   # tmdb/movie/{id}.json, tmdb/tv/{id}.json
SNAPSHOT_DIR = TMDB_RAW_DIR / "snapshots"         # popularity_YYYYMMDD.csv
IMDB_RAW_DIR = RAW_DIR / "imdb"                   # title.ratings.tsv.gz
OMDB_RAW_DIR = RAW_DIR / "omdb"                   # {imdb_id}.json

SAMPLE_DIR = ML_DIR / "sample_data"               # bundled demo dataset (made by make_sample_data.py)
ARTIFACTS_DIR = _env_path("ML_ARTIFACTS_DIR", REPO_ROOT / "backend" / "artifacts")

# Where you unzipped MovieLens (ml-25m, ml-32m or ml-latest-small all work)
MOVIELENS_DIR = _env_path("MOVIELENS_DIR", RAW_DIR / "ml-25m")


def processed_dir(sample: bool) -> Path:
    """Folder for the intermediate files of one pipeline run.

    The demo (--sample) run gets its own folder so that it can never overwrite the
    results of a long full MovieLens run (and the other way round).
    """
    folder = DATA_DIR / ("processed_sample" if sample else "processed")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def movielens_dir(sample: bool) -> Path:
    return SAMPLE_DIR if sample else MOVIELENS_DIR


# ----------------------------------------------------------------------------------------------
# API keys (offline enrichment only - the backend never needs these)
# ----------------------------------------------------------------------------------------------
TMDB_API_KEY = _env_str("TMDB_API_KEY")           # v3 key (sent as ?api_key=...)
TMDB_READ_TOKEN = _env_str("TMDB_READ_TOKEN")     # v4 "API Read Access Token" (sent as Bearer header)
OMDB_API_KEY = _env_str("OMDB_API_KEY")           # optional, gives Metascore / Rotten Tomatoes

TMDB_BASE_URL = _env_str("TMDB_BASE_URL", "https://api.themoviedb.org/3")
TMDB_EXPORT_URL = _env_str("TMDB_EXPORT_URL", "https://files.tmdb.org/p/exports")
TMDB_LANGUAGE = _env_str("TMDB_LANGUAGE", "en-US")
TMDB_RATE_LIMIT = _env_float("TMDB_RATE_LIMIT", 35.0)        # requests per second (TMDB allows ~40-50)
TMDB_CONCURRENCY = _env_int("TMDB_CONCURRENCY", 16)          # requests in flight at the same time
TMDB_TV_PAGES = _env_int("TMDB_TV_PAGES", 25)                # pages of popular AND of top-rated series
TMDB_TV_DISCOVER_COUNTRIES = _env_str("TMDB_TV_DISCOVER_COUNTRIES", "IN")  # extra Indian series
TMDB_TV_DISCOVER_PAGES = _env_int("TMDB_TV_DISCOVER_PAGES", 5)
TMDB_MIN_SERIES_VOTES = _env_int("TMDB_MIN_SERIES_VOTES", 20)  # drop obscure series with fewer votes

IMDB_RATINGS_URL = _env_str("IMDB_RATINGS_URL", "https://datasets.imdbws.com/title.ratings.tsv.gz")
IMDB_MAX_AGE_DAYS = _env_int("IMDB_MAX_AGE_DAYS", 7)         # re-download the IMDb file after a week
OMDB_BASE_URL = _env_str("OMDB_BASE_URL", "https://www.omdbapi.com/")
OMDB_DAILY_LIMIT = _env_int("OMDB_DAILY_LIMIT", 900)         # free OMDb key = 1000 calls/day

# ----------------------------------------------------------------------------------------------
# Model / data settings
# ----------------------------------------------------------------------------------------------
SEED = _env_int("SEED", 42)
MIN_RATINGS = _env_int("MIN_RATINGS", 20)                    # keep movies with at least this many ratings
MAX_RATINGS = _env_int("MAX_RATINGS", 8_000_000)             # memory cap for SVD training (whole users kept)
VELOCITY_WINDOW_DAYS = _env_int("VELOCITY_WINDOW_DAYS", 180) # "recent" window for MovieLens velocity

N_FACTORS = _env_int("N_FACTORS", 100)
N_EPOCHS = _env_int("N_EPOCHS", 20)
LR_ALL = _env_float("LR_ALL", 0.005)
REG_ALL = _env_float("REG_ALL", 0.02)
FOLD_IN_REG = _env_float("FOLD_IN_REG", 0.1)                 # used by the backend to fold in new users
# The demo dataset is tiny (50k ratings), so it needs fewer factors and more/faster epochs than
# 25M ratings do (found with step7 --tune). Only used with --sample.
SAMPLE_SVD_PARAMS = {"n_factors": 50, "n_epochs": 40, "lr_all": 0.01, "reg_all": 0.05}

TEST_FRACTION = _env_float("TEST_FRACTION", 0.2)             # latest 20% of each user's ratings = test
RELEVANT_THRESHOLD = _env_float("RELEVANT_THRESHOLD", 4.0)   # a test rating >= 4 counts as "relevant"
TOP_K = _env_int("TOP_K", 10)
EVAL_USERS = _env_int("EVAL_USERS", 2000)                    # users used for precision/recall/NDCG
TUNE_MAX_RATINGS = _env_int("TUNE_MAX_RATINGS", 1_000_000)   # subsample size for --tune

# Behaviour -> pseudo-rating rules used by retrain.py (see the docstring there)
PSEUDO_COMPLETED = 4.0      # watched >= 90%
PSEUDO_REWATCH = 4.5        # watched it again
PSEUDO_EARLY_DROP = 2.0     # stopped before 15%
APP_USER_ID_OFFSET = 1_000_000_000   # in-app users get ids 1e9 + n so they never clash with MovieLens ids

SERIES_ID_OFFSET = 10_000_000        # CONTRACT: series movie_id = 10_000_000 + TMDB tv id
DATABASE_URL = _env_str("DATABASE_URL", "sqlite:///./cinematch.db")

# Blend weights (CONTRACT model_meta.json defaults). step8 tunes cf/content/quality/trend.
DEFAULT_BLEND_WEIGHTS = {
    "cf": 0.45, "content": 0.15, "ref": 0.35, "ctx": 0.25,
    "quality": 0.12, "trend": 0.05, "behavior": 0.10,
}

# ----------------------------------------------------------------------------------------------
# Shared vocabularies - CONTRACT.md section 4 (keep identical to the backend!)
# ----------------------------------------------------------------------------------------------
EMOTIONS = ["joy", "sadness", "fear", "anger", "surprise", "disgust", "neutral"]
POSITIVE_EMOTIONS = {"joy", "surprise"}
NEGATIVE_EMOTIONS = {"sadness", "fear", "anger", "disgust"}
ARCS = ["rise", "fall", "fall-rise", "rise-fall", "steady"]
MOOD_TAGS = ["feel-good", "dark", "cozy", "thrilling", "romantic", "mind-bending", "epic", "heartwarming",
             "scary", "funny", "inspiring", "melancholic", "action-packed", "family", "slow-burn", "light"]
AGE_RATINGS = ["U", "UA 7+", "UA 13+", "UA 16+", "A"]
GENRES = ["Action", "Adventure", "Animation", "Children", "Comedy", "Crime", "Documentary", "Drama",
          "Fantasy", "Film-Noir", "Horror", "IMAX", "Musical", "Mystery", "Romance", "Sci-Fi",
          "Thriller", "War", "Western"]

# catalog.csv columns, in this exact order (CONTRACT section 2)
CATALOG_COLUMNS = [
    "movie_id", "content_type", "tmdb_id", "imdb_id", "title", "year", "genres", "overview",
    "poster_path", "backdrop_path", "runtime", "seasons", "original_language", "age_rating",
    "certification_raw", "directors", "cast", "keywords", "collection_name", "ml_rating_mean",
    "ml_rating_count", "tmdb_popularity", "tmdb_vote_avg", "tmdb_vote_count", "imdb_rating",
    "imdb_votes", "critic_score", "popularity_score", "trending_velocity", "quality_score",
    "start_emotion", "end_emotion", "emotion_arc", "mood_tags", "decade", "trailer_key",
]
LIST_COLUMNS = ["genres", "directors", "cast", "keywords", "mood_tags"]   # pipe-separated in the CSV
INT_COLUMNS = ["movie_id", "tmdb_id", "year", "runtime", "seasons", "ml_rating_count",
               "tmdb_vote_count", "imdb_votes", "decade"]
FLOAT_COLUMNS = ["ml_rating_mean", "tmdb_popularity", "tmdb_vote_avg", "imdb_rating", "critic_score",
                 "popularity_score", "trending_velocity", "quality_score"]
