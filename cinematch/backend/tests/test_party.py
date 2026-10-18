"""Watch-party mode (CONTRACT 5.8)."""
import uuid

from app.database import SessionLocal
from app.models import RequestLog
from tests.helpers import ids_with_genre, rate_many


def test_party_flow_and_blending(client, new_user, state):
    h1, u1 = new_user("Aman")
    h2, u2 = new_user("Bela")
    h3, u3 = new_user("Chirag")
    horror = ids_with_genre(state, "Horror", 6)
    romance = [m for m in ids_with_genre(state, "Romance", 12) if m not in horror][:6]
    rate_many(client, h1, [(m, 5.0) for m in horror] + [(m, 1.0) for m in romance])
    rate_many(client, h2, [(m, 5.0) for m in romance] + [(m, 1.5) for m in horror])

    r = client.post("/api/party", json={"member_emails": [u2["email"]]}, headers=h1)
    assert r.status_code == 200, r.text
    party = r.json()
    assert len(party["code"]) == 6 and party["host"]["id"] == u1["id"]
    assert {m["id"] for m in party["members"]} == {u1["id"], u2["id"]}

    # third person joins with the code (case-insensitive)
    joined = client.post(f"/api/party/{party['code'].lower()}/join", headers=h3).json()
    assert {m["id"] for m in joined["members"]} == {u1["id"], u2["id"], u3["id"]}
    assert client.get(f"/api/party/{party['code']}", headers=h2).json()["code"] == party["code"]

    body = client.post(f"/api/party/{party['code']}/recommendations",
                       json={"context": {"hour": 21}, "limit": 15}, headers=h2).json()
    assert body["fallback"] is False and len(body["items"]) == 15
    for item in body["items"]:
        assert set(item["member_scores"]) == {"Aman", "Bela", "Chirag"}
        # "average without misery": members WITH ratings are never predicted below 2.5
        assert item["member_scores"]["Aman"] >= 2.5 and item["member_scores"]["Bela"] >= 2.5
        assert item["reason"] in ("Everyone should enjoy this", "A good compromise for the group")
        assert item["movie_id"] not in set(horror) | set(romance)   # someone rated these low
    with SessionLocal() as db:
        log = db.get(RequestLog, uuid.UUID(body["request_id"]))
    assert log.endpoint == "/api/party/{code}/recommendations" and log.context["members"] == 3


def test_party_respects_every_members_dismissals(client, new_user):
    h1, u1 = new_user("Host")
    h2, u2 = new_user("Guest")
    party = client.post("/api/party", json={"member_emails": [u2["email"]]}, headers=h1).json()
    first = client.post(f"/api/party/{party['code']}/recommendations", json={}, headers=h1).json()["items"]
    target = first[0]["movie_id"]
    client.post(f"/api/recommendations/{target}/dismiss", headers=h2)
    again = client.post(f"/api/party/{party['code']}/recommendations", json={}, headers=h1).json()["items"]
    assert target not in [i["movie_id"] for i in again]


def test_party_errors(client, new_user):
    h1, _ = new_user("Solo")
    h2, _ = new_user("Outsider")
    r = client.post("/api/party", json={"member_emails": ["ghost1@example.com", "ghost2@example.com"]}, headers=h1)
    assert r.status_code == 404 and "ghost1@example.com" in r.json()["detail"]
    party = client.post("/api/party", json={}, headers=h1).json()
    assert len(party["members"]) == 1
    assert client.get("/api/party/ZZZZZZ", headers=h1).status_code == 404
    r = client.post(f"/api/party/{party['code']}/recommendations", json={}, headers=h2)
    assert r.status_code == 403
    assert client.post(f"/api/party/{party['code']}/recommendations", json={}).status_code == 401
