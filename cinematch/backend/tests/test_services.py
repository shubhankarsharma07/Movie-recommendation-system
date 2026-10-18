"""Unit tests for festivals, weather, rules and the fold-in maths."""
from datetime import date

import httpx
import numpy as np
import pytest

from app.config import settings
from app.services import weather
from app.services.festivals import FESTIVAL_DATES, upcoming_festival
from app.services.recommender import compute_user_state, prepare, recommend
from app.services.rules import FESTIVAL_RULES, OCCASION_RULES, TIME_RULES, WEATHER_RULES, rule_match
from app.vocab import FESTIVALS, GENRES, OCCASIONS, TIME_OF_DAY, WEATHER, time_of_day_for_hour


def test_every_vocabulary_value_has_a_rule():
    assert set(WEATHER_RULES) == set(WEATHER)
    assert set(TIME_RULES) == set(TIME_OF_DAY)
    assert set(OCCASION_RULES) == set(OCCASIONS)
    assert set(FESTIVAL_RULES) == set(FESTIVALS) == set(FESTIVAL_DATES)


def test_time_of_day_buckets():
    assert [time_of_day_for_hour(h) for h in (5, 11, 12, 16, 17, 20, 21, 23, 0, 4)] == [
        "morning", "morning", "afternoon", "afternoon", "evening", "evening", "night", "night",
        "late_night", "late_night"]


def test_upcoming_festival():
    assert upcoming_festival(date(2026, 10, 2)) == {"id": "navratri", "label": "Navratri",
                                                    "date": "2026-10-11", "days_away": 9}
    assert upcoming_festival(date(2026, 10, 20))["id"] == "halloween"
    diwali = upcoming_festival(date(2026, 11, 1))
    assert diwali["id"] == "diwali" and diwali["days_away"] == 7
    assert upcoming_festival(date(2027, 6, 1)) is None            # nothing within 21 days
    assert upcoming_festival(date(2027, 12, 20))["id"] == "christmas"


def test_weather_mapping():
    assert weather.map_weather("Rain", 25) == "rainy"
    assert weather.map_weather("Clear", 35) == "hot"
    assert weather.map_weather("Clouds", 5) == "cold"
    assert weather.map_weather("Thunderstorm", 40) == "stormy"   # storm beats heat
    assert weather.map_weather("Haze", 20) == "foggy"
    assert weather.map_weather("Snow", -3) == "snowy"


@pytest.fixture
def fake_owm(monkeypatch):
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        return httpx.Response(200, json={"weather": [{"main": "Rain", "description": "light rain"}],
                                         "main": {"temp": 24.1}, "name": "Mathura"})
    monkeypatch.setattr(settings, "openweather_api_key", "test-key")
    monkeypatch.setattr(weather, "_transport", httpx.MockTransport(handler))
    weather.reset_for_tests()
    yield calls
    weather.reset_for_tests()


def test_weather_live_and_cached(fake_owm):
    result = weather.get_weather(27.4924, 77.6737)
    assert result == {"id": "rainy", "label": "Rainy", "temp_c": 24.1, "city": "Mathura",
                      "description": "light rain", "source": "live"}
    assert fake_owm[0].url.params["units"] == "metric" and fake_owm[0].url.params["appid"] == "test-key"
    weather.get_weather(27.4931, 77.6741)               # same rounded cell -> cache
    assert len(fake_owm) == 1


def test_weather_rate_limit(fake_owm):
    for k in range(weather.MAX_CALLS_PER_MINUTE):
        assert weather.get_weather(10 + k, 20) is not None
    assert weather.get_weather(80, 80) is None          # 56th call in a minute is skipped
    assert len(fake_owm) == weather.MAX_CALLS_PER_MINUTE


def test_weather_failure_is_none(monkeypatch):
    monkeypatch.setattr(settings, "openweather_api_key", "test-key")
    monkeypatch.setattr(weather, "_transport", httpx.MockTransport(lambda r: httpx.Response(503)))
    weather.reset_for_tests()
    assert weather.get_weather(1, 2) is None
    weather.reset_for_tests()


def test_rule_match_prefers_matching_genres(state):
    halloween = rule_match(state, FESTIVAL_RULES["halloween"])
    horror = state.genre_matrix[:, GENRES.index("Horror")]
    assert halloween[horror].mean() > halloween[~horror].mean() + 0.2


def test_fold_in_learns_from_ratings(state):
    """Rating Sci-Fi high and Romance low must raise predicted Sci-Fi scores."""
    scifi = [int(state.movie_ids[i]) for i in np.flatnonzero(state.genre_matrix[:, GENRES.index("Sci-Fi")]
                                                              & state.has_cf)[:5]]
    romance = [int(state.movie_ids[i]) for i in np.flatnonzero(state.genre_matrix[:, GENRES.index("Romance")]
                                                               & ~state.genre_matrix[:, GENRES.index("Sci-Fi")]
                                                               & state.has_cf)[:5]]
    ratings = [(m, 5.0) for m in scifi] + [(m, 1.0) for m in romance]
    us = compute_user_state(state, "u", ratings, set(), [], [])
    assert us.cf_norm is not None and us.content is not None
    is_scifi = state.genre_matrix[:, GENRES.index("Sci-Fi")] & state.has_cf
    is_rom = state.genre_matrix[:, GENRES.index("Romance")] & ~is_scifi & state.has_cf
    assert us.cf_pred[is_scifi].mean() > us.cf_pred[is_rom].mean() + 0.5
    cold = compute_user_state(state, "c", [], set(), [], [])
    assert cold.cf_norm is None and cold.content is None   # cold start: no CF term
    result = recommend(state, cold, prepare(state, {}), 10)
    assert len(result.items) == 10
