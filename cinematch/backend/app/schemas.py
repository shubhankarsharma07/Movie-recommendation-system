"""
Request bodies (Pydantic v2). Responses are plain dicts built in the routers,
shaped exactly like CONTRACT section 5.
"""
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.vocab import FESTIVALS, GENRES, OCCASIONS, TIME_OF_DAY, WEATHER, time_of_day_for_hour

WeatherId = Literal["sunny", "cloudy", "rainy", "stormy", "snowy", "foggy", "hot", "cold"]
TimeOfDay = Literal["morning", "afternoon", "evening", "night", "late_night"]
OccasionId = Literal["date_night", "family_night", "friends_hangout", "solo_chill", "kids_time",
                     "late_night_thrills", "rainy_day_in", "weekend_binge"]
FestivalId = Literal["diwali", "holi", "navratri", "eid", "christmas", "new_year", "halloween",
                     "valentines", "raksha_bandhan", "independence_day", "onam", "pongal", "thanksgiving"]
EmotionId = Literal["joy", "sadness", "fear", "anger", "surprise", "disgust", "neutral"]
AgeRating = Literal["U", "UA 7+", "UA 13+", "UA 16+", "A"]
# Extra (optional) home-row presets that have no normal Context field. See rules.PRESET_RULES.
PresetId = Literal["trending", "acclaimed", "hidden_gems", "mind_bending"]

# sanity checks that the Literal types above match the shared vocabularies
assert set(WeatherId.__args__) == set(WEATHER)
assert set(TimeOfDay.__args__) == set(TIME_OF_DAY)
assert set(OccasionId.__args__) == set(OCCASIONS)
assert set(FestivalId.__args__) == set(FESTIVALS)


def _lenient_uuid(value: Any) -> uuid.UUID | None:
    """request_id fields are optional links back to a recommendation request.
    A missing or malformed id should not fail the whole call, so we drop it."""
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


# ----------------------------------------------------------------------------- auth
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    display_name: str = Field(min_length=1, max_length=50)

    @field_validator("display_name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("display_name cannot be empty")
        return v


class LoginIn(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=128)


# ----------------------------------------------------------------------------- ratings
class RatingIn(BaseModel):
    movie_id: int
    # Typed as Any on purpose: FR-1.2 wants our own 400 message for ANY bad value
    # (5.5, 4.3, "abc", null ...), not a generic validation error.
    rating: Any = None


# ----------------------------------------------------------------------------- context
class Context(BaseModel):
    """CONTRACT 5.6 Context object. Every field is optional."""
    model_config = ConfigDict(extra="ignore")

    weather: WeatherId | None = None
    time_of_day: TimeOfDay | None = None
    hour: int | None = Field(default=None, ge=0, le=23)
    time_available_min: int | None = Field(default=None, ge=1, le=1440)
    occasion: OccasionId | None = None
    festival: FestivalId | None = None
    reference_movie_ids: list[int] = Field(default_factory=list, max_length=10)
    directors: list[str] = Field(default_factory=list, max_length=10)
    actors: list[str] = Field(default_factory=list, max_length=10)
    language: str | None = Field(default=None, max_length=10)
    max_age_rating: AgeRating | None = None
    franchise_mode: Literal["any", "only", "exclude"] | None = None
    nostalgia_decade: int | None = Field(default=None, ge=1900, le=2030)
    start_emotion: EmotionId | None = None
    end_emotion: EmotionId | None = None
    genres: list[str] = Field(default_factory=list, max_length=19)
    content_type: Literal["any", "movie", "series"] | None = None
    preset: PresetId | None = None   # backend addition, only used by some /api/home rows

    @field_validator("genres")
    @classmethod
    def _known_genres(cls, v: list[str]) -> list[str]:
        lookup = {g.lower(): g for g in GENRES}
        out = []
        for g in v:
            name = lookup.get(str(g).strip().lower())
            if name is None:
                raise ValueError(f"unknown genre '{g}'")
            if name not in out:
                out.append(name)
        return out

    @field_validator("directors", "actors")
    @classmethod
    def _clean_names(cls, v: list[str]) -> list[str]:
        return [s.strip() for s in v if s and s.strip()]

    @field_validator("language")
    @classmethod
    def _clean_language(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        return v or None

    @field_validator("nostalgia_decade")
    @classmethod
    def _floor_decade(cls, v: int | None) -> int | None:
        return None if v is None else (v // 10) * 10

    def cleaned(self) -> dict:
        """The context as a plain dict without empty values, with time_of_day
        filled in from `hour` when only the hour was sent."""
        data = self.model_dump(exclude_none=True)
        data = {k: v for k, v in data.items() if v != [] and v != ""}
        if data.get("franchise_mode") == "any":
            data.pop("franchise_mode")
        if data.get("content_type") == "any":
            data.pop("content_type")
        if "time_of_day" not in data and "hour" in data:
            data["time_of_day"] = time_of_day_for_hour(data["hour"])
        return data


class RecommendationIn(BaseModel):
    context: Context = Field(default_factory=Context)
    limit: int = Field(default=20, ge=1)

    @field_validator("limit")
    @classmethod
    def _max_20(cls, v: int) -> int:
        return min(v, 20)  # FR-4.2: at most 20 items


# ----------------------------------------------------------------------------- playback / events
class PlaybackStartIn(BaseModel):
    movie_id: int
    request_id: uuid.UUID | None = None

    @field_validator("request_id", mode="before")
    @classmethod
    def _request_id(cls, v):
        return _lenient_uuid(v)


class PlaybackEventIn(BaseModel):
    type: Literal["pause", "resume", "seek_back", "seek_forward"]
    position_sec: float | None = Field(default=None, ge=0)


class PlaybackStopIn(BaseModel):
    position_sec: float = Field(ge=0)
    duration_sec: float | None = Field(default=None, ge=0)
    completed: bool = False


EventType = Literal["impression", "details_open", "select", "trailer_open", "search",
                    "filter_apply", "dismiss", "binge_next"]


class EventIn(BaseModel):
    type: EventType
    movie_id: int | None = None
    request_id: uuid.UUID | None = None
    row_id: str | None = Field(default=None, max_length=64)
    value: float | None = None
    position_sec: float | None = None

    @field_validator("request_id", mode="before")
    @classmethod
    def _request_id(cls, v):
        return _lenient_uuid(v)


class EventsIn(BaseModel):
    events: list[EventIn] = Field(default_factory=list, max_length=500)


# ----------------------------------------------------------------------------- party
class PartyCreateIn(BaseModel):
    member_emails: list[str] = Field(default_factory=list, max_length=20)
