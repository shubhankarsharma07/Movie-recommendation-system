"""Ratings: FR-1.1, FR-1.2, AC-2."""
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import Rating, User

MESSAGE = "Rating must be between 0.5 and 5.0 in steps of 0.5"


def _count(user_id=None):
    with SessionLocal() as db:
        q = select(func.count(Rating.id))
        if user_id:
            import uuid
            q = q.where(Rating.user_id == uuid.UUID(user_id))
        return db.scalar(q)


@pytest.mark.parametrize("bad", [5.5, 4.3, 0, 0.25, -1, 6, "abc", None, True, "4.25"])
def test_invalid_ratings_rejected_and_nothing_written(client, new_user, bad):
    headers, user = new_user("Rater")
    before = _count()
    r = client.post("/api/ratings", json={"movie_id": 2, "rating": bad}, headers=headers)
    assert r.status_code == 400
    assert r.json() == {"detail": MESSAGE}
    assert _count() == before
    assert _count(user["id"]) == 0


def test_ac2_exact_examples(client, new_user):
    """AC-2: 5.5 and 4.3 rejected with the range message, no row written."""
    headers, user = new_user("AC2")
    for bad in (5.5, 4.3):
        r = client.post("/api/ratings", json={"movie_id": 2, "rating": bad}, headers=headers)
        assert r.status_code == 400 and r.json()["detail"] == MESSAGE
    assert _count(user["id"]) == 0


@pytest.mark.parametrize("good", [0.5, 1, 2.5, 4.5, 5.0, "3.5"])
def test_valid_ratings_accepted(client, new_user, good):
    headers, _ = new_user("Good")
    r = client.post("/api/ratings", json={"movie_id": 2, "rating": good}, headers=headers)
    assert r.status_code == 200
    assert r.json()["rating"] == float(good) and r.json()["movie_id"] == 2


def test_rerate_updates_same_row(client, new_user):
    headers, user = new_user("ReRater")
    first = client.post("/api/ratings", json={"movie_id": 3, "rating": 2.0}, headers=headers).json()
    second = client.post("/api/ratings", json={"movie_id": 3, "rating": 4.5}, headers=headers).json()
    assert _count(user["id"]) == 1
    assert second["rating"] == 4.5 and second["created_at"] >= first["created_at"]
    mine = client.get("/api/ratings/me", headers=headers).json()["items"]
    assert len(mine) == 1 and mine[0]["rating"] == 4.5 and mine[0]["movie"]["movie_id"] == 3


def test_ratings_list_newest_first_and_delete(client, new_user):
    headers, user = new_user("Lister")
    for movie_id in (4, 5, 6):
        client.post("/api/ratings", json={"movie_id": movie_id, "rating": 3.0}, headers=headers)
    items = client.get("/api/ratings/me", headers=headers).json()["items"]
    assert [i["movie"]["movie_id"] for i in items] == [6, 5, 4]
    assert client.delete("/api/ratings/5", headers=headers).status_code == 204
    assert _count(user["id"]) == 2
    assert client.get("/api/auth/me", headers=headers).json()["rating_count"] == 2


def test_unknown_movie_and_auth(client, new_user):
    headers, _ = new_user("Unknown")
    assert client.post("/api/ratings", json={"movie_id": 999999, "rating": 3}, headers=headers).status_code == 404
    assert client.post("/api/ratings", json={"movie_id": 2, "rating": 3}).status_code == 401
    assert client.get("/api/ratings/me").status_code == 401


def test_database_check_constraint_blocks_bad_values(client, new_user):
    """Even code that bypasses the API cannot store 4.3 or 5.5 (DB CHECK)."""
    _, user = new_user("Constraint")
    import uuid
    for bad in (4.3, 5.5, 0.0):
        with SessionLocal() as db:
            db.add(Rating(user_id=uuid.UUID(user["id"]), movie_id=2, rating=bad))
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()
    with SessionLocal() as db:
        assert db.get(User, uuid.UUID(user["id"])) is not None
