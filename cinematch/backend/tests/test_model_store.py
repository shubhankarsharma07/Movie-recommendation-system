"""Artifact loading, hot reload and NFR-4 (keep the last good model)."""
import time

import numpy as np

from app.database import SessionLocal
from app.models import Movie
from tests.make_fixture_artifacts import make_artifacts, set_current


def _recs_ok(client, headers):
    body = client.post("/api/recommendations", json={}, headers=headers).json()
    return body["fallback"] is False and len(body["items"]) == 20


def test_nfr4_corrupt_new_version_keeps_old_model(client, new_user, restore_model, artifacts_copy):
    store = restore_model
    headers, _ = new_user("NFR4")
    store.configure(artifacts_copy)
    assert store.reload(force=True) is True
    old_version = store.state.version

    # a broken retrain: new folder with a corrupt item_factors.npy, and current.txt points at it
    bad = make_artifacts(artifacts_copy, n_items=60, version="v20261002_090000", write_current=False)
    (bad / "item_factors.npy").write_bytes(b"this is not a numpy file")
    set_current(artifacts_copy, "v20261002_090000")

    assert store.reload() is True                       # still serving a model...
    assert store.state.version == old_version           # ...the OLD one
    assert "v20261002_090000" in store.last_error
    assert _recs_ok(client, headers)
    health = client.get("/api/health").json()
    assert health["model_loaded"] is True and health["model_version"] == old_version


def test_nfr4_wrong_shapes_and_nan_are_rejected(client, restore_model, artifacts_copy):
    store = restore_model
    store.configure(artifacts_copy)
    store.reload(force=True)
    old_version = store.state.version
    for version, damage in [
        ("v20261002_100000", lambda f: np.save(f / "item_factors.npy", np.zeros((5, 16), np.float32))),
        ("v20261002_110000", lambda f: np.save(f / "item_bias.npy", np.full(60, np.nan, np.float32))),
        ("v20261002_120000", lambda f: (f / "catalog.csv").write_text("nothing,useful\n1,2\n")),
        ("v20261002_130000", lambda f: (f / "model_meta.json").write_text("{not json")),
    ]:
        folder = make_artifacts(artifacts_copy, n_items=60, version=version, write_current=False)
        damage(folder)
        set_current(artifacts_copy, version)
        store.reload()
        assert store.state.version == old_version, version
        assert store.model_loaded


def test_hot_reload_picks_up_new_version_in_background(client, new_user, restore_model, artifacts_copy):
    store = restore_model
    headers, _ = new_user("HotReload")
    store.configure(artifacts_copy)
    store.reload(force=True)
    make_artifacts(artifacts_copy, n_items=90, version="v20261003_080000", seed=11, write_current=False)
    set_current(artifacts_copy, "v20261003_080000")

    store.check_interval = 0            # don't wait 30 s in a test
    client.get("/api/health")           # any request triggers the cheap check -> background reload
    for _ in range(100):
        if store.state.version == "v20261003_080000":
            break
        time.sleep(0.05)
    assert store.state.version == "v20261003_080000" and store.state.n == 90
    assert client.get("/api/health").json()["catalog_size"] == 90
    # the movies table was upserted for the new version (old rows are kept for old ratings)
    with SessionLocal() as db:
        assert db.query(Movie).count() >= 120
    assert _recs_ok(client, headers)


def test_reload_interval_limits_checks(restore_model, artifacts_copy):
    store = restore_model
    store.configure(artifacts_copy)
    store.reload(force=True)
    store.check_interval = 3600
    store._last_check = time.monotonic()
    make_artifacts(artifacts_copy, n_items=50, version="v20261004_080000", write_current=False)
    set_current(artifacts_copy, "v20261004_080000")
    store.maybe_reload()
    time.sleep(0.2)
    assert store.state.version != "v20261004_080000"     # not checked yet (30 s rule)


def test_nothing_loadable_means_no_model(restore_model, tmp_path):
    store = restore_model
    store.state = None
    store.configure(tmp_path)                            # empty folder, no current.txt
    assert store.reload() is False and store.state is None and store.model_loaded is False


def test_broken_arrays_but_good_catalog_loads_catalog_only(restore_model, tmp_path):
    store = restore_model
    store.state = None
    folder = make_artifacts(tmp_path, n_items=40, version="v20261005_080000")
    (folder / "item_factors.npy").write_bytes(b"garbage")
    store.configure(tmp_path)
    assert store.reload() is False
    assert store.state is not None and store.state.n == 40 and store.model_loaded is False
