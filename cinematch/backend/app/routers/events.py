"""
POST /api/events — batched behaviour events from the frontend (CONTRACT 5.7):
impression, details_open, select (value = browse-to-select ms, FR-3.3),
trailer_open, search, filter_apply, dismiss, binge_next.
"""
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.database import get_db, utcnow
from app.deps import get_current_user
from app.models import Event, User
from app.schemas import EventsIn

router = APIRouter(prefix="/api", tags=["events"])


@router.post("/events", status_code=status.HTTP_204_NO_CONTENT)
def log_events(body: EventsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = utcnow()
    for e in body.events:
        db.add(Event(
            user_id=user.id, movie_id=e.movie_id, type=e.type, request_id=e.request_id,
            row_id=e.row_id, value=e.value, position_sec=e.position_sec, created_at=now,
        ))
    if body.events:
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
