"""
Watch-party mode (CONTRACT 5.8): one list that blends 2+ people's tastes.

Strategy ("average without misery", see recommender.party_recommend):
each member's scores are z-normalised, averaged, minus 0.5 x their spread
(disagreement penalty), and titles any member with ratings is predicted to
rate below 2.5 are dropped.
"""
import secrets
import time

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db, utcnow
from app.deps import get_current_user, get_model_state
from app.models import Party, PartyMember, User
from app.schemas import PartyCreateIn, RecommendationIn
from app.services import rating_stats
from app.services.cards import json_response, movie_ids_of, rec_items, user_json, users_json
from app.services.logging import log_recommendation
from app.services.recommender import (
    TRENDING, RecResult, UserState, build_user_state, db_popularity_fallback, engine_slot,
    party_recommend, popularity_fallback, prepare,
)
from app.routers.recommend import response_body

router = APIRouter(prefix="/api/party", tags=["party"])

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O or 1/I mix-ups


def _new_code(db: Session) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        if db.scalar(select(Party.id).where(Party.code == code)) is None:
            return code
    raise HTTPException(status_code=503, detail="Could not create a party code, please retry")


def _get_party(db: Session, code: str) -> Party:
    party = db.scalar(select(Party).where(Party.code == code.strip().upper()))
    if party is None:
        raise HTTPException(status_code=404, detail="Party not found")
    return party


def _members(db: Session, party: Party) -> list[User]:
    return list(db.scalars(
        select(User).join(PartyMember, PartyMember.user_id == User.id)
        .where(PartyMember.party_id == party.id).order_by(User.created_at)
    ).all())


def party_json(db: Session, party: Party) -> dict:
    host = db.get(User, party.host_id)
    return {"code": party.code, "host": user_json(db, host), "members": users_json(db, _members(db, party))}


@router.post("")
def create_party(body: PartyCreateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    emails = list(dict.fromkeys(e.strip().lower() for e in body.member_emails if e and e.strip()))
    found = list(db.scalars(select(User).where(User.email.in_(emails))).all()) if emails else []
    unknown = sorted(set(emails) - {u.email for u in found})
    if unknown:
        raise HTTPException(status_code=404, detail="Unknown emails: " + ", ".join(unknown))
    party = Party(code=_new_code(db), host_id=user.id, created_at=utcnow())
    db.add(party)
    db.flush()
    for member_id in dict.fromkeys([user.id] + [u.id for u in found]):   # host is always a member
        db.add(PartyMember(party_id=party.id, user_id=member_id))
    db.commit()
    return party_json(db, party)


@router.post("/{code}/join")
def join_party(code: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    party = _get_party(db, code)
    already = db.scalar(select(PartyMember.id).where(PartyMember.party_id == party.id,
                                                     PartyMember.user_id == user.id))
    if already is None:
        db.add(PartyMember(party_id=party.id, user_id=user.id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return party_json(db, party)


@router.get("/{code}")
def get_party(code: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return party_json(db, _get_party(db, code))


def _display_names(users: list[User]) -> list[str]:
    """member_scores is keyed by display name; make duplicates unique."""
    names, seen = [], {}
    for u in users:
        name = u.display_name
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
        else:
            seen[name] = 1
        names.append(name)
    return names


@router.post("/{code}/recommendations")
def party_recommendations(code: str, request: Request, body: RecommendationIn | None = None,
                          user: User = Depends(get_current_user), state=Depends(get_model_state),
                          db: Session = Depends(get_db)):
    started = time.perf_counter()
    body = body or RecommendationIn()
    party = _get_party(db, code)
    users = _members(db, party)
    if user.id not in {u.id for u in users}:
        raise HTTPException(status_code=403, detail="Join the party first")
    ctx = body.context.cleaned()
    result: RecResult | None = None

    with engine_slot():
        if state is not None:
            names = _display_names(users)
            members = [(name, build_user_state(db, u.id, state)) for name, u in zip(names, users)]
            prep = prepare(state, ctx)
            try:
                result = party_recommend(state, members, prep, body.limit)
            except Exception:
                result = None
            if result is None or not result.items:
                # fallback: popularity, excluding anything any member dismissed
                combined = UserState(dismissed_mask=np.zeros(state.n, bool), rated_mask=np.ones(state.n, bool))
                for _, us in members:
                    combined.dismissed_mask |= us.dismissed_mask
                    combined.rated_mask &= us.rated_mask
                result = popularity_fallback(state, combined, prep, body.limit)
                for k, (i, score, _reason) in enumerate(result.items):
                    scores = {name: round(float(us.rated.get(i, us.cf_pred[i] if us.cf_pred is not None else
                                                             state.global_mean)), 1)
                              for name, us in members}
                    result.items[k] = (i, score, TRENDING, scores)
        else:
            result = db_popularity_fallback(db, ctx, set(), set(), body.limit)
            result.items = [(m, s, r, {}) for m, s, r in result.items]

    items = rec_items(state, result, rating_stats.get_stats(db))
    request_id = request.state.request_id
    latency = (time.perf_counter() - started) * 1000
    log_recommendation(db, request_id, user.id, "/api/party/{code}/recommendations",
                       {**result.context_used, "party": party.code, "members": len(users)},
                       movie_ids_of(items), result.fallback, latency)
    return json_response(response_body(request_id, result, items))
