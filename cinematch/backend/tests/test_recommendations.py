"""Recommendation API: FR-4.1 .. FR-4.5, AC-1, AC-3, NFR-3."""
import uuid

import pytest

from app.database import SessionLocal
from app.models import Event, RequestLog
from app.security import create_access_token
from app.services.model_store import load_state
from app.vocab import AGE_RATINGS, GENRES
from tests.helpers import ids_with_genre, rate_many

CARD_KEYS = {"movie_id", "title", "year", "content_type", "genres", "poster_url", "backdrop_url",
             "avg_rating", "rating_count", "runtime", "age_rating", "language", "critic_score",
             "mood_tags", "start_emotion", "end_emotion", "overview", "trailer_key", "collection_name"}


def recs(client, headers, context=None, limit=20):
    r = client.post("/api/recommendations", json={"context": context or {}, "limit": limit}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------------------ FR-4.1
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer not-a-jwt"}, {"Authorization": "Basic abc"}])
def test_fr41_unknown_user_gets_400(client, headers):
    r = client.post("/api/recommendations", json={"context": {}}, headers=headers)
    assert r.status_code == 400
    assert r.json() == {"detail": "User could not be identified"}


def test_fr41_token_of_deleted_or_unknown_user_gets_400(client):
    token = create_access_token(uuid.uuid4())
    r = client.post("/api/recommendations", json={}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400 and r.json()["detail"] == "User could not be identified"


@pytest.mark.parametrize("method,path", [
    ("get", "/api/home"), ("get", "/api/ratings/me"), ("post", "/api/recommendations/2/dismiss"),
    ("get", "/api/profile/insights"), ("get", "/api/playback/me"), ("post", "/api/party"),
    ("get", "/api/admin/stats"),
])
def test_other_protected_endpoints_are_401(client, method, path):
    r = getattr(client, method)(path)
    assert r.status_code == 401


# ------------------------------------------------------------------------------ AC-1 / FR-4.2 / FR-4.3
def test_ac1_personalised_ranked_list_with_reasons(client, new_user, state):
    headers, user = new_user("Horror Fan")
    horror = ids_with_genre(state, "Horror", 8)
    comedy = [m for m in ids_with_genre(state, "Comedy", 12) if m not in horror][:4]
    rate_many(client, headers, [(m, 5.0) for m in horror] + [(m, 1.0) for m in comedy])

    body = recs(client, headers, {"weather": "rainy", "hour": 20})
    assert set(body) >= {"request_id", "label", "fallback", "items", "context_used"}
    assert body["fallback"] is False
    assert len(body["items"]) == 20                                  # FR-4.2
    rated = set(horror + comedy)
    for item in body["items"]:
        assert CARD_KEYS <= set(item)
        assert isinstance(item["score"], float)
        assert isinstance(item["reason"], str) and item["reason"]    # FR-4.3
        assert item["movie_id"] not in rated                         # already rated -> not recommended
    assert body["context_used"]["time_of_day"] == "evening"
    reasons = " | ".join(i["reason"] for i in body["items"])
    assert "Because you rated" in reasons

    # taste is respected: at least twice as much Horror in the top 10 as in the catalog
    no_ctx = recs(client, headers)
    share = sum("Horror" in i["genres"] for i in no_ctx["items"][:10]) / 10
    base = state.genre_matrix[:, GENRES.index("Horror")].mean()
    assert share >= 2 * base
    # and the disliked genre (Comedy) is pushed down
    comedy_share = sum("Comedy" in i["genres"] for i in no_ctx["items"][:10]) / 10
    assert comedy_share < state.genre_matrix[:, GENRES.index("Comedy")].mean()


def test_limit_is_capped_at_20(client, new_user):
    headers, _ = new_user()
    assert len(recs(client, headers, limit=50)["items"]) == 20
    assert len(recs(client, headers, limit=5)["items"]) == 5


def test_recommendations_change_right_after_rating(client, new_user, state):
    headers, _ = new_user("Fold-in")
    before = [i["movie_id"] for i in recs(client, headers)["items"]]
    rate_many(client, headers, [(m, 5.0) for m in ids_with_genre(state, "Romance", 5)])
    after = [i["movie_id"] for i in recs(client, headers)["items"]]
    assert before != after


def test_nfr3_every_request_is_logged(client, new_user):
    headers, user = new_user("Logged")
    body = recs(client, headers, {"occasion": "date_night"})
    with SessionLocal() as db:
        row = db.get(RequestLog, uuid.UUID(body["request_id"]))
    assert row is not None
    assert row.endpoint == "/api/recommendations" and str(row.user_id) == user["id"]
    assert row.movie_ids == [i["movie_id"] for i in body["items"]]
    assert row.context["occasion"] == "date_night" and row.latency_ms > 0 and row.fallback is False


# ------------------------------------------------------------------------------ hard filters
def test_hard_filters_are_respected(client, new_user, state):
    headers, _ = new_user("Filters")
    items = recs(client, headers, {"time_available_min": 100})["items"]
    assert all(i["runtime"] is not None and i["runtime"] <= 110 for i in items)

    items = recs(client, headers, {"language": "hi"}, limit=5)["items"]
    assert items and all(i["language"] == "hi" for i in items)

    items = recs(client, headers, {"content_type": "series"}, limit=8)["items"]
    assert items and all(i["content_type"] == "series" for i in items)

    items = recs(client, headers, {"franchise_mode": "only"}, limit=5)["items"]
    assert items and all(i["collection_name"] for i in items)
    items = recs(client, headers, {"franchise_mode": "exclude"})["items"]
    assert all(i["collection_name"] is None for i in items)

    items = recs(client, headers, {"max_age_rating": "UA 13+"})["items"]
    assert all(i["age_rating"] in ("U", "UA 7+", "UA 13+") or
               (i["age_rating"] is None and {"Animation", "Children"} & set(i["genres"])) for i in items)

    items = recs(client, headers, {"directors": ["christopher nolan"]}, limit=3)["items"]
    for i in items:
        assert "Christopher Nolan" in client.get(f"/api/movies/{i['movie_id']}").json()["directors"]


def test_reference_films_are_used_and_excluded(client, new_user, state):
    headers, _ = new_user("Refs")
    ref = ids_with_genre(state, "Sci-Fi", 1)[0]
    body = recs(client, headers, {"reference_movie_ids": [ref]})
    assert ref not in [i["movie_id"] for i in body["items"]]
    title = state.title[state.idx(ref)]
    assert any(i["reason"] == f"Because you picked {title}" for i in body["items"])


def test_too_few_matches_relaxes_filters_and_says_so(client, new_user, state):
    headers, _ = new_user("Relax")
    nolan = {int(state.movie_ids[i]) for i in state.directors.rows("Christopher Nolan")}
    body = recs(client, headers, {"directors": ["Christopher Nolan"]}, limit=20)
    assert len(body["items"]) == 20
    assert "relaxed director" in body["label"]
    assert body["relaxed_filters"] == ["directors"]
    first = [i["movie_id"] for i in body["items"][:len(nolan)]]
    assert set(first) == nolan                     # exact matches still come first


def test_kids_occasion_caps_age_rating(client, new_user):
    headers, _ = new_user("Kids")
    body = recs(client, headers, {"occasion": "kids_time"})
    assert body["context_used"]["max_age_rating"] == "UA 7+"
    cap = AGE_RATINGS.index("UA 7+")
    for i in body["items"]:
        if i["age_rating"]:
            assert AGE_RATINGS.index(i["age_rating"]) <= cap
        else:
            assert {"Animation", "Children"} & set(i["genres"])


def test_invalid_context_value_is_422(client, new_user):
    headers, _ = new_user()
    r = client.post("/api/recommendations", json={"context": {"weather": "volcanic"}}, headers=headers)
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)


# ------------------------------------------------------------------------------ FR-4.5 dismiss
def test_fr45_dismissed_item_never_comes_back(client, new_user):
    headers, user = new_user("Dismisser")
    first = recs(client, headers)["items"][0]["movie_id"]
    assert client.post(f"/api/recommendations/{first}/dismiss", headers=headers).status_code == 204
    assert client.post(f"/api/recommendations/{first}/dismiss", headers=headers).status_code == 204  # idempotent
    contexts = [{}, {"weather": "sunny"}, {"occasion": "date_night"}, {"time_available_min": 180},
                {"reference_movie_ids": [first + 1]}, {"genres": ["Drama", "Comedy"]}]
    for ctx in contexts:
        assert first not in [i["movie_id"] for i in recs(client, headers, ctx)["items"]]
    home = client.get("/api/home", headers=headers).json()
    assert first not in [c["movie_id"] for row in home["rows"] for c in row["items"]]
    assert client.get(f"/api/movies/{first}", headers=headers).json()["dismissed"] is True
    with SessionLocal() as db:
        events = db.query(Event).filter(Event.user_id == uuid.UUID(user["id"]), Event.type == "dismiss").all()
    assert len(events) == 2 and events[0].movie_id == first
    # undo
    assert client.delete(f"/api/recommendations/{first}/dismiss", headers=headers).status_code == 204
    assert client.get(f"/api/movies/{first}", headers=headers).json()["dismissed"] is False


def test_dismiss_unknown_movie_404(client, new_user):
    headers, _ = new_user()
    assert client.post("/api/recommendations/987654321/dismiss", headers=headers).status_code == 404


# ------------------------------------------------------------------------------ AC-3 / FR-4.4 fallback
@pytest.fixture
def catalog_only(restore_model):
    """Simulate 'model unavailable': catalog loaded, no model arrays."""
    store = restore_model
    store.state = load_state(store.artifacts_dir, store.state.version, catalog_only=True)
    return store


def test_ac3_fallback_without_model_respects_filters(client, new_user, catalog_only):
    headers, _ = new_user("NoModel")
    assert client.get("/api/health").json()["model_loaded"] is False
    ctx = {"occasion": "kids_time", "start_emotion": "sadness", "end_emotion": "joy"}
    body = recs(client, headers, ctx)
    assert body["fallback"] is True and body["label"] == "Trending now"
    assert len(body["items"]) > 0
    cap = AGE_RATINGS.index("UA 7+")
    for i in body["items"]:
        assert i["reason"] == "Trending now"
        assert (i["age_rating"] and AGE_RATINGS.index(i["age_rating"]) <= cap) or \
               {"Animation", "Children"} & set(i["genres"])
    pops = [catalog_only.state.popularity[catalog_only.state.idx(i["movie_id"])] for i in body["items"]]
    assert pops == sorted(pops, reverse=True)       # popularity order


def test_ac3_fallback_relaxes_impossible_filters(client, new_user, catalog_only):
    headers, _ = new_user("Impossible")
    ctx = {"language": "xx", "directors": ["Nobody Atall"], "actors": ["No One"], "time_available_min": 30,
           "occasion": "date_night", "end_emotion": "joy"}
    body = recs(client, headers, ctx)
    assert body["fallback"] is True and body["label"] == "Trending now"
    assert len(body["items"]) == 20
    assert {"actors", "directors", "language"} <= set(body["relaxed_filters"])


def test_ac3_fallback_from_database_when_no_catalog_in_memory(client, new_user, restore_model):
    headers, _ = new_user("NoCatalog")
    restore_model.state = None
    body = recs(client, headers, {"weather": "rainy"})
    assert body["fallback"] is True and body["label"] == "Trending now"
    assert len(body["items"]) == 20 and CARD_KEYS <= set(body["items"][0])
    home = client.get("/api/home", headers=headers)
    assert home.status_code == 200 and home.json()["rows"]


def test_no_catalog_and_no_db_gives_empty_list_not_500(client, new_user, restore_model, monkeypatch):
    headers, _ = new_user("Empty")
    restore_model.state = None

    def broken(*args, **kwargs):
        raise RuntimeError("movies table unavailable")
    monkeypatch.setattr("app.routers.recommend.db_popularity_fallback", broken)
    body = recs(client, headers)
    assert body["items"] == [] and body["label"] == "Trending now" and body["fallback"] is True


def test_engine_error_falls_back_instead_of_500(client, new_user, monkeypatch):
    headers, _ = new_user("Crash")

    def boom(*args, **kwargs):
        raise ValueError("simulated bug")
    monkeypatch.setattr("app.routers.recommend.recommend", boom)
    body = recs(client, headers, {"weather": "sunny"})
    assert body["fallback"] is True and len(body["items"]) == 20


# ------------------------------------------------------------------------------ concurrency
def test_many_parallel_requests_do_not_exhaust_the_db_pool(client, new_user):
    """Regression: helpers must reuse the request's DB session. Opening a second
    connection inside a request deadlocked the pool under ~20 parallel requests."""
    from concurrent.futures import ThreadPoolExecutor

    from app.services import rating_stats
    headers, _ = new_user("Parallel")

    def call(k):
        rating_stats.invalidate()          # force the stats query inside every request
        r = client.post("/api/recommendations", json={"context": {"hour": k % 24}}, headers=headers)
        return r.status_code, r.json()["fallback"]

    with ThreadPoolExecutor(max_workers=25) as pool:
        results = list(pool.map(call, range(40)))
    assert results == [(200, False)] * 40
