"""
App configuration, read from environment variables (CONTRACT section 6).

Values come from (highest priority first):
  1. real environment variables (Render dashboard, shell, tests)
  2. backend/.env
  3. <repo root>/.env
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# backend/ folder and the repo root (cinematch/)
BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent

# load_dotenv never overrides variables that are already set, so loading
# backend/.env first means it wins over the repo-root .env.
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(REPO_DIR / ".env")


def normalise_database_url(url: str) -> str:
    """Render/Heroku/Neon give 'postgres://' or 'postgresql://' URLs.
    SQLAlchemy needs the driver name, and we use psycopg 3."""
    url = url.strip()
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _resolve_dir(value: str) -> Path:
    """Relative paths (like the default './artifacts') are relative to backend/,
    so the app works no matter which folder uvicorn is started from."""
    path = Path(value)
    if not path.is_absolute():
        path = BACKEND_DIR / path
    return path.resolve()


class Settings:
    def __init__(self) -> None:
        self.database_url = normalise_database_url(os.getenv("DATABASE_URL", "sqlite:///./cinematch.db"))
        self.jwt_secret = os.getenv("JWT_SECRET", "change-me")
        self.jwt_expire_days = 7
        self.admin_emails = {
            e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()
        }
        self.openweather_api_key = os.getenv("OPENWEATHER_API_KEY", "").strip()
        cors = os.getenv("CORS_ORIGINS", "*").strip() or "*"
        self.cors_origins = ["*"] if cors == "*" else [o.strip() for o in cors.split(",") if o.strip()]
        self.artifacts_dir = _resolve_dir(os.getenv("ARTIFACTS_DIR", "./artifacts"))
        self.enable_inapp_retrain = _env_bool("ENABLE_INAPP_RETRAIN", False)
        # bcrypt cost factor. 12 is a good production value; tests lower it to stay fast.
        self.bcrypt_rounds = int(os.getenv("BCRYPT_ROUNDS", "12"))
        # The frontend folder served at "/" for local dev (if it exists)
        self.frontend_dir = REPO_DIR / "frontend"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


settings = Settings()
