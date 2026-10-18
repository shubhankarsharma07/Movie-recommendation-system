"""
Database tables (CONTRACT section 3). ml/retrain.py reads `ratings` and
`playback_sessions`, so keep those column names exactly as they are.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, Numeric,
    String, Text, UniqueConstraint, Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(100))   # bcrypt hash, never the password
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Movie(Base):
    """A small copy of catalog.csv so ratings can have a real foreign key and
    ml/retrain.py can join on it. Filled from the current artifact version."""
    __tablename__ = "movies"

    movie_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str] = mapped_column(String(10), default="movie")
    genres: Mapped[str] = mapped_column(Text, default="")          # pipe separated: "Action|Drama"
    poster_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    backdrop_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    original_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    age_rating: Mapped[str | None] = mapped_column(String(10), nullable=True)
    runtime: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ml_rating_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    ml_rating_count: Mapped[int] = mapped_column(Integer, default=0)
    popularity_score: Mapped[float] = mapped_column(Float, default=0.0)


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (
        UniqueConstraint("user_id", "movie_id", name="uq_ratings_user_movie"),
        # FR-1.1 / FR-1.2 enforced in the database too: 0.5..5.0 in half steps.
        # (rating * 2 must be a whole number -> works the same on Postgres and SQLite)
        CheckConstraint(
            "rating >= 0.5 AND rating <= 5.0 AND rating * 2 = CAST(rating * 2 AS INTEGER)",
            name="ck_ratings_half_steps",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.movie_id"), index=True)
    rating: Mapped[float] = mapped_column(Numeric(2, 1, asdecimal=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)  # updated on re-rate


class PlaybackSession(Base):
    """One 'press play' → 'stop' session (FR-3.1 drop-off, FR-3.2 rewatch)."""
    __tablename__ = "playback_sessions"
    __table_args__ = (Index("ix_playback_user_started", "user_id", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    movie_id: Mapped[int] = mapped_column(Integer, index=True)
    request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    drop_off_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    pause_count: Mapped[int] = mapped_column(Integer, default=0)
    seek_back_count: Mapped[int] = mapped_column(Integer, default=0)
    seek_forward_count: Mapped[int] = mapped_column(Integer, default=0)
    is_rewatch: Mapped[bool] = mapped_column(Boolean, default=False)
    start_number: Mapped[int] = mapped_column(Integer, default=1)


class Event(Base):
    """Generic behaviour events: impression, details_open, select, trailer_open, search,
    filter_apply, dismiss, binge_next (CONTRACT 5.7)."""
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_user_type", "user_id", "type"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    movie_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    type: Mapped[str] = mapped_column(String(32))
    request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    row_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class RequestLog(Base):
    """NFR-3: one row per recommendation request. Kept at least 90 days."""
    __tablename__ = "request_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)     # = request_id
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    endpoint: Mapped[str] = mapped_column(String(64))
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    movie_ids: Mapped[list] = mapped_column(JSON, default=list)
    fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Dismissal(Base):
    """FR-4.5: items the user said 'not interested' to. They never come back."""
    __tablename__ = "dismissals"
    __table_args__ = (UniqueConstraint("user_id", "movie_id", name="uq_dismissals_user_movie"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    movie_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Party(Base):
    __tablename__ = "parties"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(6), unique=True, index=True)
    host_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PartyMember(Base):
    __tablename__ = "party_members"
    __table_args__ = (UniqueConstraint("party_id", "user_id", name="uq_party_members"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))


class AppState(Base):
    """Tiny key/value table for backend bookkeeping (not in the shared contract).
    Used to remember which artifact version was copied into `movies`."""
    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
