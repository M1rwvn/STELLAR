from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import SecurityEvent
from app.schemas import LoginIn, SecurityEventOut, TokenOut
from app.security import (
    AccountLocked,
    CurrentUser,
    astronaut_id_for_user,
    authenticate,
    client_ip,
    create_access_token,
    get_current_user,
    require_role,
)

router = APIRouter(tags=["Auth & Security"])


@router.post("/login", response_model=TokenOut, summary="Log in and get a JWT")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    try:
        user = authenticate(db, body.username, body.password, client_ip(request))
    except AccountLocked:
        raise HTTPException(status_code=status.HTTP_423_LOCKED,
                            detail="Account temporarily locked after too many failed logins")
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid username or password")
    astronaut_id = astronaut_id_for_user(db, user)
    token, expires_in = create_access_token(user, astronaut_id)
    return TokenOut(access_token=token, role=user.role, astronaut_id=astronaut_id,
                    expires_in=expires_in)


@router.get("/me", summary="Who am I (decoded from the token)")
def me(user: CurrentUser = Depends(get_current_user)):
    return {"username": user.username, "role": user.role, "astronaut_id": user.astronaut_id}


@router.get("/security-events", response_model=list[SecurityEventOut],
            summary="Security log for the Ground dashboard / IDS (ground, admin)")
def security_events(
    event_type: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_role(["ground"])),
):
    q = select(SecurityEvent).order_by(SecurityEvent.ts.desc(), SecurityEvent.id.desc()).limit(limit)
    if event_type:
        q = q.where(SecurityEvent.event_type == event_type)
    return db.scalars(q).all()
