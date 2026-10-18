"""
run_all.py - run the whole offline pipeline (steps 1-9) in order and print a summary.

    python run_all.py --sample            # demo data, fully offline, ~10 seconds
    python run_all.py                     # full MovieLens run (needs MOVIELENS_DIR, TMDB key optional)
    python run_all.py --skip-tmdb --skip-scores   # no network at all (no posters/overviews/IMDb)
    python run_all.py --tune              # also grid-search the SVD settings in step 7
    python run_all.py --from-step 5       # resume after fixing a problem in step 5

Each step runs as its own Python process, so memory is fully released between steps
(important for 25M ratings on an 8 GB laptop). The pipeline stops at the first failing step;
backend/artifacts/current.txt only changes when step 9 succeeds.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

import config
from utils import banner, load_json, print_table

STEPS = [
    (1, "step1_prepare_movielens.py", "Prepare MovieLens ratings"),
    (2, "step2_fetch_tmdb.py", "Fetch TMDB metadata (movies + series)"),
    (3, "step3_fetch_scores.py", "Fetch IMDb / critic scores"),
    (4, "step4_build_catalog.py", "Build the catalog"),
    (5, "step5_embeddings.py", "Content embeddings"),
    (6, "step6_emotion_arcs.py", "Emotion arcs"),
    (7, "step7_train.py", "Train + evaluate SVD"),
    (8, "step8_tune_blend.py", "Tune blend weights"),
    (9, "step9_export.py", "Export artifacts"),
]


def run(script: str, flags: list[str]) -> int:
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    return subprocess.run([sys.executable, str(config.ML_DIR / script), *flags], cwd=config.ML_DIR, env=env).returncode


def summary(sample: bool, timings: list) -> None:
    out_dir = config.processed_dir(sample)
    banner("Summary")
    version = (config.ARTIFACTS_DIR / "current.txt").read_text(encoding="utf-8").strip() \
        if (config.ARTIFACTS_DIR / "current.txt").exists() else "(none)"
    meta = load_json(config.ARTIFACTS_DIR / version / "model_meta.json", {})
    print(f"Live model version : {version}  (dataset_mode={meta.get('dataset_mode', '?')})")
    print(f"Catalog            : {meta.get('n_items', '?')} titles {meta.get('catalog_counts', {})}, "
          f"{meta.get('n_cf_items', '?')} with CF factors")
    print(f"Models             : SVD {meta.get('n_factors')} factors | embeddings: {meta.get('embedding_model')} "
          f"| emotions: {meta.get('emotion_model')}")
    print(f"Blend weights      : {meta.get('blend_weights')}")

    metrics = load_json(out_dir / "metrics.json", {})
    blend = load_json(out_dir / "blend.json", {})
    rp, rk = metrics.get("rating_prediction", {}), metrics.get("ranking", {})
    if rp:
        print_table(["Rating prediction (test set)", "RMSE", "MAE"], [
            ["Level 0: global mean", rp["global_mean"]["rmse"], rp["global_mean"]["mae"]],
            ["Level 1: BaselineOnly", rp["baseline_only"]["rmse"], rp["baseline_only"]["mae"]],
            ["SVD", rp["svd"]["rmse"], rp["svd"]["mae"]],
        ], title=f"Split: {metrics.get('split')}, {metrics.get('n_test', 0):,} test ratings")
    if rk:
        rows = [["Popularity baseline", *(rk["popularity"][k] for k in ("precision_at_10", "recall_at_10", "ndcg_at_10"))],
                ["SVD only", *(rk["svd"][k] for k in ("precision_at_10", "recall_at_10", "ndcg_at_10"))]]
        print_table(["Top-10 ranking (all test users)", "precision@10", "recall@10", "NDCG@10"], rows,
                    title=f"{rk.get('n_users', 0):,} users, relevant = rating >= {rk.get('relevant_threshold')}")
    check = blend.get("metrics", {}).get("check", {})
    if check:
        print_table(["Blend (held-out check users)", "precision@10", "recall@10", "NDCG@10"],
                    [[name, m["precision_at_10"], m["recall_at_10"], m["ndcg_at_10"]] for name, m in check.items()],
                    title=f"step8 check users (weights chosen: {blend.get('chosen')})")
    if timings:
        print_table(["Step", "seconds"], [[f"{n}. {label}", f"{sec:.1f}"] for n, label, sec in timings],
                    title="Time per step")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the CineMatch ML pipeline (steps 1-9)")
    parser.add_argument("--sample", action="store_true", help="bundled demo data, fully offline")
    parser.add_argument("--skip-tmdb", action="store_true", help="skip step 2 (TMDB)")
    parser.add_argument("--skip-scores", action="store_true", help="skip step 3 (IMDb/OMDb)")
    parser.add_argument("--tune", action="store_true", help="grid-search SVD settings in step 7")
    parser.add_argument("--from-step", type=int, default=1, help="start at this step (resume)")
    parser.add_argument("--to-step", type=int, default=9, help="stop after this step")
    args = parser.parse_args(argv)

    banner(f"CineMatch ML pipeline ({'DEMO sample data, offline' if args.sample else 'full data'})")
    if args.sample and not (config.SAMPLE_DIR / "ratings.csv").exists():
        print("Demo data not found - generating it first (make_sample_data.py)", flush=True)
        if run("make_sample_data.py", []) != 0:
            return 1

    timings = []
    for number, script, label in STEPS:
        if number < args.from_step or number > args.to_step:
            continue
        if (number == 2 and args.skip_tmdb) or (number == 3 and args.skip_scores):
            print(f"\n--- Skipping step {number} ({label}) ---", flush=True)
            continue
        flags = ["--sample"] if args.sample else []
        if number == 7 and args.tune:
            flags.append("--tune")
        start = time.time()
        code = run(script, flags)
        timings.append((number, label, time.time() - start))
        if code != 0:
            resume = f"python run_all.py --from-step {number}" + (" --sample" if args.sample else "")
            print(f"\n[ PIPELINE STOPPED ] step {number} ({script}) failed with exit code {code}.\n"
                  f"Fix the error above, then resume with:  {resume}\n"
                  f"backend/artifacts/current.txt was not changed.", file=sys.stderr, flush=True)
            return code
    if args.to_step >= 9:
        summary(args.sample, timings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
