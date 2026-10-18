"""
utils.py - small helpers shared by the pipeline steps.

Nothing clever here: printing progress, reading/writing JSON safely, the pipe-separated
list format used by catalog.csv, and the ranking metrics (precision / recall / NDCG @ K)
that both step7 and step8 use, so the two steps always measure things the same way.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Iterable

import numpy as np


# ----------------------------------------------------------------------------------------------
# Printing progress
# ----------------------------------------------------------------------------------------------
_START = time.time()


def banner(title: str) -> None:
    """Big header at the start of every step."""
    line = "=" * 78
    print(f"\n{line}\n{title}\n{line}", flush=True)


def log(message: str) -> None:
    """Print a progress line with the time since the script started, e.g. '[  12.3s] ...'."""
    print(f"[{time.time() - _START:7.1f}s] {message}", flush=True)


def warn(message: str) -> None:
    print(f"[ WARNING ] {message}", flush=True)


def fail(message: str, code: int = 1) -> None:
    """Stop the script with a clear message (non-zero exit code so run_all/retrain notice)."""
    print(f"\n[ ERROR ] {message}\n", file=sys.stderr, flush=True)
    sys.exit(code)


def require(path: Path, hint: str) -> Path:
    """Make sure an input file exists; otherwise explain which step creates it."""
    if not Path(path).exists():
        fail(f"Missing input: {path}\n          -> {hint}")
    return Path(path)


def human_minutes(seconds: float) -> str:
    if seconds < 90:
        return f"~{max(1, round(seconds))} s"
    return f"~{seconds / 60:.0f} min"


# ----------------------------------------------------------------------------------------------
# Files
# ----------------------------------------------------------------------------------------------
def save_json(path: Path, data) -> None:
    """Write JSON atomically: write a temp file, then rename it over the real one.

    If the program crashes half way, the old file is still intact (never a half-written file).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=_json_default)
    os.replace(tmp, path)


def load_json(path: Path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _json_default(value):
    """Let json.dump handle numpy numbers."""
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"Cannot convert {type(value)} to JSON")


# ----------------------------------------------------------------------------------------------
# Pipe-separated lists ("Action|Comedy") - the list format of catalog.csv
# ----------------------------------------------------------------------------------------------
def clean_text(value) -> str:
    """Turn anything into a single-line string ('' for missing values)."""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value)
    if text.lower() in ("nan", "none", "<na>"):
        return ""
    return " ".join(text.split())   # removes newlines / tabs / double spaces


def join_list(items: Iterable, limit: int | None = None) -> str:
    """['a', 'b'] -> 'a|b'. Removes blanks and duplicates, keeps the original order."""
    out, seen = [], set()
    for item in items or []:
        text = clean_text(item).replace("|", "/")   # a '|' inside an item would break the format
        if text and text not in seen:
            seen.add(text)
            out.append(text)
        if limit and len(out) >= limit:
            break
    return "|".join(out)


def split_list(value) -> list[str]:
    """'a|b' -> ['a', 'b'];  '' or NaN -> []."""
    text = clean_text(value)
    return [part for part in text.split("|") if part] if text else []


# ----------------------------------------------------------------------------------------------
# Ranking metrics
# ----------------------------------------------------------------------------------------------
def top_k_indices(scores: np.ndarray, k: int) -> np.ndarray:
    """Row-wise indices of the k largest scores, best first. scores: [n_users, n_items]."""
    k = min(k, scores.shape[1])
    part = np.argpartition(-scores, k - 1, axis=1)[:, :k]               # unordered top-k (fast)
    part_scores = np.take_along_axis(scores, part, axis=1)
    order = np.argsort(-part_scores, axis=1, kind="stable")             # now sort just those k
    return np.take_along_axis(part, order, axis=1)


def ranking_metrics(top_items: np.ndarray, relevant: list[set], k: int) -> dict:
    """Mean precision@k, recall@k and NDCG@k over users.

    top_items: [n_users, k] recommended item indices (best first)
    relevant:  list of sets - the held-out items each user rated >= RELEVANT_THRESHOLD
    """
    discounts = 1.0 / np.log2(np.arange(2, k + 2))       # 1/log2(rank+1) for rank = 1..k
    precision, recall, ndcg = [], [], []
    for row, rel in zip(top_items, relevant):
        if not rel:
            continue
        hits = np.array([item in rel for item in row[:k]], dtype=float)
        n_hits = hits.sum()
        precision.append(n_hits / k)
        recall.append(n_hits / len(rel))
        ideal = discounts[: min(len(rel), k)].sum()
        ndcg.append(float((hits * discounts[: len(hits)]).sum() / ideal))
    if not precision:
        return {"precision_at_10": 0.0, "recall_at_10": 0.0, "ndcg_at_10": 0.0, "n_users": 0}
    return {
        "precision_at_10": round(float(np.mean(precision)), 4),
        "recall_at_10": round(float(np.mean(recall)), 4),
        "ndcg_at_10": round(float(np.mean(ndcg)), 4),
        "n_users": len(precision),
    }


def print_table(headers: list[str], rows: list[list], title: str | None = None) -> None:
    """Plain text table, e.g. for the metrics summary."""
    cells = [[str(h) for h in headers]] + [[_fmt(c) for c in row] for row in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(headers))]
    if title:
        print(f"\n{title}")
    sep = "+".join("-" * (w + 2) for w in widths)
    print(f"+{sep}+")
    for i, row in enumerate(cells):
        print("| " + " | ".join(c.ljust(w) if j == 0 else c.rjust(w)
                                for j, (c, w) in enumerate(zip(row, widths))) + " |")
        if i == 0:
            print(f"+{sep}+")
    print(f"+{sep}+", flush=True)


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)
