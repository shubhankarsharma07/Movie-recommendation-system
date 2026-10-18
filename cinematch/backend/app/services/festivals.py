"""
Festival calendar, October 2026 – December 2027.

ONE static dict: festival id -> list of dates (YYYY-MM-DD). These are the
best-known dates at the time of writing. Hindu and Islamic festivals follow
lunar calendars, so the exact day can shift by a day depending on the region
and moon sighting - a researcher will double-check and correct them later.
Multi-day festivals use their first day (e.g. the start of Navratri).
"""
from datetime import date, timedelta

from app.vocab import FESTIVAL_INFO

FESTIVAL_DATES = {
    "navratri":         ["2026-10-11", "2027-09-30"],   # Sharad Navratri, first day
    "halloween":        ["2026-10-31", "2027-10-31"],
    "diwali":           ["2026-11-08", "2027-10-29"],   # Lakshmi Puja day
    "thanksgiving":     ["2026-11-26", "2027-11-25"],   # US, 4th Thursday of November
    "christmas":        ["2026-12-25", "2027-12-25"],
    "new_year":         ["2027-01-01", "2028-01-01"],   # 2028-01-01 so late Dec 2027 still sees it
    "pongal":           ["2027-01-15"],                 # Thai Pongal
    "valentines":       ["2027-02-14"],
    "eid":              ["2027-03-10", "2027-05-17"],   # Eid al-Fitr, Eid al-Adha (moon sighting)
    "holi":             ["2027-03-22"],                 # Rangwali Holi
    "independence_day": ["2027-08-15"],                 # India
    "raksha_bandhan":   ["2027-08-17"],
    "onam":             ["2027-09-12"],                 # Thiruvonam
}


def next_date(festival_id: str, today: date) -> date | None:
    """The next date (today or later) of a festival, or None if not in the table."""
    for text in FESTIVAL_DATES.get(festival_id, []):
        day = date.fromisoformat(text)
        if day >= today:
            return day
    return None


def upcoming_festival(today: date, within_days: int = 21) -> dict | None:
    """The nearest festival happening in the next `within_days` days, e.g.
    {"id": "diwali", "label": "Diwali", "date": "2026-11-08", "days_away": 37}."""
    best = None
    limit = today + timedelta(days=within_days)
    for festival_id in FESTIVAL_DATES:
        day = next_date(festival_id, today)
        if day is not None and day <= limit and (best is None or day < best[1]):
            best = (festival_id, day)
    if best is None:
        return None
    festival_id, day = best
    return {
        "id": festival_id,
        "label": FESTIVAL_INFO[festival_id][0],
        "date": day.isoformat(),
        "days_away": (day - today).days,
    }
