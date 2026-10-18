"""
step8_tune_blend.py - choose the blend weights of the final recommendation score.

THE SCORING FORMULA (the backend uses the same one - keep them in sync)
--------------------------------------------------------------------------
    score(u, i) = w_cf      * cf_norm(u, i)
                + w_content * content_sim(u, i)
                + w_quality * quality_score(i)
                + w_trend   * trend_norm(i)
                [+ w_ref * ref_sim + w_ctx * ctx_match + w_behavior * behavior   <- added by the backend
                   at request time from the context/reference films/behaviour; NOT tuned here, they
                   stay at the CONTRACT defaults ref 0.35, ctx 0.25, behavior 0.10]
where
    cf_norm      = clip((r_hat - 0.5) / 4.5, 0, 1),  r_hat = global_mean + b_u + b_i + q_i . p_u
                   (titles with no CF data: r_hat = global_mean + b_u)
    content_sim  = max(0, cosine(plot_emb_i, profile_u)); profile_u = normalised mean embedding of the
                   titles the user rated >= 4.0 (if none: their 3 highest-rated titles)
    quality      = quality_score from the catalog (0-1)
    trend_norm   = 0.5 * popularity_score + 0.5 * (0.5 + 0.5 * tanh(2 * trending_velocity))
    (the backend divides the score by the sum of the weights in use - that does not change the ranking)

How the weights are tuned
    * Uses the model trained on the TRAINING split only (saved by step7) and the held-out test
      ratings of up to EVAL_USERS users. Quality and popularity are recomputed from training
      ratings only, so the tuning never peeks at the test answers.
    * The users are split in half: "tune" users pick the weights, "check" users confirm them.
    * Only the RATIOS between weights change the ranking, so w_cf is fixed at 0.45 (the contract
      default) and content/quality/trend are searched on a small grid (100 combinations),
      maximising precision@10. If the winner is not at least as good as the default weights on the
      check users, the defaults are kept (protects against over-fitting a small sample).
Output: data/processed/blend.json      Time: ~1-5 min for 2000 users x 30k titles.
"""
from __future__ import annotations

import argparse
import time
from itertools import product

import numpy as np
import pandas as pd

import config
from step4_build_catalog import compute_popularity_score, compute_quality_score
from utils import banner, fail, load_json, log, print_table, ranking_metrics, save_json, top_k_indices, warn

CF_WEIGHT = 0.45
GRID = {"content": [0.0, 0.05, 0.15, 0.3, 0.5], "quality": [0.0, 0.06, 0.12, 0.25, 0.4],
        "trend": [0.0, 0.05, 0.1, 0.2]}
FORMULA = ("score = w_cf*cf_norm + w_content*content_sim + w_quality*quality_score + w_trend*trend_norm "
           "(+ w_ref*ref_sim + w_ctx*ctx_match + w_behavior*behavior at serve time); "
           "cf_norm = clip((r_hat-0.5)/4.5,0,1) with r_hat = global_mean + b_u + b_i + q_i.p_u; "
           "content_sim = max(0, cos(plot_emb_i, mean plot_emb of titles the user rated >= 4)); "
           "trend_norm = 0.5*popularity_score + 0.5*(0.5+0.5*tanh(2*trending_velocity))")


def trend_norm(popularity: np.ndarray, velocity: np.ndarray) -> np.ndarray:
    return 0.5 * popularity + 0.5 * (0.5 + 0.5 * np.tanh(2.0 * velocity))


def load_inputs(out_dir):
    for name, hint in (("eval/eval_model.npz", "step7_train.py"), ("eval/eval_ratings.parquet", "step7_train.py"),
                       ("catalog_base.parquet", "step4_build_catalog.py")):
        if not (out_dir / name).exists():
            fail(f"{out_dir / name} not found -> run {hint} first")
    npz = np.load(out_dir / "eval" / "eval_model.npz")
    data = {k: npz[k] for k in npz.files}
    ratings = pd.read_parquet(out_dir / "eval" / "eval_ratings.parquet")
    catalog = pd.read_parquet(out_dir / "catalog_base.parquet").set_index("movie_id").loc[data["catalog_ids"]]
    return data, ratings, catalog.reset_index()


def leak_free_features(data, catalog: pd.DataFrame):
    """quality / trend computed from TRAINING ratings only (same formulas as step4)."""
    train_cat = catalog.copy()
    train_cat["ml_rating_mean"] = data["train_mean"]
    train_cat["ml_rating_count"] = data["train_count"]
    quality = compute_quality_score(train_cat).to_numpy(np.float32)
    popularity = compute_popularity_score(train_cat).to_numpy(np.float32)
    velocity = np.where(catalog["velocity_source"] == "tmdb", catalog["trending_velocity"],
                        np.clip(data["train_velocity"], -1.0, 5.0))
    return quality, trend_norm(popularity, velocity).astype(np.float32)


def load_embeddings(out_dir, catalog_ids):
    path = out_dir / "plot_emb.npy"
    if not path.exists():
        warn("plot_emb.npy not found (run step5) - content similarity will be 0")
        return None
    emb = np.load(path).astype(np.float32)
    ids = np.load(out_dir / "plot_emb_ids.npy")
    pos = pd.Index(ids).get_indexer(catalog_ids)
    out = np.zeros((len(catalog_ids), emb.shape[1]), dtype=np.float32)
    out[pos >= 0] = emb[pos[pos >= 0]]
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Step 8 - tune blend weights")
    parser.add_argument("--sample", action="store_true", help="use the demo-data folders")
    args = parser.parse_args(argv)

    banner("Step 8/9 - Tune blend weights")
    start = time.time()
    out_dir = config.processed_dir(args.sample)
    data, ratings, catalog = load_inputs(out_dir)
    catalog_ids = data["catalog_ids"]
    cat_index = pd.Index(catalog_ids)
    n_items = len(catalog_ids)

    # Item-side arrays in catalog order
    model_pos = pd.Index(data["item_ids"]).get_indexer(catalog_ids)
    known = model_pos >= 0
    bi = np.zeros(n_items, np.float32)
    bi[known] = data["bi"][model_pos[known]]
    qi = np.zeros((n_items, data["qi"].shape[1]), np.float32)
    qi[known] = data["qi"][model_pos[known]]
    quality, trend = leak_free_features(data, catalog)
    emb = load_embeddings(out_dir, catalog_ids)
    popularity_counts = data["train_count"].astype(np.float32)

    users = data["user_ids"]
    if len(users) < 20:
        warn("Too few evaluation users to tune - keeping the default weights")
    ratings = ratings.assign(pos=cat_index.get_indexer(ratings["movieId"]))
    train = ratings[ratings["split"] == "train"]
    test = ratings[(ratings["split"] == "test") & (ratings["rating"] >= config.RELEVANT_THRESHOLD)]
    seen = train.groupby("userId")["pos"].apply(np.array)
    relevant = test.groupby("userId")["pos"].apply(lambda s: set(s.tolist()))

    train_by_user = dict(tuple(train.groupby("userId")))

    def profile(user):
        rows = train_by_user[user]
        liked = rows[rows["rating"] >= config.RELEVANT_THRESHOLD]
        if liked.empty:
            liked = rows.nlargest(3, "rating")
        vec = emb[liked["pos"].to_numpy()].mean(axis=0)
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec

    combos = [dict(cf=CF_WEIGHT, content=c, quality=q, trend=t)
              for c, q, t in product(GRID["content"], GRID["quality"], GRID["trend"])]
    default = {k: config.DEFAULT_BLEND_WEIGHTS[k] for k in ("cf", "content", "quality", "trend")}
    named = {"popularity": None, "cf_only": dict(cf=1.0, content=0, quality=0, trend=0), "default": default}
    log(f"{len(users):,} users x {n_items:,} titles, {len(combos)} weight combinations")

    tops = {i: [] for i in range(len(combos))}
    tops.update({name: [] for name in named})
    for begin in range(0, len(users), 200):
        batch = users[begin:begin + 200]
        idx = np.arange(begin, begin + len(batch))
        r_hat = data["global_mean"] + data["bu"][idx][:, None] + bi[None, :] + data["pu"][idx] @ qi.T
        cf = np.clip((r_hat - 0.5) / 4.5, 0, 1).astype(np.float32)
        if emb is not None:
            content = np.clip(np.stack([profile(u) for u in batch]) @ emb.T, 0, 1)
        else:
            content = np.zeros_like(cf)
        mask = np.zeros_like(cf, dtype=bool)
        for row, user in enumerate(batch):
            mask[row, seen.get(user, np.array([], int))] = True

        def top(weights):
            score = (weights["cf"] * cf + weights["content"] * content
                     + weights["quality"] * quality[None, :] + weights["trend"] * trend[None, :])
            score[mask] = -np.inf
            return top_k_indices(score, config.TOP_K)

        for i, weights in enumerate(combos):
            tops[i].append(top(weights))
        for name, weights in named.items():
            if weights is None:
                pop = np.repeat(popularity_counts[None, :], len(batch), axis=0)
                pop[mask] = -np.inf
                tops[name].append(top_k_indices(pop, config.TOP_K))
            else:
                tops[name].append(top(weights))
    tops = {k: np.vstack(v) for k, v in tops.items()}

    # Split users into "tune" and "check" halves
    rng = np.random.default_rng(config.SEED)
    order = rng.permutation(len(users))
    halves = {"tune": np.sort(order[: len(users) // 2]), "check": np.sort(order[len(users) // 2:])}
    rel = [relevant.get(u, set()) for u in users]

    def score_of(key, half):
        rows = halves[half]
        return ranking_metrics(tops[key][rows], [rel[r] for r in rows], config.TOP_K)

    results = [(i, score_of(i, "tune")) for i in range(len(combos))]
    results.sort(key=lambda r: (r[1]["precision_at_10"], r[1]["ndcg_at_10"]), reverse=True)
    best_i, best_tune = results[0]
    best = combos[best_i]
    best_check, default_check = score_of(best_i, "check"), score_of("default", "check")
    use_tuned = best_check["precision_at_10"] >= default_check["precision_at_10"]
    chosen = best if use_tuned else default

    print_table(["Weights (cf/content/quality/trend)", "tune P@10", "tune NDCG@10"],
                [[f"{combos[i]['cf']}/{combos[i]['content']}/{combos[i]['quality']}/{combos[i]['trend']}",
                  m["precision_at_10"], m["ndcg_at_10"]] for i, m in results[:5]],
                title="Top 5 weight combinations on the tune users")
    check = {"popularity": score_of("popularity", "check"), "cf_only": score_of("cf_only", "check"),
             "blend_default": default_check, "blend_tuned": best_check}
    print_table(["Check users (not used for tuning)", "precision@10", "recall@10", "NDCG@10"],
                [[name, m["precision_at_10"], m["recall_at_10"], m["ndcg_at_10"]] for name, m in check.items()],
                title=f"Held-out comparison on {check['popularity']['n_users']} check users")
    log(("Using the TUNED weights " if use_tuned else "Tuned weights did not beat the defaults on the check "
         "users -> keeping the DEFAULT weights ") + str(chosen))

    weights = dict(config.DEFAULT_BLEND_WEIGHTS)
    weights.update({k: float(v) for k, v in chosen.items()})
    save_json(out_dir / "blend.json", {
        "weights": weights, "chosen": "tuned" if use_tuned else "default", "best_grid_weights": best,
        "formula": FORMULA, "grid": GRID, "cf_weight_fixed": CF_WEIGHT,
        "n_users": int(len(users)), "metrics": {"tune_best": best_tune, "check": check},
    })
    log(f"Saved {out_dir / 'blend.json'} in {time.time() - start:.1f}s")


if __name__ == "__main__":
    main()
