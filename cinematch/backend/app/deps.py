"""
FastAPI dependencies shared by the routers: DB session, current user, admin
check, and the live model state.
"""
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User
from app.security import decode_access_token
from app.services.model_store import store

USER_NOT_IDENTIFIED = "User could not be identified"   # FR-4.1 exact text


def _user_from_header(authorization: str | None, db: Session) -> User | None:
    """'Bearer <jwt>' -> User, or None if missing/invalid/expired/unknown."""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    user_id = decode_access_token(token.strip())
    if user_id is None:
        return None
    return db.get(User, user_id)


def get_current_user(authorization: str | None = Header(default=None),
                     db: Session = Depends(get_db)) -> User:
    """Protected endpoints: 401 without a valid token."""
    user = _user_from_header(authorization, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_optional_user(authorization: str | None = Header(default=None),
                      db: Session = Depends(get_db)) -> User | None:
    """Public endpoints that personalise a little when logged in."""
    return _user_from_header(authorization, db)


def get_user_for_recommendations(authorization: str | None = Header(default=None),
                                 db: Session = Depends(get_db)) -> User:
    """FR-4.1: /api/recommendations answers 400 (not 401) when the user is unknown."""
    user = _user_from_header(authorization, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=USER_NOT_IDENTIFIED)
    return user


def is_admin(user: User) -> bool:
    """Admin = flagged at registration (first user) or listed in ADMIN_EMAILS."""
    return bool(user.is_admin) or user.email.lower() in settings.admin_emails


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


def get_model_state():
    """The live artifact state (may be None). Also triggers the cheap 30-second
    'did current.txt change?' check for hot reloading."""
    store.maybe_reload()
    return store.state
