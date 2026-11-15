from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Alert
from app.schemas import AlertOut, AlertType
from app.security import CurrentUser, client_ip, log_security_event, require_role
from app.services.alerts import ALERT_ORDER

router = APIRouter(tags=["Alerts"])


@router.get(
    "/alerts",
    response_model=list[AlertOut],
    summary="Alerts, Emergency first (unacknowledged -> severity -> newest)",
    description="Astronauts see only their own health alerts; doctors see health alerts; "
                "ground/admin see health + security.",
)
def list_alerts(
    request: Request,
    astronaut_id: str | None = None,
    type: AlertType | None = None,  # noqa: A002 - name fixed by the contract
    acknowledged: bool | None = None,
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(["astronaut", "doctor", "ground"])),
):
    if user.role in ("astronaut", "doctor"):
        if type == "security":
            log_security_event(db, "forbidden", user.username, client_ip(request),
                               "requested security alerts")
            raise HTTPException(status_code=403, detail="Security alerts are for Ground/Admin")
        type = "health"
    if user.role == "astronaut":
        if astronaut_id and astronaut_id != user.astronaut_id:
            raise HTTPException(status_code=403, detail="Astronauts can only access their own data")
        astronaut_id = user.astronaut_id

    q = select(Alert)
    if astronaut_id:
        q = q.where(Alert.astronaut_id == astronaut_id)
    if type:
        q = q.where(Alert.type == type)
    if acknowledged is not None:
        q = q.where(Alert.acknowledged.is_(acknowledged))
    return db.scalars(q.order_by(*ALERT_ORDER).limit(limit)).all()


@router.post("/alerts/{alert_id}/ack", response_model=AlertOut,
             summary="Acknowledge an alert (doctor, ground)")
def acknowledge_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role(["doctor", "ground"])),
):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not alert.acknowledged:
        alert.acknowledged = True
        alert.acknowledged_by = user.username
        alert.acknowledged_at = datetime.now(timezone.utc)
        db.commit()
    return alert
