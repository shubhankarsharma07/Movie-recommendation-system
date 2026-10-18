"""
Live weather from OpenWeatherMap (free tier: 60 calls/minute).

  * Only called when the browser shared its location (FR-2.2 / FR-2.4).
  * We stay under 55 calls per minute with a tiny in-process rate limiter.
  * Results are cached for 10 minutes per rounded (lat, lon) (~11 km grid).
  * Any problem (no API key, limit reached, timeout, bad answer) -> None, and
    the API silently drops the weather signal. Never an error for the user.
"""
import logging
import threading
import time
from collections import deque

import httpx

from app.config import settings
from app.vocab import WEATHER_INFO

log = logging.getLogger("cinematch.weather")

OWM_URL = "https://api.openweathermap.org/data/2.5/weather"
MAX_CALLS_PER_MINUTE = 55
CACHE_SECONDS = 600
TIMEOUT_SECONDS = 3.0

# OpenWeatherMap "main" group -> our WEATHER vocabulary
MAIN_TO_WEATHER = {
    "Clear": "sunny",
    "Clouds": "cloudy",
    "Rain": "rainy",
    "Drizzle": "rainy",
    "Thunderstorm": "stormy",
    "Squall": "stormy",
    "Tornado": "stormy",
    "Snow": "snowy",
    "Mist": "foggy", "Fog": "foggy", "Haze": "foggy", "Smoke": "foggy",
    "Dust": "foggy", "Sand": "foggy", "Ash": "foggy",
}

_lock = threading.Lock()
_call_times: deque = deque()          # timestamps of calls in the last 60 s
_cache: dict[tuple, tuple] = {}       # (lat, lon) -> (expires_at, result)
_transport = None                     # tests can plug in an httpx.MockTransport


def map_weather(main: str, temp_c: float | None) -> str:
    """OWM main group (+ temperature) -> one of WEATHER.
    Temperature only overrides calm skies: rain/storm/snow are more important
    for the mood than the thermometer (>32 °C -> hot, <10 °C -> cold)."""
    weather = MAIN_TO_WEATHER.get(main, "cloudy")
    if temp_c is not None and weather in ("sunny", "cloudy", "foggy"):
        if temp_c > 32:
            return "hot"
        if temp_c < 10:
            return "cold"
    return weather


def _allow_call() -> bool:
    now = time.monotonic()
    with _lock:
        while _call_times and now - _call_times[0] > 60:
            _call_times.popleft()
        if len(_call_times) >= MAX_CALLS_PER_MINUTE:
            return False
        _call_times.append(now)
        return True


def get_weather(lat: float, lon: float) -> dict | None:
    """Current weather dict for the CONTRACT 5.5 response, or None."""
    if not settings.openweather_api_key:
        return None
    key = (round(lat, 1), round(lon, 1))
    now = time.monotonic()
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] > now:
            return cached[1]
    if not _allow_call():
        log.warning("OpenWeatherMap rate limit reached - skipping weather")
        return None
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, transport=_transport) as client:
            resp = client.get(OWM_URL, params={"lat": lat, "lon": lon, "units": "metric",
                                               "appid": settings.openweather_api_key})
        resp.raise_for_status()
        data = resp.json()
        main = data["weather"][0]["main"]
        temp = data.get("main", {}).get("temp")
        temp = float(temp) if temp is not None else None
        weather_id = map_weather(main, temp)
        result = {
            "id": weather_id,
            "label": WEATHER_INFO[weather_id][0],
            "temp_c": round(temp, 1) if temp is not None else None,
            "city": data.get("name") or None,
            "description": data["weather"][0].get("description", main.lower()),
            "source": "live",
        }
    except Exception as exc:  # network error, timeout, 401, 429, unexpected JSON ...
        log.warning("weather lookup failed: %s", type(exc).__name__)
        return None
    with _lock:
        _cache[key] = (now + CACHE_SECONDS, result)
        if len(_cache) > 5000:   # keep memory bounded
            _cache.clear()
    return result


def reset_for_tests() -> None:
    with _lock:
        _cache.clear()
        _call_times.clear()
