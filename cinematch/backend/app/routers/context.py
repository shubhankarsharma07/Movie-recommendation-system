"""
GET /api/context — weather + time of day + upcoming festival (FR-2.2 .. FR-2.4).

  * `hour` is the browser's local hour (the server runs in UTC).
  * No lat/lon (location permission denied) -> no weather call at all,
    weather_status "no_location"; time of day and manual filters still work.
  * Weather lookup failed / no API key / rate limit -> weather null,
    weather_status "unavailable". Never an error.
"""
from datetime import date, datetime, timezone

from fastapi import APIRouter

from app.services.festivals import upcoming_festival
from app.services.weather import get_weather
from app.vocab import time_of_day_for_hour

router = APIRouter(prefix="/api", tags=["context"])


def _float_or_none(value: str | None, low: float, high: float) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if low <= number <= high else None


def build_context_info(lat: str | None, lon: str | None, hour: str | None) -> dict:
    lat_f = _float_or_none(lat, -90, 90)
    lon_f = _float_or_none(lon, -180, 180)
    hour_f = _float_or_none(hour, 0, 23)
    hour_i = int(hour_f) if hour_f is not None else datetime.now(timezone.utc).hour

    if lat_f is None or lon_f is None:
        weather, weather_status = None, "no_location"
    else:
        weather = get_weather(lat_f, lon_f)
        weather_status = "live" if weather else "unavailable"

    return {
        "weather": weather,
        "time_of_day": time_of_day_for_hour(hour_i),
        "hour": hour_i,
        "upcoming_festival": upcoming_festival(date.today()),
        "weather_status": weather_status,
    }


@router.get("/context")
def get_context(lat: str | None = None, lon: str | None = None, hour: str | None = None):
    return build_context_info(lat, lon, hour)
