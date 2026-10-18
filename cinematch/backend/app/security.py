"""
Password hashing (bcrypt) and login tokens (JWT, HS256, 7 days).

NFR-2: plaintext passwords are never stored or logged. Only the bcrypt hash
goes into the database.
"""
import base64
import hashlib
import uuid
from datetime import timedelta

import bcrypt
import jwt

from app.config import settings
from app.database import utcnow

JWT_ALGORITHM = "HS256"


def _password_bytes(password: str) -> bytes:
    """bcrypt only looks at the first 72 bytes (and the `bcrypt` package now
    raises an error for longer input). For long passwords we first squeeze
    them with SHA-256 so every character still counts."""
    raw = password.encode("utf-8")
    if len(raw) > 72:
        raw = base64.b64encode(hashlib.sha256(raw).digest())  # 44 bytes
    return raw


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=settings.bcrypt_rounds)
    return bcrypt.hashpw(_password_bytes(password), salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_password_bytes(password), password_hash.encode("utf-8"))
    except ValueError:
        return False


# A real bcrypt hash used when the email does not exist, so a failed login
# takes the same time either way (no "does this email exist?" timing leak).
_DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt(rounds=4)).decode("utf-8")


def burn_time_for_missing_user(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def create_access_token(user_id: uuid.UUID) -> str:
    now = utcnow()
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.jwt_expire_days)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID | None:
    """Return the user id inside a valid token, or None if the token is bad/expired."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
        return uuid.UUID(str(payload.get("sub")))
    except (jwt.PyJWTError, ValueError, TypeError):
        return None
