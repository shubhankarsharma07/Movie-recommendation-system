"""
retrain.py - scheduled retraining with the app's own data (NFR-4, design decision D2).

What it does
  1. Reads the app database (DATABASE_URL; tables from CONTRACT section 3) with SQLAlchemy:
        ratings           -> explicit ratings (0.5 - 5.0)
        playback_sessions -> viewing behaviour, turned into PSEUDO-ratings (rules below)
  2. Merges them with the cached MovieLens ratings (app users get ids 1,000,000,000 + n, a
     "prefix" that can never clash with MovieLens user ids).
  3. Re-runs  step7 (train) -> step8 (blend) -> step9 (export)  re-using the cached catalog,
     embeddings and emotions (steps 1-6 are NOT repeated - they do not depend on app data).
  4. On ANY error: prints it, exits with code 1 and leaves backend/artifacts/current.txt alone,
     so the backend keeps serving the last good model (NFR-4).

Behaviour -> pseudo-rating rules (only for user+title pairs WITHOUT an explicit rating):
    rewatched it (is_rewatch on any session)                    -> 4.5
    watched >= 90%  (completed, or drop_off_sec / duration_sec >= 0.9) -> 4.0
    stopped before 15% of the runtime                           -> 2.0
    anything in between                                         -> no pseudo-rating (ambiguous)

Which data folder? The mode (demo "sample" or "full") is taken from the live model's
model_meta.json (dataset_mode), so the admin "Retrain" button works for both. Override with
--sample / --full. If the processed cache is missing (e.g. on GitHub Actions) the catalog,
embeddings and emotions are rebuilt from the live artifact folder; MovieLens ratings must
still be prepared once with step1 (see README_ML.md for a GitHub Actions example).

Usage:  python ml/retrain.py            (from anywhere; the backend admin panel calls this)
        python ml/retrain.py --tune     (also re-run the SVD grid search)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

import config
from utils import banner, load_json, log, save_json, warn

LOCK_MAX_AGE_HOURS = 6


# ----------------------------------------------------------------------------------------------
# Database
# ----------------------------------------------------------------------------------------------
def normalise_db_url(url: str) -> str:
    """postgres:// (Heroku/Render style) -> postgresql+psycopg:// (SQLAlchemy 2 + psycopg 3)."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def resolve_sqlite(url: str) -> str | None:
    """sqlite:///./cinematch.db is relative to wherever the backend runs; look in the usual places."""
    path_text = url[len("sqlite:///"):]
    path = Path(path_text)
    if path.is_absolute():
        return url if path.exists() else None
    for base in (Path.cwd(), config.REPO_ROOT / "backend", config.REPO_ROOT):
        candidate = (base / path).resolve()
        if candidate.exists():
            return f"sqlite:///{candidate}"
    return None


def _to_epoch(values: pd.Series) -> pd.Series:
    times = pd.to_datetime(values, utc=True, errors="coerce", format="mixed")
    now = pd.Timestamp.now(tz="UTC")
    return ((times.fillna(now) - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(seconds=1)).astype("int64")


def pseudo_ratings(sessions: pd.DataFrame) -> pd.DataFrame:
    """Turn playback sessions into pseudo-ratings using the rules in the module docstring."""
    if sessions.empty:
        return pd.DataFrame(columns=["user_id", "movie_id", "rating", "timestamp", "source"])
    s = sessions.copy()
    duration = pd.to_numeric(s["duration_sec"], errors="coerce")
    drop_off = pd.to_numeric(s["drop_off_sec"], errors="coerce")
    ratio = (drop_off / duration).where(duration > 0)
    completed = s["completed"].fillna(False).astype(bool)
    s["completion"] = ratio.where(~completed, 1.0).clip(0, 1)
    s["is_rewatch"] = s["is_rewatch"].fillna(False).astype(bool)
    s["timestamp"] = _to_epoch(s["started_at"])
    g = s.groupby(["user_id", "movie_id"]).agg(completion=("completion", "max"), rewatch=("is_rewatch", "any"),
                                               timestamp=("timestamp", "max")).reset_index()
    g["rating"], g["source"] = np.nan, ""
    rules = [  # (condition, rating, label) - first matching rule wins
        (g["rewatch"], config.PSEUDO_REWATCH, "pseudo_rewatch"),
        (g["completion"] >= 0.9, config.PSEUDO_COMPLETED, "pseudo_completed"),
        (g["completion"] < 0.15, config.PSEUDO_EARLY_DROP, "pseudo_early_drop"),
    ]
    for condition, rating, label in reversed(rules):            # reversed so earlier rules overwrite later
        g.loc[condition.fillna(False), ["rating", "source"]] = [rating, label]
    return g.dropna(subset=["rating"])[["user_id", "movie_id", "rating", "timestamp", "source"]]


def load_app_ratings(database_url: str | None = None) -> pd.DataFrame:
    """Explicit + pseudo ratings from the app DB as userId/movieId/rating/timestamp/source."""
    from sqlalchemy import create_engine, text

    empty = pd.DataFrame({"userId": pd.Series(dtype="int32"), "movieId": pd.Series(dtype="int32"),
                          "rating": pd.Series(dtype="float32"), "timestamp": pd.Series(dtype="int64"),
                          "source": pd.Series(dtype="str")})
    explicit_setting = database_url or os.getenv("DATABASE_URL", "").strip()
    url = normalise_db_url(explicit_setting or config.DATABASE_URL)
    if url.startswith("sqlite:///"):
        resolved = resolve_sqlite(url)
        if resolved is None:
            if explicit_setting:
                raise FileNotFoundError(f"SQLite database not found for DATABASE_URL={explicit_setting}")
            warn("No app database found (DATABASE_URL not set, no cinematch.db) - using MovieLens data only")
            return empty
        url = resolved
    safe = url.split("@")[-1] if "@" in url else url                 # never print passwords
    log(f"Reading app data from {safe}")

    engine = create_engine(url)
    with engine.connect() as conn:
        ratings = pd.read_sql(text("SELECT user_id, movie_id, rating, created_at FROM ratings"), conn)
        sessions = pd.read_sql(text(
            "SELECT user_id, movie_id, started_at, drop_off_sec, duration_sec, completed, is_rewatch "
            "FROM playback_sessions"), conn)
    engine.dispose()

    for df in (ratings, sessions):
        df["user_id"] = df["user_id"].astype(str)
        df["movie_id"] = pd.to_numeric(df["movie_id"], errors="coerce")
    ratings = ratings.dropna(subset=["movie_id"])
    explicit = pd.DataFrame({
        "user_id": ratings["user_id"], "movie_id": ratings["movie_id"].astype("int64"),
        "rating": pd.to_numeric(ratings["rating"].astype(str), errors="coerce"),
        "timestamp": _to_epoch(ratings["created_at"]), "source": "explicit"}).dropna(subset=["rating"])
    explicit = explicit[explicit["rating"].between(0.5, 5.0)]

    pseudo = pseudo_ratings(sessions.dropna(subset=["movie_id"]).astype({"movie_id": "int64"}))
    if not pseudo.empty:                       # explicit rating always wins over behaviour
        rated = set(zip(explicit["user_id"], explicit["movie_id"]))
        pseudo = pseudo[[pair not in rated for pair in zip(pseudo["user_id"], pseudo["movie_id"])]]
    app = pd.concat([explicit, pseudo], ignore_index=True)
    if app.empty:
        log("App database has no ratings or usable playback sessions yet")
        return empty

    # "Prefix" app users: UUID strings -> integer ids starting at 1,000,000,000
    users = sorted(app["user_id"].unique())
    user_ids = {u: config.APP_USER_ID_OFFSET + k for k, u in enumerate(users)}
    out = pd.DataFrame({
        "userId": app["user_id"].map(user_ids).astype("int32"), "movieId": app["movie_id"].astype("int32"),
        "rating": app["rating"].astype("float32"), "timestamp": app["timestamp"].astype("int64"),
        "source": app["source"].astype(str)})
    counts = out["source"].value_counts().to_dict()
    log("App ratings by source: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return out


# ----------------------------------------------------------------------------------------------
# Re-using the cached catalog (or rebuilding it from the live artifact)
# ----------------------------------------------------------------------------------------------
def live_version() -> str | None:
    pointer = config.ARTIFACTS_DIR / "current.txt"
    return pointer.read_text(encoding="utf-8").strip() if pointer.exists() else None


def detect_sample_mode(args) -> bool:
    if args.sample or args.full:
        return bool(args.sample)
    version = live_version()
    meta = load_json(config.ARTIFACTS_DIR / version / "model_meta.json", {}) if version else {}
    mode = meta.get("dataset_mode", "full")
    log(f"Live model {version or '(none)'} has dataset_mode={mode}")
    return mode == "sample"


def bootstrap_from_artifact(out_dir: Path) -> None:
    """Recreate catalog_base / emotions / embeddings from the live artifact if the cache is missing."""
    needed = ["catalog_base.parquet", "emotions.parquet", "plot_emb.npy", "plot_emb_ids.npy"]
    if all((out_dir / n).exists() for n in needed):
        return
    version = live_version()
    if not version or not (config.ARTIFACTS_DIR / version / "catalog.csv").exists():
        raise FileNotFoundError("No cached catalog and no live artifact to rebuild it from - run run_all.py first")
    folder = config.ARTIFACTS_DIR / version
    log(f"Processed cache missing -> rebuilding catalog/embeddings/emotions from live artifact {version}")
    cat = pd.read_csv(folder / "catalog.csv", dtype=str, keep_default_na=False)
    for col in config.INT_COLUMNS:
        cat[col] = pd.to_numeric(cat[col].replace("", np.nan)).astype("Int64")
    for col in config.FLOAT_COLUMNS:
        cat[col] = pd.to_numeric(cat[col].replace("", np.nan)).astype("float64")
    cat["ml_rating_count"] = cat["ml_rating_count"].fillna(0).astype("int64")
    emotions = cat[["movie_id", "start_emotion", "end_emotion", "emotion_arc"]].assign(emotion_mood_tags="")
    emotions["movie_id"] = emotions["movie_id"].astype("int64")
    base = cat.drop(columns=["start_emotion", "end_emotion", "emotion_arc"]).assign(
        ml_tags="", velocity_source="artifact", ml_velocity=0.0, metascore=np.nan, rt_score=np.nan)
    base["movie_id"] = base["movie_id"].astype("int64")
    base.to_parquet(out_dir / "catalog_base.parquet", index=False)
    emotions.to_parquet(out_dir / "emotions.parquet", index=False)
    np.save(out_dir / "plot_emb.npy", np.load(folder / "plot_emb.npy"))
    np.save(out_dir / "plot_emb_ids.npy", base["movie_id"].to_numpy(np.int64))
    np.save(out_dir / "has_emb.npy", np.load(folder / "has_emb.npy"))
    meta = load_json(folder / "model_meta.json", {})
    save_json(out_dir / "embedding_info.json", {"model": meta.get("embedding_model", "unknown")})
    save_json(out_dir / "emotion_info.json", {"model": meta.get("emotion_model", "unknown")})


def run_step(script: str, flags: list[str]) -> None:
    command = [sys.executable, str(config.ML_DIR / script), *flags]
    log("Running: " + " ".join(Path(c).name if i < 2 else c for i, c in enumerate(command)))
    result = subprocess.run(command, cwd=config.ML_DIR, env={**os.environ, "PYTHONUNBUFFERED": "1"})
    if result.returncode != 0:
        raise RuntimeError(f"{script} failed with exit code {result.returncode}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Retrain the model with in-app ratings + behaviour")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--sample", action="store_true", help="retrain the demo-data model")
    mode.add_argument("--full", action="store_true", help="retrain the full MovieLens model")
    parser.add_argument("--tune", action="store_true", help="also re-run the SVD grid search")
    parser.add_argument("--no-app-data", action="store_true", help="retrain on MovieLens only")
    args = parser.parse_args(argv)

    banner("CineMatch retraining")
    start = time.time()
    previous = live_version()
    lock = config.ARTIFACTS_DIR / ".retrain.lock"
    try:
        config.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        if lock.exists() and time.time() - lock.stat().st_mtime < LOCK_MAX_AGE_HOURS * 3600:
            raise RuntimeError(f"another retraining seems to be running ({lock} exists) - try again later")
        lock.write_text(str(os.getpid()), encoding="utf-8")

        sample = detect_sample_mode(args)
        out_dir = config.processed_dir(sample)
        if not (out_dir / "ratings.parquet").exists():
            raise FileNotFoundError(f"{out_dir / 'ratings.parquet'} missing - run step1_prepare_movielens.py"
                                    f"{' --sample' if sample else ''} once first")
        bootstrap_from_artifact(out_dir)
        if not args.no_app_data:
            load_app_ratings()        # fail fast here if the database is unreachable (step7 reads it again)
        flags = ["--sample"] if sample else []
        run_step("step7_train.py", flags + ([] if args.no_app_data else ["--with-app-data"])
                 + (["--tune"] if args.tune else []))
        run_step("step8_tune_blend.py", flags)
        run_step("step9_export.py", flags)
    except Exception as error:
        print(f"\n[ RETRAIN FAILED ] {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        print(f"current.txt was NOT changed - the backend keeps serving {previous or '(no model yet)'}",
              file=sys.stderr, flush=True)
        return 1
    finally:
        if lock.exists() and lock.read_text(encoding="utf-8").strip() == str(os.getpid()):
            lock.unlink()
    log(f"Retraining finished in {time.time() - start:.0f}s: {previous} -> {live_version()}")
    log("Tell the backend to load it: POST /api/admin/reload-model (or restart the server)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
