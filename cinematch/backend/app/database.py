"""
Database engine + session factory (SQLAlchemy 2.x).

Works on both:
  * SQLite      (local dev, default:  sqlite:///./cinematch.db)
  * PostgreSQL  (production, via psycopg 3: postgresql+psycopg://...)
"""
from datetime import datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


def utcnow() -> datetime:
    """Timezone-aware 'now' in UTC. All timestamps in the DB are UTC."""
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite gives back naive datetimes; Postgres gives aware ones.
    Make every datetime aware (UTC) so they can be compared and serialised."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso(value: datetime | None) -> str | None:
    """Datetime -> ISO 8601 string with a 'Z' (what the frontend expects)."""
    value = as_utc(value)
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _make_engine(url: str):
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30},
                               pool_size=10, max_overflow=30)

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")      # SQLite ignores FKs unless asked
            cursor.execute("PRAGMA journal_mode=WAL")     # readers don't block the writer
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

        return engine
    # Postgres: check connections before use (Neon/Render close idle ones)
    return create_engine(url, pool_pre_ping=True, pool_recycle=300, pool_size=5, max_overflow=5)


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables that don't exist yet."""
    from app import models  # noqa: F401  (registers the tables on Base.metadata)

    Base.metadata.create_all(bind=engine)
