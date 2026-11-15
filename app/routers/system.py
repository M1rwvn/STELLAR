from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.ai import ai_status
from app.database import get_db
from app.models import Astronaut, HealthReading
from app.security import CurrentUser, require_role
from app.services import space_weather
from app.services.comm_link import comm_link

router = APIRouter(tags=["System"])


@router.get("/health", summary="Quick liveness check (no auth)")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok, "ai": ai_status()}


@router.get("/comm/status", summary="Simulated space-to-ground link: queue + delivered log")
def comm_status(
    limit: int = 50,
    _: CurrentUser = Depends(require_role(["ground", "doctor"])),
):
    return comm_link.status(limit)


class BlackoutIn(BaseModel):
    seconds: float = Field(20, gt=0, le=600)


@router.post("/comm/blackout",
             summary="Simulate loss of signal; queued messages are sent Emergency first after it")
def comm_blackout(body: BlackoutIn, _: CurrentUser = Depends(require_role(["ground"]))):
    until = comm_link.start_blackout(body.seconds)
    return {"blackout_until": until.isoformat()}


@router.get("/space-weather",
            summary="Space weather at mission time, from NASA data (OMNIWeb Kp/Dst + DONKI events)")
def space_weather_now(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_role(["astronaut", "doctor", "ground"])),
):
    """Mission days 1-60 replay the real space weather of 2024-08-25 .. 2024-10-23 (solar maximum)."""
    latest = db.execute(select(HealthReading.ts, Astronaut.mission_day)
                        .join(Astronaut, Astronaut.id == HealthReading.astronaut_id)
                        .order_by(HealthReading.ts.desc(), HealthReading.id.desc()).limit(1)).first()
    if latest is None:
        t, day = space_weather.NASA_START, 1
    else:
        t, day = space_weather.nasa_time(latest[0], latest[1]), latest[1]
    out = space_weather.conditions(t)
    out["mission_day"] = day
    return out
