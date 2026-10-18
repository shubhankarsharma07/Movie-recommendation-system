"""Behaviour logging (Module 3): AC-4 drop-off, FR-3.2 rewatch, FR-3.3 browse-to-select,
continue watching, profile insights."""
import uuid

from app.database import SessionLocal
from app.models import Event, PlaybackSession


def start(client, headers, movie_id, request_id=None):
    r = client.post("/api/playback/start", json={"movie_id": movie_id, "request_id": request_id}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def stop(client, headers, session_id, position, duration, completed=False):
    r = client.post(f"/api/playback/{session_id}/stop",
                    json={"position_sec": position, "duration_sec": duration, "completed": completed},
                    headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_ac4_drop_off_is_written(client, new_user):
    headers, _ = new_user("Viewer")
    s = start(client, headers, 2, request_id=str(uuid.uuid4()))
    assert s["is_rewatch"] is False and s["start_number"] == 1
    for event in ("pause", "resume", "seek_back", "seek_forward", "seek_forward"):
        r = client.post(f"/api/playback/{s['session_id']}/event", json={"type": event, "position_sec": 100},
                        headers=headers)
        assert r.status_code == 204
    result = stop(client, headers, s["session_id"], position=1830.5, duration=7200)
    assert result["drop_off_sec"] == 1830.5
    assert abs(result["completion_ratio"] - 1830.5 / 7200) < 1e-4

    with SessionLocal() as db:
        row = db.get(PlaybackSession, uuid.UUID(s["session_id"]))
    assert row.drop_off_sec == 1830.5 and row.duration_sec == 7200 and row.completed is False
    assert row.ended_at is not None
    assert (row.pause_count, row.seek_back_count, row.seek_forward_count) == (1, 1, 2)


def test_rewatch_and_start_number(client, new_user):
    headers, _ = new_user("Rewatcher")
    s1 = start(client, headers, 3)
    stop(client, headers, s1["session_id"], 5000, 5100)          # >= 90 % -> completed
    s2 = start(client, headers, 3)
    assert s2["is_rewatch"] is True and s2["start_number"] == 2
    mine = client.get("/api/playback/me", headers=headers).json()["items"]
    assert mine[0]["session_id"] == s2["session_id"] and mine[0]["is_rewatch"] is True
    assert mine[1]["completed"] is True


def test_playback_errors(client, new_user):
    headers, _ = new_user("Errors")
    other, _ = new_user("Other")
    assert client.post("/api/playback/start", json={"movie_id": 99999999}, headers=headers).status_code == 404
    s = start(client, headers, 4)
    assert client.post(f"/api/playback/{s['session_id']}/stop", json={"position_sec": 1}, headers=other).status_code == 404
    assert client.post("/api/playback/not-a-uuid/stop", json={"position_sec": 1}, headers=headers).status_code == 404
    bad = client.post(f"/api/playback/{s['session_id']}/event", json={"type": "explode"}, headers=headers)
    assert bad.status_code == 422


def test_events_batch_and_browse_to_select(client, new_user):
    headers, user = new_user("Events")
    rid = str(uuid.uuid4())
    events = [
        {"type": "impression", "request_id": rid, "row_id": "for_you"},
        {"type": "details_open", "movie_id": 2, "request_id": rid, "row_id": "for_you"},
        {"type": "select", "movie_id": 2, "request_id": rid, "value": 4200},
        {"type": "select", "movie_id": 3, "request_id": "not-a-uuid", "value": 5800},
        {"type": "trailer_open", "movie_id": 2},
        {"type": "search"}, {"type": "filter_apply"}, {"type": "binge_next", "movie_id": 10000000},
    ]
    assert client.post("/api/events", json={"events": events}, headers=headers).status_code == 204
    with SessionLocal() as db:
        rows = db.query(Event).filter(Event.user_id == uuid.UUID(user["id"])).all()
    assert len(rows) == len(events)
    assert client.post("/api/events", json={"events": [{"type": "bogus"}]}, headers=headers).status_code == 422
    insights = client.get("/api/profile/insights", headers=headers).json()
    assert insights["avg_browse_to_select_ms"] == 5000.0


def test_continue_watching_row_and_insights(client, new_user, state):
    headers, _ = new_user("Binger")
    movies = [int(state.movie_ids[i]) for i in range(20, 26)]
    for m in movies[:5]:
        s = start(client, headers, m)
        stop(client, headers, s["session_id"], 600, 6000)        # stopped at 10 minutes
    s = start(client, headers, movies[5])
    stop(client, headers, s["session_id"], 6000, 6000, completed=True)

    home = client.get("/api/home", headers=headers).json()
    row = next(r for r in home["rows"] if r["id"] == "continue_watching")
    assert [c["movie_id"] for c in row["items"]] == list(reversed(movies[:5]))
    assert row["items"][0]["reason"] == "Continue from 10 min" and row["items"][0]["resume_sec"] == 600

    insights = client.get("/api/profile/insights", headers=headers).json()
    assert insights["sessions_count"] == 6
    assert abs(insights["completion_rate"] - (5 * 0.1 + 1.0) / 6) < 1e-3
    assert set(insights) >= {"top_genres", "completion_rate", "avg_browse_to_select_ms", "rewatch_count",
                             "binge_score", "seek_forward_rate", "favourite_decade", "ratings_count",
                             "sessions_count", "taste_summary"}


def test_behaviour_changes_recommendations(client, new_user, state):
    """Finishing (and rewatching) titles acts like a positive pseudo-rating."""
    headers, _ = new_user("Behaviour")
    before = [i["movie_id"] for i in client.post("/api/recommendations", json={}, headers=headers).json()["items"]]
    for m in before[:3]:
        for _ in range(2):
            s = start(client, headers, m)
            stop(client, headers, s["session_id"], 5900, 6000)
    after = [i["movie_id"] for i in client.post("/api/recommendations", json={}, headers=headers).json()["items"]]
    assert before != after
