"""
Playback sessions (Module 3): FR-3.1 drop-off timestamp (AC-4), FR-3.2 rewatch
count, pause / rewind / fast-forward counters.

The frontend calls:
    start  -> when the player opens
    event  -> on pause, resume, seek back, seek forward
    stop   -> when the player closes (position = where the user dropped off)
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db, iso, utcnow
from app.deps import get_current_user, get_model_state
from app.models import Movie, PlaybackSession, User
from app.schemas import PlaybackEventIn, PlaybackStartIn, PlaybackStopIn
from app.services import rating_stats
from app.services.behavior import COMPLETE_RATIO
from app.services.cards import card_for, json_response

router = APIRouter(prefix="/api/playback", tags=["playback"])


def _own_session(db: Session, user: User, session_id: str) -> PlaybackSession:
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Playback session not found")
    session = db.get(PlaybackSession, sid)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Playback session not found")
    return session


@router.post("/start")
def start(body: PlaybackStartIn, user: User = Depends(get_current_user), state=Depends(get_model_state),
          db: Session = Depends(get_db)):
    known = (state is not None and state.idx(body.movie_id) is not None) or db.get(Movie, body.movie_id)
    if not known:
        raise HTTPException(status_code=404, detail="Movie not found")
    count = db.scalar(select(func.count(PlaybackSession.id)).where(
        PlaybackSession.user_id == user.id, PlaybackSession.movie_id == body.movie_id)) or 0
    finished_before = db.scalar(select(PlaybackSession.id).where(
        PlaybackSession.user_id == user.id, PlaybackSession.movie_id == body.movie_id,
        PlaybackSession.completed.is_(True)).limit(1)) is not None
    session = PlaybackSession(
        user_id=user.id, movie_id=body.movie_id, request_id=body.request_id, started_at=utcnow(),
        is_rewatch=finished_before,          # FR-3.2: watching again after finishing it once
        start_number=count + 1,
    )
    db.add(session)
    db.commit()
    return {"session_id": str(session.id), "is_rewatch": session.is_rewatch, "start_number": session.start_number}


@router.post("/{session_id}/event", status_code=status.HTTP_204_NO_CONTENT)
def playback_event(session_id: str, body: PlaybackEventIn, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    session = _own_session(db, user, session_id)
    if body.type == "pause":
        session.pause_count = (session.pause_count or 0) + 1
    elif body.type == "seek_back":
        session.seek_back_count = (session.seek_back_count or 0) + 1
    elif body.type == "seek_forward":
        session.seek_forward_count = (session.seek_forward_count or 0) + 1
    # "resume" needs no counter
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{session_id}/stop")
def stop(session_id: str, body: PlaybackStopIn, user: User = Depends(get_current_user),
         db: Session = Depends(get_db)):
    """AC-4: store where the user dropped off. Watching >= 90 % counts as completed."""
    session = _own_session(db, user, session_id)
    duration = body.duration_sec if body.duration_sec else None
    position = body.position_sec
    if duration:
        position = min(position, duration)
        ratio = position / duration
    else:
        ratio = 1.0 if body.completed else 0.0
    completed = bool(body.completed or ratio >= COMPLETE_RATIO)
    session.drop_off_sec = float(position)
    session.duration_sec = float(duration) if duration else None
    session.completed = completed
    session.ended_at = utcnow()
    db.commit()
    return {"session_id": str(session.id), "drop_off_sec": session.drop_off_sec,
            "completion_ratio": round(1.0 if body.completed else ratio, 4)}


@router.get("/me")
def my_sessions(user: User = Depends(get_current_user), state=Depends(get_model_state),
                db: Session = Depends(get_db)):
    sessions = db.scalars(
        select(PlaybackSession).where(PlaybackSession.user_id == user.id)
        .order_by(PlaybackSession.started_at.desc()).limit(100)
    ).all()
    stats = rating_stats.get_stats(db)
    items = []
    for s in sessions:
        card = card_for(state, db, s.movie_id, stats)
        if card is None:
            continue
        items.append({
            "session_id": str(s.id), "movie": card, "started_at": iso(s.started_at),
            "ended_at": iso(s.ended_at), "drop_off_sec": s.drop_off_sec, "duration_sec": s.duration_sec,
            "completed": bool(s.completed), "is_rewatch": bool(s.is_rewatch),
        })
    return json_response({"items": items})
