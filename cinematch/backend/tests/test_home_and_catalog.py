"""Home page rows, catalog browser (FR-1.3/1.4), meta, context, onboarding."""
import uuid

from app.database import SessionLocal
from app.models import RequestLog
from app.services import weather
from tests.helpers import ids_with_genre, rate_many


def test_home_rows_and_presets(client, new_user, state, monkeypatch):
    headers, _ = new_user("Home")
    rate_many(client, headers, [(m, 5.0) for m in ids_with_genre(state, "Thriller", 5)])
    fake_weather = {"id": "rainy", "label": "Rainy", "temp_c": 24.1, "city": "Mathura",
                    "description": "light rain", "source": "live"}
    monkeypatch.setattr("app.routers.context.get_weather", lambda lat, lon: fake_weather)
    r = client.get("/api/home?lat=27.49&lon=77.67&hour=19", headers=headers)
    assert r.status_code == 200
    home = r.json()
    assert set(home) == {"request_id", "context", "needs_onboarding", "hero", "rows"}
    assert home["needs_onboarding"] is False
    assert home["context"]["weather"]["id"] == "rainy" and home["context"]["time_of_day"] == "evening"
    assert home["hero"]["reason"] and "movie_id" in home["hero"]
    ids = [row["id"] for row in home["rows"]]
    for expected in ("for_you", "weather", "time_fit", "trending", "acclaimed", "feel_good", "nostalgia",
                     "date_night", "mind_bending"):
        assert expected in ids, ids
    assert any(i.startswith("because_") for i in ids)
    weather_row = next(r for r in home["rows"] if r["id"] == "weather")
    assert weather_row["title"] == "Perfect for this rainy evening"
    assert weather_row["filter"] == {"weather": "rainy", "time_of_day": "evening"}
    for row in home["rows"]:
        assert len(row["items"]) >= 4 and isinstance(row["filter"], dict)
        assert all(item["reason"] for item in row["items"])

    # "See all": the filter preset reproduces the same kind of list in the Mood Mixer
    for row in home["rows"]:
        if row["id"] == "continue_watching":
            continue
        again = client.post("/api/recommendations", json={"context": row["filter"]}, headers=headers).json()
        overlap = {i["movie_id"] for i in again["items"]} & {i["movie_id"] for i in row["items"]}
        assert len(overlap) >= len(row["items"]) // 2, row["id"]

    with SessionLocal() as db:
        log = db.get(RequestLog, uuid.UUID(home["request_id"]))
    assert log.endpoint == "/api/home" and log.context["weather"] == "rainy"


def test_home_cold_start_needs_onboarding(client, new_user):
    headers, _ = new_user("Newbie")
    home = client.get("/api/home", headers=headers).json()
    assert home["needs_onboarding"] is True
    assert home["rows"][0]["id"] == "for_you"


def test_onboarding_movies(client, new_user):
    items = client.get("/api/onboarding/movies").json()["items"]
    assert len(items) == 30 and len({i["movie_id"] for i in items}) == 30
    headers, _ = new_user("Onboard")
    rate_many(client, headers, [(items[0]["movie_id"], 4.0)])
    again = client.get("/api/onboarding/movies", headers=headers).json()["items"]
    assert items[0]["movie_id"] not in [i["movie_id"] for i in again]


def test_catalog_list_filters_sort_and_pagination(client, state):
    body = client.get("/api/movies?page_size=10").json()
    assert body["total"] == state.n and len(body["items"]) == 10 and body["page"] == 1
    pops = [state.popularity[state.idx(i["movie_id"])] for i in body["items"]]
    assert pops == sorted(pops, reverse=True)

    body = client.get("/api/movies?q=&genre=&year_from=&year_to=&language=&content_type=&sort=popular").json()
    assert body["total"] == state.n                      # empty params are ignored

    body = client.get("/api/movies?genre=comedy&year_from=1990&year_to=2010&page_size=100").json()
    assert body["items"] and all("Comedy" in i["genres"] and 1990 <= i["year"] <= 2010 for i in body["items"])

    body = client.get("/api/movies?content_type=series&sort=title&page_size=100").json()
    titles = [i["title"].lower() for i in body["items"]]
    assert titles == sorted(titles) and all(i["content_type"] == "series" for i in body["items"])

    body = client.get("/api/movies?sort=year&language=en").json()
    years = [i["year"] for i in body["items"]]
    assert years == sorted(years, reverse=True) and all(i["language"] == "en" for i in body["items"])

    page2 = client.get("/api/movies?page=2&page_size=7").json()
    page1 = client.get("/api/movies?page=1&page_size=14").json()
    assert [i["movie_id"] for i in page2["items"]] == [i["movie_id"] for i in page1["items"][7:]]
    assert client.get("/api/movies?sort=rating").status_code == 200


def test_cards_show_rating_merged_with_in_app_ratings(client, new_user, state):
    from app.services import rating_stats
    movie = client.get("/api/movies/2").json()
    headers, _ = new_user("Merger")
    client.post("/api/ratings", json={"movie_id": 2, "rating": 0.5}, headers=headers)
    rating_stats.invalidate()
    after = client.get("/api/movies/2").json()
    assert after["rating_count"] == movie["rating_count"] + 1
    assert after["avg_rating"] <= movie["avg_rating"]


def test_search_and_details(client, new_user, state):
    title = state.title[0]
    found = client.get(f"/api/movies/search?q={title[:4].lower()}&limit=5").json()["items"]
    assert found and found[0]["title"].lower().startswith(title[:4].lower())
    assert client.get("/api/movies/search?q=").json() == {"items": []}

    details = client.get("/api/movies/2").json()
    for key in ("directors", "cast", "keywords", "emotion_arc", "decade", "quality_score", "popularity_score",
                "trending_velocity", "imdb_rating", "user_rating", "dismissed", "similar"):
        assert key in details
    assert details["user_rating"] is None and len(details["similar"]) == 12
    assert 2 not in [s["movie_id"] for s in details["similar"]]
    assert client.get("/api/movies/987654").status_code == 404


def test_meta_filters_and_people(client):
    meta = client.get("/api/meta/filters").json()
    assert meta["age_ratings"] == ["U", "UA 7+", "UA 13+", "UA 16+", "A"]
    assert meta["content_types"] == ["any", "movie", "series"]
    assert {"id": "rainy", "label": "Rainy", "icon": "🌧️"} in meta["weather"]
    assert {"minutes": None, "label": "No limit"} in meta["time_available"]
    assert meta["time_of_day"] == ["morning", "afternoon", "evening", "night", "late_night"]
    assert {"code": "en", "name": "English"} in meta["languages"]
    diwali = next(f for f in meta["festivals"] if f["id"] == "diwali")
    assert diwali["date"] == "2026-11-08"
    assert {"id": "fear", "label": "Tense"} in meta["emotions"]
    assert "Christopher Nolan" in meta["directors"] and "Toy Saga Collection" in meta["franchises"]
    assert meta["actors"] and meta["decades"]
    people = client.get("/api/meta/people?role=director&q=nol&limit=5").json()
    assert people["items"][0] == "Christopher Nolan"
    assert client.get("/api/meta/people?role=actor&q=a&limit=3").json()["items"]
    assert client.get("/api/meta/people?role=producer").status_code == 422


def test_context_endpoint(client, monkeypatch):
    body = client.get("/api/context?hour=23").json()
    assert body["weather"] is None and body["weather_status"] == "no_location"
    assert body["time_of_day"] == "night" and body["hour"] == 23
    assert set(body) == {"weather", "time_of_day", "hour", "upcoming_festival", "weather_status"}
    # location given but no API key -> unavailable, never an error
    weather.reset_for_tests()
    body = client.get("/api/context?lat=27.49&lon=77.67&hour=7").json()
    assert body["weather"] is None and body["weather_status"] == "unavailable" and body["time_of_day"] == "morning"


def test_health(client, state):
    body = client.get("/api/health").json()
    assert body == {"status": "ok", "model_loaded": True, "model_version": state.version,
                    "dataset_mode": "sample", "catalog_size": state.n}


def test_home_never_500_when_engine_fails(client, new_user, monkeypatch):
    headers, _ = new_user("HomeCrash")

    def boom(*args, **kwargs):
        raise ValueError("simulated engine bug")
    monkeypatch.setattr("app.routers.home.recommend", boom)
    r = client.get("/api/home", headers=headers)
    assert r.status_code == 200
    ids = [row["id"] for row in r.json()["rows"]]
    assert "trending" in ids and r.json()["hero"] is not None
