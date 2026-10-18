"""
/api/auth — register, login, me (CONTRACT 5.1).

NFR-2: passwords are only ever hashed with bcrypt; they are never stored,
returned or logged.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db, utcnow
from app.deps import get_current_user
from app.models import User
from app.schemas import LoginIn, RegisterIn
from app.security import burn_time_for_missing_user, create_access_token, hash_password, verify_password
from app.services.cards import user_json

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _token_response(db: Session, user: User) -> dict:
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "user": user_json(db, user),
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    # The very first account becomes the admin (plus anyone in ADMIN_EMAILS).
    first_user = (db.scalar(select(func.count(User.id))) or 0) == 0
    user = User(
        email=email,
        display_name=body.display_name,
        password_hash=hash_password(body.password),
        is_admin=first_user or email in settings.admin_emails,
        created_at=utcnow(),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:   # two sign-ups with the same email at the same moment
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    db.refresh(user)
    return _token_response(db, user)


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        burn_time_for_missing_user(body.password)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    return _token_response(db, user)


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return user_json(db, user)
