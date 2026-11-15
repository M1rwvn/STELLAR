from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Astronaut
from app.schemas import AlertOut, HealthDataIn, HealthDataOut
from app.security import CurrentUser, ensure_can_access_astronaut, require_role
from app.services.pipeline import process_health_data

router = APIRouter(tags=["Health data"])


@router.post(
    "/health-data",
    response_model=HealthDataOut,
    summary="Ingest one reading -> baseline -> fusion -> risk -> store -> alert",
    description="Called by the wearable device / replay script. Missing sensor values are "
                "allowed; fusion fills them and lists them in `imputed`.",
)
def post_health_data(
    payload: HealthDataIn,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(["astronaut", "device"])),
):
    ensure_can_access_astronaut(user, payload.astronaut_id, request, db)
    astronaut = db.get(Astronaut, payload.astronaut_id)
    if astronaut is None:
        raise HTTPException(status_code=404, detail=f"Unknown astronaut {payload.astronaut_id}")

    result = process_health_data(db, astronaut, payload)
    return HealthDataOut(
        reading_id=result.reading.id,
        astronaut_id=astronaut.id,
        timestamp=result.risk_row.ts,
        risk_score=result.risk["risk_score"],
        level=result.risk["level"],
        top_factors=result.risk["top_factors"],
        recommendation=result.risk["recommendation"],
        explanation=HealthDataOut.explanation_from(result.explanation),
        alert=AlertOut.model_validate(result.alert) if result.alert else None,
        imputed=result.imputed,
    )
