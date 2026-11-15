from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Alert, Astronaut, RiskScore
from app.schemas import CrewMember, ProfileOut, RiskHistoryOut, RiskHistoryPoint, RiskScoreOut
from app.security import CurrentUser, ensure_can_access_astronaut, require_role
from app.services.pipeline import explain_stored_reading, fusion_summary, load_baseline

router = APIRouter(tags=["Astronauts"])


def get_astronaut_or_404(db: Session, astronaut_id: str) -> Astronaut:
    astronaut = db.get(Astronaut, astronaut_id)
    if astronaut is None:
        raise HTTPException(status_code=404, detail=f"Unknown astronaut {astronaut_id}")
    return astronaut


def latest_risk(db: Session, astronaut_id: str) -> RiskScore | None:
    return db.scalar(select(RiskScore).where(RiskScore.astronaut_id == astronaut_id)
                     .order_by(RiskScore.ts.desc(), RiskScore.id.desc()).limit(1))


@router.get("/astronaut-profile/{astronaut_id}", response_model=ProfileOut,
            summary="Profile + personal baseline (Digital Twin)")
def astronaut_profile(
    astronaut_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(["astronaut", "doctor", "ground"])),
):
    ensure_can_access_astronaut(user, astronaut_id, request, db)
    astronaut = get_astronaut_or_404(db, astronaut_id)
    profile = load_baseline(db, astronaut_id)
    db.commit()
    return ProfileOut(astronaut_id=astronaut.id, name=astronaut.name,
                      mission_day=astronaut.mission_day, status=astronaut.status,
                      baseline=profile.get("baseline", {}),
                      recovery_score=profile.get("recovery_score"))


@router.get("/risk-score/{astronaut_id}", response_model=RiskScoreOut,
            summary="Latest risk score + top factors + recommendation")
def risk_score(
    astronaut_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(["astronaut", "doctor", "ground"])),
):
    ensure_can_access_astronaut(user, astronaut_id, request, db)
    get_astronaut_or_404(db, astronaut_id)
    row = latest_risk(db, astronaut_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No risk score yet for this astronaut")
    return RiskScoreOut(astronaut_id=astronaut_id, timestamp=row.ts,
                        risk_score=round(row.risk_score), level=row.level,
                        top_factors=row.top_factors_json or [],
                        recommendation=row.recommendation,
                        explanation=RiskScoreOut.explanation_from(
                            explain_stored_reading(db, row.reading_id, astronaut_id)),
                        fusion=fusion_summary(db, row.reading_id))


@router.get("/risk-history/{astronaut_id}", response_model=RiskHistoryOut,
            summary="Risk score over time, oldest first (for charts)")
def risk_history(
    astronaut_id: str,
    request: Request,
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(["astronaut", "doctor", "ground"])),
):
    ensure_can_access_astronaut(user, astronaut_id, request, db)
    get_astronaut_or_404(db, astronaut_id)
    rows = db.scalars(select(RiskScore).where(RiskScore.astronaut_id == astronaut_id)
                      .order_by(RiskScore.ts.desc(), RiskScore.id.desc()).limit(limit)).all()
    points = [RiskHistoryPoint(timestamp=r.ts, risk_score=round(r.risk_score), level=r.level)
              for r in reversed(rows)]
    return RiskHistoryOut(astronaut_id=astronaut_id, points=points)


@router.get("/crew", response_model=list[CrewMember],
            summary="Whole crew status for the Ground dashboard")
def crew(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_role(["doctor", "ground"])),
):
    open_counts = dict(db.execute(
        select(Alert.astronaut_id, func.count(Alert.id))
        .where(Alert.acknowledged.is_(False), Alert.astronaut_id.is_not(None))
        .group_by(Alert.astronaut_id)
    ).all())
    members = []
    for a in db.scalars(select(Astronaut).order_by(Astronaut.id)).all():
        r = latest_risk(db, a.id)
        members.append(CrewMember(
            astronaut_id=a.id, name=a.name, mission_day=a.mission_day, status=a.status,
            risk_score=round(r.risk_score) if r else None, level=r.level if r else None,
            last_update=r.ts if r else None, open_alerts=open_counts.get(a.id, 0),
        ))
    return members
