"""NFR-1: ranked list in < 2 s at p95 for a 65,000-item catalog.

Builds a synthetic 65k catalog (k=100 factors, d=384 float16 embeddings, the
same sizes as the real pipeline), loads it, and times 50 POST
/api/recommendations calls with varied contexts (+ 10 /api/home calls).
"""
import time

import numpy as np
import pytest

from tests.helpers import rate_many
from tests.make_fixture_artifacts import make_artifacts

N_ITEMS = 65_000


@pytest.fixture(scope="module")
def big_artifacts(tmp_path_factory):
    out = tmp_path_factory.mktemp("big_artifacts")
    make_artifacts(out, n_items=N_ITEMS, k=100, d=384, seed=3, version="v20261002_000000")
    return out


CONTEXTS = [
    {},
    {"weather": "rainy", "hour": 19},
    {"occasion": "date_night", "time_available_min": 120},
    {"festival": "diwali", "language": "hi"},
    {"start_emotion": "sadness", "end_emotion": "joy", "genres": ["Drama"]},
    {"reference_movie_ids": [10, 20, 30], "max_age_rating": "UA 13+"},
    {"directors": ["Christopher Nolan"], "franchise_mode": "exclude"},
    {"nostalgia_decade": 1990, "content_type": "movie", "weather": "stormy", "hour": 1},
    {"occasion": "kids_time", "actors": ["Maya Sharma"]},
    {"content_type": "series", "occasion": "weekend_binge", "preset": "trending"},
]


def test_nfr1_p95_under_2_seconds_on_65k_items(client, new_user, restore_model, big_artifacts):
    store = restore_model
    store.configure(big_artifacts)
    t0 = time.perf_counter()
    assert store.reload(force=True) is True
    load_seconds = time.perf_counter() - t0
    assert store.state.n == N_ITEMS

    headers, _ = new_user("Latency")
    ids = [int(m) for m in store.state.movie_ids[store.state.has_cf][:40]]
    rate_many(client, headers, [(m, float(1 + (k % 9) / 2)) for k, m in enumerate(ids)])
    for m in ids[:5]:
        s = client.post("/api/playback/start", json={"movie_id": m}, headers=headers).json()
        client.post(f"/api/playback/{s['session_id']}/stop", json={"position_sec": 900, "duration_sec": 6000},
                    headers=headers)

    client.post("/api/recommendations", json={}, headers=headers)     # warm-up
    timings = []
    for k in range(50):
        ctx = CONTEXTS[k % len(CONTEXTS)]
        start = time.perf_counter()
        r = client.post("/api/recommendations", json={"context": ctx, "limit": 20}, headers=headers)
        timings.append(time.perf_counter() - start)
        assert r.status_code == 200 and len(r.json()["items"]) == 20
        assert r.json()["fallback"] is False
    p50, p95 = np.percentile(timings, 50), np.percentile(timings, 95)

    home_timings = []
    for _ in range(10):
        start = time.perf_counter()
        r = client.get("/api/home?hour=20", headers=headers)
        home_timings.append(time.perf_counter() - start)
        assert r.status_code == 200 and len(r.json()["rows"]) >= 8
    home_p95 = np.percentile(home_timings, 95)

    print(f"\n[NFR-1] {N_ITEMS} items: load {load_seconds:.1f}s | /api/recommendations "
          f"p50 {p50 * 1000:.0f} ms, p95 {p95 * 1000:.0f} ms | /api/home p95 {home_p95 * 1000:.0f} ms")
    assert p95 < 2.0
    assert home_p95 < 2.0
