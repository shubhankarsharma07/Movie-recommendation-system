"""
step7_train.py - train the collaborative-filtering model and measure how good it is.

Model: Surprise SVD = biased matrix factorisation. Every user u and item i get a bias and a
vector of N_FACTORS hidden "taste" numbers; the predicted rating is
        r_hat(u, i) = global_mean + b_u + b_i + q_i . p_u
The backend only needs the ITEM part (q_i, b_i, global_mean): for a new app user it "folds in"
a p_u from that user's own ratings at request time (fold_in_reg in model_meta.json).

Steps
  1. Load ratings (+ in-app ratings and behaviour pseudo-ratings with --with-app-data, see retrain.py).
  2. Memory cap: if there are more than MAX_RATINGS ratings (default 8M), keep a random set of
     WHOLE users up to the cap (logged and flagged in model_meta.json). Surprise keeps every
     rating as a Python object, so 25M ratings would need ~8 GB; 8M fits an 8 GB laptop.
  3. Split: for every user with >= 5 ratings, the LATEST 20% (by timestamp) is the test set.
     This "temporal" split mimics real life: learn from the past, predict the future.
     (Falls back to a random 80/20 split if there are no timestamps.)
  4. Evaluate on the test set:
        Level 0  global mean        - predict the average rating for everything
        Level 1  BaselineOnly       - average + user bias + item bias
        SVD                         - the real model
     RMSE / MAE (rating error), and precision@10 / recall@10 / NDCG@10 for up to EVAL_USERS users
     by ranking ALL catalog items the user has not rated in training (full ranking, no sampling);
     an item is "relevant" if the user's test rating is >= 4.0. Compared with a popularity baseline.
  5. --tune: small grid search (n_factors 50/100/150, reg_all 0.02/0.05, n_epochs 20/30) on a
     subsample (TUNE_MAX_RATINGS), best RMSE wins.
  6. Refit on ALL (capped) ratings and save item factors/biases + metrics.

Outputs (data/processed/): cf_model.npz, cf_meta.json, metrics.json, eval/ (used by step8)
Time on 8M ratings: ~10-20 min (two SVD fits), + ~5 min with --tune. Peak RAM ~3 GB.
"""
from __future__ import annotations

import argparse
import gc
import time
from collections import defaultdict
from dataclasses import dataclass
from itertools import product

import numpy as np
import pandas as pd

import config
from step1_prepare_movielens import rating_velocity
from utils import banner, fail, human_minutes, load_json, log, print_table, ranking_metrics, save_json, top_k_indices, warn

try:
    from surprise import SVD, BaselineOnly
    from surprise.trainset import Trainset
except ImportError:  # pragma: no cover
    SVD = None

SECONDS_PER_MILLION = 10.0     # rough SVD time per 1M ratings (100 factors, 20 epochs) on a laptop


@dataclass
class MFModel:
    """Plain numpy copy of a trained Surprise model (easy to save, fast to predict with)."""
    mu: float
    user_ids: np.ndarray
    item_ids: np.ndarray
    bu: np.ndarray
    bi: np.ndarray
    pu: np.ndarray | None = None     # None for BaselineOnly (no factors)
    qi: np.ndarray | None = None

    def __post_init__(self):
        self.user_index = pd.Index(self.user_ids)
        self.item_index = pd.Index(self.item_ids)

    def predict(self, users: np.ndarray, items: np.ndarray, chunk: int = 200_000) -> np.ndarray:
        """Exactly Surprise's formula: unknown users/items simply get no bias / no factor term."""
        u = self.user_index.get_indexer(users)
        i = self.item_index.get_indexer(items)
        est = np.full(len(u), self.mu, dtype=np.float64)
        known_u, known_i = u >= 0, i >= 0
        est[known_u] += self.bu[u[known_u]]
        est[known_i] += self.bi[i[known_i]]
        if self.pu is not None:
            both = np.where(known_u & known_i)[0]
            for start in range(0, len(both), chunk):        # chunks keep memory small
                rows = both[start:start + chunk]
                est[rows] += np.einsum("ij,ij->i", self.pu[u[rows]], self.qi[i[rows]])
        return np.clip(est, 0.5, 5.0)


# ----------------------------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------------------------
def load_ratings(out_dir, catalog_ids: np.ndarray, with_app_data: bool):
    df = pd.read_parquet(out_dir / "ratings.parquet")
    app_info = {}
    if with_app_data:
        from retrain import load_app_ratings               # reads DATABASE_URL (see retrain.py)
        app = load_app_ratings()
        app_info = {"app_ratings": int((app["source"] == "explicit").sum()),
                    "app_pseudo_ratings": int((app["source"] != "explicit").sum()),
                    "app_users": int(app["userId"].nunique())}
        log(f"In-app data: {app_info['app_ratings']:,} ratings + {app_info['app_pseudo_ratings']:,} "
            f"behaviour pseudo-ratings from {app_info['app_users']:,} users")
        df = pd.concat([df, app[df.columns]], ignore_index=True)
    before = len(df)
    df = df[df["movieId"].isin(catalog_ids)].reset_index(drop=True)
    if len(df) < before:
        log(f"Dropped {before - len(df):,} ratings for titles not in the catalog")
    return df, app_info


def cap_users(df: pd.DataFrame, max_ratings: int, seed: int, keep_from: int | None = None):
    """Keep random WHOLE users until `max_ratings` is reached (app users, id >= keep_from, always kept)."""
    info = {"sampled": False, "n_ratings_before_sampling": int(len(df)),
            "n_users_before_sampling": int(df["userId"].nunique())}
    if len(df) <= max_ratings:
        return df, info
    counts = df["userId"].value_counts()
    rng = np.random.default_rng(seed)
    users = counts.index.to_numpy()
    priority = np.where(users >= keep_from, -1.0, rng.random(len(users))) if keep_from else rng.random(len(users))
    order = np.argsort(priority)
    cumulative = np.cumsum(counts.to_numpy()[order])
    chosen = users[order[cumulative <= max_ratings]]
    df = df[df["userId"].isin(chosen)].reset_index(drop=True)
    info.update(sampled=True, n_ratings_after_sampling=int(len(df)), n_users_after_sampling=int(len(chosen)))
    warn(f"{info['n_ratings_before_sampling']:,} ratings > MAX_RATINGS={max_ratings:,}: kept {len(chosen):,} of "
         f"{len(users):,} users ({len(df):,} ratings). Flagged in model_meta.json.")
    return df, info


def split_ratings(df: pd.DataFrame, seed: int):
    """Per-user hold-out of the latest TEST_FRACTION ratings (temporal), else random."""
    has_time = "timestamp" in df.columns and df["timestamp"].notna().all() and df["timestamp"].nunique() > 1
    if has_time:
        df = df.sort_values(["userId", "timestamp"], kind="stable").reset_index(drop=True)
        size = df.groupby("userId")["rating"].transform("size").to_numpy()
        rank = df.groupby("userId").cumcount().to_numpy()
        n_test = np.ceil(size * config.TEST_FRACTION)
        is_test = (size >= 5) & (rank >= size - n_test)
        kind = "temporal (latest 20% of each user's ratings)"
    else:
        rng = np.random.default_rng(seed)
        size = df.groupby("userId")["rating"].transform("size").to_numpy()
        is_test = (size >= 5) & (rng.random(len(df)) < config.TEST_FRACTION)
        kind = "random 80/20 (no timestamps)"
    train, test = df[~is_test].reset_index(drop=True), df[is_test].reset_index(drop=True)
    log(f"Split: {kind} -> train {len(train):,} / test {len(test):,} ratings")
    return train, test, kind


def build_trainset(df: pd.DataFrame):
    """Build a Surprise Trainset straight from numpy arrays.

    (Surprise's own Dataset.load_from_df first copies every rating into a Python list, which
    needs ~1 GB extra for 8M ratings - building the Trainset directly avoids that.)
    """
    u_codes, u_raw = pd.factorize(df["userId"])
    i_codes, i_raw = pd.factorize(df["movieId"])
    ur, ir = defaultdict(list), defaultdict(list)
    for u, i, r in zip(u_codes.tolist(), i_codes.tolist(), df["rating"].astype("float64").tolist()):
        ur[u].append((i, r))
        ir[i].append((u, r))
    trainset = Trainset(ur, ir, len(u_raw), len(i_raw), len(df), (0.5, 5.0),
                        {int(raw): k for k, raw in enumerate(u_raw)},
                        {int(raw): k for k, raw in enumerate(i_raw)})
    return trainset, np.asarray(u_raw, dtype=np.int64), np.asarray(i_raw, dtype=np.int64)


def fit_svd(trainset, user_ids, item_ids, params: dict, label: str = "SVD") -> MFModel:
    estimate = trainset.n_ratings / 1e6 * SECONDS_PER_MILLION * params["n_factors"] / 100 * params["n_epochs"] / 20
    log(f"Training {label} on {trainset.n_ratings:,} ratings (n_factors={params['n_factors']}, "
        f"n_epochs={params['n_epochs']}, reg_all={params['reg_all']}) - estimated {human_minutes(estimate)}")
    start = time.time()
    algo = SVD(n_factors=params["n_factors"], n_epochs=params["n_epochs"], lr_all=params["lr_all"],
               reg_all=params["reg_all"], random_state=config.SEED)
    algo.fit(trainset)
    log(f"  done in {time.time() - start:.1f}s")
    return MFModel(trainset.global_mean, user_ids, item_ids, algo.bu.copy(), algo.bi.copy(),
                   algo.pu.astype(np.float32), algo.qi.astype(np.float32))


def fit_baseline(trainset, user_ids, item_ids) -> MFModel:
    algo = BaselineOnly(verbose=False)
    algo.fit(trainset)
    return MFModel(trainset.global_mean, user_ids, item_ids, algo.bu.copy(), algo.bi.copy())


def rating_errors(pred: np.ndarray, truth: np.ndarray) -> dict:
    err = pred - truth
    return {"rmse": round(float(np.sqrt(np.mean(err ** 2))), 4), "mae": round(float(np.mean(np.abs(err))), 4)}


# ----------------------------------------------------------------------------------------------
# Ranking evaluation (full ranking over the catalog)
# ----------------------------------------------------------------------------------------------
def choose_eval_users(train, test, seed: int) -> np.ndarray:
    relevant = test[test["rating"] >= config.RELEVANT_THRESHOLD]
    users = np.intersect1d(relevant["userId"].unique(), train["userId"].unique())
    rng = np.random.default_rng(seed)
    if len(users) > config.EVAL_USERS:
        users = rng.choice(users, config.EVAL_USERS, replace=False)
    return np.sort(users)


def catalog_item_arrays(model: MFModel, catalog_ids: np.ndarray):
    """Item biases/factors laid out in catalog order (zeros for titles the model never saw)."""
    pos = model.item_index.get_indexer(catalog_ids)
    known = pos >= 0
    bi = np.zeros(len(catalog_ids), dtype=np.float32)
    bi[known] = model.bi[pos[known]]
    qi = np.zeros((len(catalog_ids), model.qi.shape[1]), dtype=np.float32)
    qi[known] = model.qi[pos[known]]
    return bi, qi


def evaluate_ranking(model: MFModel, train, test, catalog_ids, users) -> dict:
    cat_index = pd.Index(catalog_ids)
    pop = np.bincount(cat_index.get_indexer(train["movieId"]), minlength=len(catalog_ids)).astype(np.float32)
    bi, qi = catalog_item_arrays(model, catalog_ids)
    tr = train[train["userId"].isin(users)]
    te = test[(test["userId"].isin(users)) & (test["rating"] >= config.RELEVANT_THRESHOLD)]
    seen = tr.groupby("userId")["movieId"].apply(lambda s: cat_index.get_indexer(s.to_numpy()))
    relevant = te.groupby("userId")["movieId"].apply(lambda s: set(cat_index.get_indexer(s.to_numpy()).tolist()))
    u_pos = model.user_index.get_indexer(users)

    svd_top, pop_top = [], []
    for start in range(0, len(users), 256):
        batch = users[start:start + 256]
        up = u_pos[start:start + 256]
        scores = model.mu + model.bu[up][:, None] + bi[None, :] + model.pu[up] @ qi.T
        pop_scores = np.repeat(pop[None, :], len(batch), axis=0)
        for row, user in enumerate(batch):                  # never recommend what they already rated
            scores[row, seen[user]] = -np.inf
            pop_scores[row, seen[user]] = -np.inf
        svd_top.append(top_k_indices(scores, config.TOP_K))
        pop_top.append(top_k_indices(pop_scores, config.TOP_K))
    rel = [relevant[u] for u in users]
    return {"svd": ranking_metrics(np.vstack(svd_top), rel, config.TOP_K),
            "popularity": ranking_metrics(np.vstack(pop_top), rel, config.TOP_K)}


# ----------------------------------------------------------------------------------------------
# Tuning
# ----------------------------------------------------------------------------------------------
def tune(df: pd.DataFrame, base_params: dict) -> tuple[dict, list]:
    small, _ = cap_users(df, config.TUNE_MAX_RATINGS, config.SEED + 1)
    train, test, _ = split_ratings(small, config.SEED)
    trainset, users, items = build_trainset(train)
    grid = list(product([50, 100, 150], [0.02, 0.05], [20, 30]))
    log(f"Grid search: {len(grid)} combinations on {len(small):,} ratings")
    results = []
    for n_factors, reg_all, n_epochs in grid:
        params = {**base_params, "n_factors": n_factors, "reg_all": reg_all, "n_epochs": n_epochs}
        model = fit_svd(trainset, users, items, params, label="candidate")
        err = rating_errors(model.predict(test["userId"].to_numpy(), test["movieId"].to_numpy()),
                            test["rating"].to_numpy())
        results.append({"n_factors": n_factors, "reg_all": reg_all, "n_epochs": n_epochs, **err})
    results.sort(key=lambda r: r["rmse"])
    print_table(["n_factors", "reg_all", "n_epochs", "RMSE", "MAE"],
                [[r["n_factors"], r["reg_all"], r["n_epochs"], r["rmse"], r["mae"]] for r in results],
                title="Grid search (sorted by RMSE, best first)")
    best = results[0]
    return {**base_params, "n_factors": best["n_factors"], "reg_all": best["reg_all"],
            "n_epochs": best["n_epochs"]}, results


# ----------------------------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(description="Step 7 - train + evaluate Surprise SVD")
    parser.add_argument("--sample", action="store_true", help="use the demo-data folders")
    parser.add_argument("--tune", action="store_true", help="grid-search SVD settings on a subsample")
    parser.add_argument("--with-app-data", action="store_true",
                        help="also use in-app ratings + behaviour from DATABASE_URL (see retrain.py)")
    args = parser.parse_args(argv)

    banner("Step 7/9 - Train collaborative filtering (Surprise SVD)")
    if SVD is None:
        fail("scikit-surprise is not installed -> pip install -r requirements.txt")
    start_all = time.time()
    out_dir = config.processed_dir(args.sample)
    for name, hint in (("ratings.parquet", "step1"), ("catalog_base.parquet", "step4")):
        if not (out_dir / name).exists():
            fail(f"{out_dir / name} not found -> run {hint} first")
    catalog_ids = pd.read_parquet(out_dir / "catalog_base.parquet", columns=["movie_id"])["movie_id"].to_numpy(np.int64)

    df, app_info = load_ratings(out_dir, catalog_ids, args.with_app_data)
    log(f"{len(df):,} ratings, {df['userId'].nunique():,} users, {df['movieId'].nunique():,} titles")
    df, sample_info = cap_users(df, config.MAX_RATINGS, config.SEED,
                                keep_from=config.APP_USER_ID_OFFSET if args.with_app_data else None)
    params = {"n_factors": config.N_FACTORS, "n_epochs": config.N_EPOCHS, "lr_all": config.LR_ALL,
              "reg_all": config.REG_ALL}
    if args.sample:
        params = dict(config.SAMPLE_SVD_PARAMS)
        log(f"Demo data is small -> using small-data SVD settings {params}")
    total_estimate = 2.2 * len(df) / 1e6 * SECONDS_PER_MILLION * params["n_factors"] / 100 * params["n_epochs"] / 20
    log(f"Estimated total time for this step: {human_minutes(total_estimate + 30)}")

    tuning = []
    if args.tune:
        params, tuning = tune(df, params)
        log(f"Best settings: {params}")

    # ---- evaluation fit (train split only) ----------------------------------------------------
    train, test, split_kind = split_ratings(df, config.SEED)
    trainset, users, items = build_trainset(train)
    mu = trainset.global_mean
    truth = test["rating"].to_numpy()
    t_users, t_items = test["userId"].to_numpy(), test["movieId"].to_numpy()

    level0 = rating_errors(np.full(len(test), mu), truth)
    log("Training Level 1 baseline (BaselineOnly: global mean + user bias + item bias)")
    level1 = rating_errors(fit_baseline(trainset, users, items).predict(t_users, t_items), truth)
    eval_model = fit_svd(trainset, users, items, params)
    svd_err = rating_errors(eval_model.predict(t_users, t_items), truth)

    eval_users = choose_eval_users(train, test, config.SEED)
    log(f"Ranking evaluation: {len(eval_users):,} users x {len(catalog_ids):,} catalog titles (full ranking)")
    ranking = evaluate_ranking(eval_model, train, test, catalog_ids, eval_users)

    print_table(["Rating prediction (lower is better)", "RMSE", "MAE"], [
        ["Level 0: global mean", level0["rmse"], level0["mae"]],
        ["Level 1: BaselineOnly (user + item bias)", level1["rmse"], level1["mae"]],
        [f"SVD ({params['n_factors']} factors)", svd_err["rmse"], svd_err["mae"]],
    ], title=f"Test set: {len(test):,} ratings, {split_kind}")
    print_table([f"Top-{config.TOP_K} ranking (higher is better)", "precision@10", "recall@10", "NDCG@10"], [
        ["Popularity baseline", ranking["popularity"]["precision_at_10"], ranking["popularity"]["recall_at_10"],
         ranking["popularity"]["ndcg_at_10"]],
        ["SVD", ranking["svd"]["precision_at_10"], ranking["svd"]["recall_at_10"], ranking["svd"]["ndcg_at_10"]],
    ], title=f"{ranking['svd']['n_users']:,} test users, relevant = test rating >= {config.RELEVANT_THRESHOLD}")
    if svd_err["rmse"] >= level1["rmse"]:
        warn("SVD did not beat the BaselineOnly RMSE - try --tune or more data")

    # ---- save what step8 needs to tune the blend (train-split model, so no test leakage) -----
    eval_dir = out_dir / "eval"
    eval_dir.mkdir(exist_ok=True)
    cat_index = pd.Index(catalog_ids)
    pos = cat_index.get_indexer(train["movieId"])
    train_count = np.bincount(pos, minlength=len(catalog_ids)).astype(np.float64)
    train_sum = np.bincount(pos, weights=train["rating"].to_numpy(np.float64), minlength=len(catalog_ids))
    velocity = rating_velocity(train, config.VELOCITY_WINDOW_DAYS)["ml_velocity"].reindex(catalog_ids)
    up = eval_model.user_index.get_indexer(eval_users)
    np.savez_compressed(
        eval_dir / "eval_model.npz", global_mean=mu, catalog_ids=catalog_ids,
        item_ids=eval_model.item_ids, qi=eval_model.qi, bi=eval_model.bi.astype(np.float32),
        user_ids=eval_users, pu=eval_model.pu[up], bu=eval_model.bu[up].astype(np.float32),
        train_count=train_count, train_mean=np.divide(train_sum, train_count, out=np.full_like(train_sum, np.nan),
                                                      where=train_count > 0),
        train_velocity=velocity.fillna(0.0).to_numpy(np.float64))
    rows = pd.concat([train[train["userId"].isin(eval_users)].assign(split="train"),
                      test[test["userId"].isin(eval_users)].assign(split="test")])
    rows[["userId", "movieId", "rating", "split"]].to_parquet(eval_dir / "eval_ratings.parquet", index=False)

    metrics = {
        "split": split_kind, "n_train": int(len(train)), "n_test": int(len(test)), "params": params,
        "rating_prediction": {"global_mean": level0, "baseline_only": level1, "svd": svd_err},
        "ranking": {**ranking, "k": config.TOP_K, "relevant_threshold": config.RELEVANT_THRESHOLD,
                    "n_users": ranking["svd"]["n_users"]},
        "tuning": tuning,
    }
    save_json(out_dir / "metrics.json", metrics)
    del trainset, eval_model, train, test, rows
    gc.collect()

    # ---- final model on ALL ratings -------------------------------------------------------------
    full_set, users, items = build_trainset(df)
    final = fit_svd(full_set, users, items, params, label="final SVD on all ratings")
    np.savez_compressed(out_dir / "cf_model.npz", item_ids=final.item_ids, qi=final.qi,
                        bi=final.bi.astype(np.float32), global_mean=final.mu)
    info = load_json(out_dir / "movielens_info.json", {})
    save_json(out_dir / "cf_meta.json", {
        "algorithm": "SVD (Surprise, biased matrix factorisation)", **params,
        "global_mean": round(float(final.mu), 4), "n_train_ratings": int(full_set.n_ratings),
        "n_users_trained": int(full_set.n_users), "n_cf_items": int(full_set.n_items),
        "ratings_source": info.get("name", ""), "with_app_data": bool(args.with_app_data), **app_info,
        **sample_info, "trained_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    log(f"Saved cf_model.npz ({full_set.n_items:,} items x {params['n_factors']} factors), cf_meta.json, metrics.json")
    log(f"Step 7 done in {time.time() - start_all:.1f}s")


if __name__ == "__main__":
    main()
