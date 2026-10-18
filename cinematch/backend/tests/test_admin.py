"""Admin panel (CONTRACT 5.9) and request-log retention (NFR-3)."""
import uuid
from datetime import timedelta

from app.database import SessionLocal, utcnow
from app.models import RequestLog
from app.services.logging import cleanup_request_logs


def test_admin_endpoints_forbidden_for_normal_users(client, new_user):
    headers, _ = new_user("NotAdmin")
    for method, path in [("get", "/api/admin/stats"), ("post", "/api/admin/reload-model"),
                         ("post", "/api/admin/retrain"), ("get", "/api/admin/retrain")]:
        r = getattr(client, method)(path, headers=headers)
        assert r.status_code == 403, path
        assert r.json() == {"detail": "Admin access required"}


def test_admin_stats(client, admin_headers, new_user):
    headers, _ = new_user("StatsUser")
    client.post("/api/ratings", json={"movie_id": 2, "rating": 4.5}, headers=headers)
    rec = client.post("/api/recommendations", json={"context": {"weather": "sunny"}}, headers=headers).json()
    client.post("/api/events", json={"events": [{"type": "select", "movie_id": rec["items"][0]["movie_id"],
                                                 "request_id": rec["request_id"], "value": 3000}]},
                headers=headers)
    r = client.get("/api/admin/stats", headers=admin_headers)
    assert r.status_code == 200
    stats = r.json()
    expected = {"users", "ratings", "sessions", "events", "requests", "ratings_by_day", "rating_histogram",
                "top_rated", "rec_ctr", "avg_browse_to_select_ms", "avg_completion", "dismiss_rate",
                "latency_p50_ms", "latency_p95_ms", "requests_by_day", "context_usage", "model"}
    assert expected <= set(stats)
    assert stats["users"] >= 2 and stats["ratings"] >= 1 and stats["requests"] >= 1
    assert set(stats["rating_histogram"]) == {f"{v / 2:.1f}" for v in range(1, 11)}
    assert stats["rating_histogram"]["4.5"] >= 1
    assert stats["context_usage"]["weather"] >= 1
    assert 0 < stats["rec_ctr"] <= 1
    assert stats["latency_p95_ms"] >= stats["latency_p50_ms"] > 0
    assert stats["model"]["version"] == "v20261001_120000" and stats["model"]["model_loaded"] is True
    assert stats["top_rated"] and {"movie", "avg", "count"} == set(stats["top_rated"][0])


def test_admin_reload_and_retrain(client, admin_headers):
    r = client.post("/api/admin/reload-model", headers=admin_headers)
    assert r.status_code == 200 and r.json()["version"] == "v20261001_120000"
    r = client.post("/api/admin/retrain", headers=admin_headers)
    assert r.status_code == 400 and "disabled" in r.json()["detail"]
    r = client.get("/api/admin/retrain", headers=admin_headers)
    assert r.status_code == 200 and r.json()["status"] == "idle"


def test_request_log_cleanup_keeps_90_days(client):
    now = utcnow()
    ages = {"d10": 10, "d100": 100, "d179": 179, "d181": 181, "d400": 400}
    ids = {}
    with SessionLocal() as db:
        for name, days in ages.items():
            ids[name] = uuid.uuid4()
            db.add(RequestLog(id=ids[name], endpoint="/api/recommendations", context={}, movie_ids=[],
                              fallback=False, latency_ms=1.0, created_at=now - timedelta(days=days)))
        db.commit()
    cleanup_request_logs(180)
    with SessionLocal() as db:
        alive = {name for name, rid in ids.items() if db.get(RequestLog, rid) is not None}
    assert alive == {"d10", "d100", "d179"}

    # asking for a shorter retention is clamped to the 90-day minimum
    cleanup_request_logs(30)
    with SessionLocal() as db:
        assert db.get(RequestLog, ids["d10"]) is not None
        assert db.get(RequestLog, ids["d100"]) is None
