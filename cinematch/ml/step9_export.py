"""
step9_export.py - write a new model version for the backend (CONTRACT section 2).

Creates backend/artifacts/<version>/ (version = v%Y%m%d_%H%M%S, UTC) containing
    catalog.csv        one row per title, CONTRACT columns in CONTRACT order
    item_factors.npy   float32 [N, k]  SVD item factors (zeros where the title has no CF data)
    item_bias.npy      float32 [N]     SVD item bias
    has_cf.npy         bool    [N]
    plot_emb.npy       float16 [N, d]  L2-normalised content embedding (zeros if missing)
    has_emb.npy        bool    [N]
    model_meta.json    settings, metrics, blend weights, data sources, dataset_mode
Row i of catalog.csv == index i of every .npy file.

Safety (NFR-4 "keep serving the last good model"):
    1. everything is written into a hidden temp folder first,
    2. the folder is VALIDATED (columns, vocabularies, shapes, dtypes, alignment, no NaN),
    3. only then renamed to its final name, and
    4. current.txt is replaced atomically (write current.txt.tmp, then os.replace).
If any check fails the script exits with an error and current.txt still points to the old version.
Finally only the newest 3 versions are kept (the live one is never deleted).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import config
from utils import banner, clean_text, fail, join_list, load_json, log, save_json, split_list

VERSION_RE = re.compile(r"^v\d{8}_\d{6}$")
KEEP_VERSIONS = 3
ROUNDING = {"ml_rating_mean": 3, "tmdb_popularity": 3, "tmdb_vote_avg": 2, "imdb_rating": 1, "critic_score": 1,
            "popularity_score": 4, "trending_velocity": 4, "quality_score": 4}
REQUIRED_META = ["version", "trained_at", "algorithm", "n_factors", "global_mean", "fold_in_reg", "n_items",
                 "n_cf_items", "embedding_model", "emotion_model", "metrics", "blend_weights", "data_sources",
                 "dataset_mode"]


# ----------------------------------------------------------------------------------------------
# Building the files
# ----------------------------------------------------------------------------------------------
def final_catalog(out_dir: Path) -> pd.DataFrame:
    cat = pd.read_parquet(out_dir / "catalog_base.parquet")
    emotions_path = out_dir / "emotions.parquet"
    if emotions_path.exists():
        cat = cat.merge(pd.read_parquet(emotions_path), on="movie_id", how="left")
    else:
        log("emotions.parquet not found (step6 skipped?) -> neutral/steady for every title")
    cat["start_emotion"] = cat.get("start_emotion", pd.Series(dtype=str)).fillna("neutral")
    cat["end_emotion"] = cat.get("end_emotion", pd.Series(dtype=str)).fillna("neutral")
    cat["emotion_arc"] = cat.get("emotion_arc", pd.Series(dtype=str)).fillna("steady")
    extra_tags = cat.get("emotion_mood_tags", pd.Series("", index=cat.index)).fillna("")
    cat["mood_tags"] = [join_list(t for t in config.MOOD_TAGS if t in set(split_list(a)) | set(split_list(b)))
                        for a, b in zip(cat["mood_tags"], extra_tags)]

    for col in config.CATALOG_COLUMNS:
        if col in config.INT_COLUMNS:
            cat[col] = pd.to_numeric(cat[col], errors="coerce").round().astype("Int64")
        elif col in config.FLOAT_COLUMNS:
            cat[col] = pd.to_numeric(cat[col], errors="coerce").astype("float64").round(ROUNDING.get(col, 4))
        else:
            cat[col] = cat[col].map(clean_text)          # single line, '' for missing
    for col in ("popularity_score", "trending_velocity", "quality_score"):   # never empty (CONTRACT: float)
        cat[col] = cat[col].fillna(0.0)
    cat["ml_rating_count"] = cat["ml_rating_count"].fillna(0)
    return cat[config.CATALOG_COLUMNS].reset_index(drop=True)


def aligned_cf(out_dir: Path, movie_ids: np.ndarray):
    model = np.load(out_dir / "cf_model.npz")
    pos = pd.Index(model["item_ids"]).get_indexer(movie_ids)
    has_cf = pos >= 0
    factors = np.zeros((len(movie_ids), model["qi"].shape[1]), dtype=np.float32)
    bias = np.zeros(len(movie_ids), dtype=np.float32)
    factors[has_cf] = model["qi"][pos[has_cf]]
    bias[has_cf] = model["bi"][pos[has_cf]]
    return factors, bias, has_cf, float(model["global_mean"])


def aligned_embeddings(out_dir: Path, movie_ids: np.ndarray):
    if not (out_dir / "plot_emb.npy").exists():
        log("plot_emb.npy not found (step5 skipped?) -> zero embeddings")
        return np.zeros((len(movie_ids), 1), dtype=np.float16), np.zeros(len(movie_ids), dtype=bool)
    emb = np.load(out_dir / "plot_emb.npy")
    ids = np.load(out_dir / "plot_emb_ids.npy")
    has = np.load(out_dir / "has_emb.npy") if (out_dir / "has_emb.npy").exists() else np.ones(len(ids), bool)
    pos = pd.Index(ids).get_indexer(movie_ids)
    found = pos >= 0
    out = np.zeros((len(movie_ids), emb.shape[1]), dtype=np.float16)
    out[found] = emb[pos[found]]
    has_emb = np.zeros(len(movie_ids), dtype=bool)
    has_emb[found] = has[pos[found]]
    out[~has_emb] = 0
    return out, has_emb


def data_sources(out_dir: Path, sample: bool, cf_meta: dict) -> list[str]:
    if sample:
        sources = ["CineMatch demo dataset (synthetic ratings, hand-written metadata)"]
    else:
        info = load_json(out_dir / "movielens_info.json", {})
        sources = [info.get("name", "MovieLens")]
        tmdb = out_dir / "tmdb_meta.parquet"
        if tmdb.exists() and len(pd.read_parquet(tmdb, columns=["movie_id"])):
            sources.append("TMDB API")
        scores = out_dir / "scores.parquet"
        if scores.exists():
            sc = pd.read_parquet(scores)
            if sc["imdb_rating"].notna().any():
                sources.append("IMDb non-commercial datasets")
            if sc[["metascore", "rt_score"]].notna().any().any():
                sources.append("OMDb API")
    if cf_meta.get("with_app_data"):
        sources.append("CineMatch in-app ratings + behaviour")
    return sources


def build_meta(version, out_dir, sample, catalog, has_cf, emb, global_mean) -> dict:
    cf_meta = load_json(out_dir / "cf_meta.json", {})
    metrics = load_json(out_dir / "metrics.json", {})
    blend = load_json(out_dir / "blend.json", {})
    rp, rk = metrics.get("rating_prediction", {}), metrics.get("ranking", {})
    check = blend.get("metrics", {}).get("check", {})
    chosen_blend = check.get("blend_tuned" if blend.get("chosen") == "tuned" else "blend_default", {})
    return {
        "version": version,
        "trained_at": cf_meta.get("trained_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "algorithm": cf_meta.get("algorithm", "SVD (Surprise, biased matrix factorisation)"),
        "n_factors": int(cf_meta.get("n_factors", 0)), "n_epochs": int(cf_meta.get("n_epochs", 0)),
        "lr_all": cf_meta.get("lr_all"), "reg_all": cf_meta.get("reg_all"),
        "global_mean": round(global_mean, 4), "fold_in_reg": config.FOLD_IN_REG,
        "n_items": int(len(catalog)), "n_cf_items": int(has_cf.sum()),
        "n_train_ratings": int(cf_meta.get("n_train_ratings", 0)),
        "n_users_trained": int(cf_meta.get("n_users_trained", 0)),
        "embedding_model": load_json(out_dir / "embedding_info.json", {}).get("model", "none"),
        "embedding_dim": int(emb.shape[1]),
        "emotion_model": load_json(out_dir / "emotion_info.json", {}).get("model", "none"),
        "metrics": {
            "rmse": rp.get("svd", {}).get("rmse"), "mae": rp.get("svd", {}).get("mae"),
            "baseline_global_mean_rmse": rp.get("global_mean", {}).get("rmse"),
            "baseline_global_mean_mae": rp.get("global_mean", {}).get("mae"),
            "baseline_bias_rmse": rp.get("baseline_only", {}).get("rmse"),
            "baseline_bias_mae": rp.get("baseline_only", {}).get("mae"),
            "precision_at_10": rk.get("svd", {}).get("precision_at_10"),
            "recall_at_10": rk.get("svd", {}).get("recall_at_10"),
            "ndcg_at_10": rk.get("svd", {}).get("ndcg_at_10"),
            "popularity_precision_at_10": rk.get("popularity", {}).get("precision_at_10"),
            "popularity_recall_at_10": rk.get("popularity", {}).get("recall_at_10"),
            "popularity_ndcg_at_10": rk.get("popularity", {}).get("ndcg_at_10"),
            "blend_precision_at_10": chosen_blend.get("precision_at_10"),
            "blend_recall_at_10": chosen_blend.get("recall_at_10"),
            "blend_ndcg_at_10": chosen_blend.get("ndcg_at_10"),
            "eval_users": rk.get("n_users"), "split": metrics.get("split"),
            "n_test_ratings": metrics.get("n_test"),
        },
        "blend_weights": blend.get("weights", dict(config.DEFAULT_BLEND_WEIGHTS)),
        "blend_formula": blend.get("formula", ""),
        "data_sources": data_sources(out_dir, sample, cf_meta),
        "dataset_mode": "sample" if sample else "full",
        "catalog_counts": catalog["content_type"].value_counts().to_dict(),
        "ratings_sampled": bool(cf_meta.get("sampled", False)),
        "n_ratings_before_sampling": cf_meta.get("n_ratings_before_sampling"),
        "with_app_data": bool(cf_meta.get("with_app_data", False)),
        "app_ratings": cf_meta.get("app_ratings", 0), "app_pseudo_ratings": cf_meta.get("app_pseudo_ratings", 0),
    }


# ----------------------------------------------------------------------------------------------
# Validation - the folder must match the CONTRACT exactly before it can go live
# ----------------------------------------------------------------------------------------------
def validate(folder: Path, version: str | None = None) -> None:
    """Raise ValueError if the folder does not match the CONTRACT. `version` defaults to the folder name."""
    def check(ok, message):
        if not ok:
            raise ValueError(message)

    for name in ("catalog.csv", "item_factors.npy", "item_bias.npy", "has_cf.npy", "plot_emb.npy",
                 "has_emb.npy", "model_meta.json"):
        check((folder / name).exists(), f"missing file {name}")
    cat = pd.read_csv(folder / "catalog.csv", dtype=str, keep_default_na=False, encoding="utf-8")
    n = len(cat)
    check(list(cat.columns) == config.CATALOG_COLUMNS, f"catalog.csv columns differ from CONTRACT: {list(cat.columns)}")
    check(n > 0, "catalog.csv is empty")
    check(cat["movie_id"].str.fullmatch(r"\d+").all() and cat["movie_id"].is_unique, "movie_id must be unique integers")
    for col in config.INT_COLUMNS:
        check(cat[col].str.fullmatch(r"\d*").all(), f"{col} must be an integer or empty")
    for col in config.FLOAT_COLUMNS:
        check(pd.to_numeric(cat[col].replace("", np.nan), errors="coerce").notna().sum()
              == (cat[col] != "").sum(), f"{col} has non-numeric values")
    for col in ("popularity_score", "trending_velocity", "quality_score", "ml_rating_count"):
        check((cat[col] != "").all(), f"{col} must never be empty")
    check(cat["content_type"].isin(["movie", "series"]).all(), "bad content_type")
    series = cat["content_type"] == "series"
    check((cat.loc[series, "movie_id"].astype(np.int64) >= config.SERIES_ID_OFFSET).all(), "series ids must be >= 10,000,000")
    check(cat["age_rating"].isin(config.AGE_RATINGS + [""]).all(), "age_rating outside AGE_RATINGS")
    check(cat["start_emotion"].isin(config.EMOTIONS).all() and cat["end_emotion"].isin(config.EMOTIONS).all(),
          "emotion outside EMOTIONS")
    check(cat["emotion_arc"].isin(config.ARCS).all(), "emotion_arc outside ARCS")
    check(all(set(split_list(t)) <= set(config.MOOD_TAGS) for t in cat["mood_tags"]), "mood tag outside MOOD_TAGS")
    check(all(set(split_list(g)) <= set(config.GENRES) for g in cat["genres"]), "genre outside the MovieLens genres")
    check((cat["title"] != "").all(), "every title needs a name")
    q = pd.to_numeric(cat["quality_score"])
    p = pd.to_numeric(cat["popularity_score"])
    check(q.between(0, 1).all() and p.between(0, 1).all(), "quality_score / popularity_score must be in 0..1")

    factors, bias = np.load(folder / "item_factors.npy"), np.load(folder / "item_bias.npy")
    has_cf, emb, has_emb = np.load(folder / "has_cf.npy"), np.load(folder / "plot_emb.npy"), np.load(folder / "has_emb.npy")
    check(factors.dtype == np.float32 and factors.ndim == 2 and factors.shape[0] == n, f"item_factors must be float32 [{n}, k]")
    check(bias.dtype == np.float32 and bias.shape == (n,), f"item_bias must be float32 [{n}]")
    check(has_cf.dtype == bool and has_cf.shape == (n,), f"has_cf must be bool [{n}]")
    check(emb.dtype == np.float16 and emb.ndim == 2 and emb.shape[0] == n, f"plot_emb must be float16 [{n}, d]")
    check(has_emb.dtype == bool and has_emb.shape == (n,), f"has_emb must be bool [{n}]")
    check(np.isfinite(factors).all() and np.isfinite(bias).all() and np.isfinite(emb.astype(np.float32)).all(),
          "NaN/inf in arrays")
    check(not factors[~has_cf].any() and not bias[~has_cf].any(), "titles without CF data must have zero factors/bias")
    norms = np.linalg.norm(emb.astype(np.float32), axis=1)
    check(np.allclose(norms[has_emb], 1.0, atol=0.02) and not norms[~has_emb].any(), "embeddings must be L2-normalised (or zero)")
    meta = load_json(folder / "model_meta.json", {})
    missing = [k for k in REQUIRED_META if k not in meta]
    check(not missing, f"model_meta.json missing keys {missing}")
    check(meta["n_items"] == n and meta["version"] == (version or folder.name), "model_meta.json does not match the folder")


# ----------------------------------------------------------------------------------------------
# Publishing
# ----------------------------------------------------------------------------------------------
def publish(artifacts_dir: Path, tmp_folder: Path, version: str) -> Path:
    final = artifacts_dir / version
    os.replace(tmp_folder, final)                                   # rename = atomic on one disk
    pointer_tmp = artifacts_dir / "current.txt.tmp"
    pointer_tmp.write_text(version + "\n", encoding="utf-8")
    os.replace(pointer_tmp, artifacts_dir / "current.txt")          # backend switches here
    return final


def prune_old_versions(artifacts_dir: Path, keep: int = KEEP_VERSIONS) -> None:
    current = (artifacts_dir / "current.txt").read_text(encoding="utf-8").strip()
    versions = sorted(p.name for p in artifacts_dir.iterdir() if p.is_dir() and VERSION_RE.match(p.name))
    for name in versions[:-keep]:
        if name != current:
            shutil.rmtree(artifacts_dir / name, ignore_errors=True)
            log(f"Deleted old version {name} (keeping the newest {keep})")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Step 9 - export a validated model version for the backend")
    parser.add_argument("--sample", action="store_true", help="use the demo-data folders")
    args = parser.parse_args(argv)

    banner("Step 9/9 - Export artifacts for the backend")
    start = time.time()
    out_dir = config.processed_dir(args.sample)
    for name, hint in (("catalog_base.parquet", "step4"), ("cf_model.npz", "step7")):
        if not (out_dir / name).exists():
            fail(f"{out_dir / name} not found -> run {hint} first")

    catalog = final_catalog(out_dir)
    movie_ids = catalog["movie_id"].to_numpy(dtype=np.int64)
    factors, bias, has_cf, global_mean = aligned_cf(out_dir, movie_ids)
    emb, has_emb = aligned_embeddings(out_dir, movie_ids)

    artifacts_dir = config.ARTIFACTS_DIR
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    version = datetime.now(timezone.utc).strftime("v%Y%m%d_%H%M%S")
    while (artifacts_dir / version).exists():                      # two exports in the same second
        time.sleep(1)
        version = datetime.now(timezone.utc).strftime("v%Y%m%d_%H%M%S")
    tmp = artifacts_dir / f".tmp_{version}"
    tmp.mkdir()
    try:
        catalog.to_csv(tmp / "catalog.csv", index=False, encoding="utf-8", na_rep="", lineterminator="\n")
        np.save(tmp / "item_factors.npy", factors)
        np.save(tmp / "item_bias.npy", bias)
        np.save(tmp / "has_cf.npy", has_cf)
        np.save(tmp / "plot_emb.npy", emb)
        np.save(tmp / "has_emb.npy", has_emb)
        meta = build_meta(version, out_dir, args.sample, catalog, has_cf, emb, global_mean)
        save_json(tmp / "model_meta.json", meta)
        validate(tmp, version)
        log("Validation passed (columns, vocabularies, dtypes, shapes, alignment, normalisation)")
        final = publish(artifacts_dir, tmp, version)
    except Exception as error:
        shutil.rmtree(tmp, ignore_errors=True)
        fail(f"Export failed, current.txt NOT changed: {error}")

    prune_old_versions(artifacts_dir)
    size_mb = sum(f.stat().st_size for f in final.iterdir()) / 1e6
    log(f"Published {final} ({size_mb:.1f} MB): {len(catalog):,} titles, {int(has_cf.sum()):,} with CF factors, "
        f"{int(has_emb.sum()):,} with embeddings")
    log(f"current.txt -> {version}   (dataset_mode={meta['dataset_mode']})")
    log(f"Step 9 done in {time.time() - start:.1f}s")


if __name__ == "__main__":
    main()
