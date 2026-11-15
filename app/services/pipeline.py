"""POST /health-data flow (brief section 3):

1. Validate payload (Pydantic) + check role/permissions      -> router
2. baseline = get_baseline(astronaut_id)                     # AI 1
3. vector = build_health_vector(wearable, suit, vision, baseline)  # AI 3
   + history features from the last 7 days (AI 1 online_features: the SAME
     rolling means / sleep debt / stress / deviation columns as the training data)
4. risk = predict_risk(vector)                               # AI 2
   + plain-English explanation sentences (AI 1 explain_deviation)
5. Store the reading and the risk score
6. If level is High Risk or Emergency -> create Alert (Emergency first)
7. Return the risk result
"""
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai
from app.models import Alert, Astronaut, Baseline, HealthReading, RiskScore
from app.schemas import HealthDataIn
from app.services.alerts import maybe_create_health_alert
from app.services import space_weather
from app.services.comm_link import comm_link

log = logging.getLogger("stellar.flow")

HISTORY_HOURS = 168  # the longest training window (7 days)


@dataclass
class PipelineResult:
    reading: HealthReading
    risk_row: RiskScore
    risk: dict
    alert: Alert | None
    imputed: list[str]
    explanation: dict | None = None


def load_baseline(db: Session, astronaut_id: str) -> dict:
    """Baseline profile from the DB (stored at startup from AI 1); falls back to AI 1."""
    row = db.get(Baseline, astronaut_id)
    if row is not None:
        return row.data_json
    profile = ai.get_baseline(astronaut_id)
    db.add(Baseline(astronaut_id=astronaut_id, data_json=profile,
                    updated_at=datetime.now(timezone.utc)))
    return profile


def recent_history(db: Session, astronaut_id: str, until: datetime) -> list[dict]:
    """The astronaut's stored readings in (until - 7 days, until], oldest first."""
    since = until - timedelta(hours=HISTORY_HOURS)
    rows = db.execute(
        select(HealthReading.ts, HealthReading.wearable_json)
        .where(HealthReading.astronaut_id == astronaut_id,
               HealthReading.ts > since, HealthReading.ts <= until)
        .order_by(HealthReading.ts, HealthReading.id)
    ).all()
    return [{"timestamp": ts, **(wearable or {})} for ts, wearable in rows]


SMOOTH_HOURS = 24      # AI 2 trains on 24 h rolling means of the deviations ("<feature>_s")
SMOOTH_MIN_READINGS = 6


def add_24h_means(db: Session, astronaut_id: str, until: datetime, vector: dict) -> None:
    """Add `<k>_s` = mean of `<k>` over the readings in (until - 24 h, until], for every deviation
    column (`*_pct_dev`, `temp_delta_c`). Uses the vectors already stored for earlier readings, so the
    values equal AI 2's training feature (pandas rolling mean, >= 6 readings, missing values skipped).
    """
    keys = [k for k in vector if k.endswith("_pct_dev") or k == "temp_delta_c"]
    if not keys:
        return
    since = until - timedelta(hours=SMOOTH_HOURS)
    earlier = db.execute(
        select(HealthReading.vector_json)
        .where(HealthReading.astronaut_id == astronaut_id,
               HealthReading.ts > since, HealthReading.ts < until)
    ).scalars().all()
    for k in keys:
        values = [v[k] for v in earlier if v and isinstance(v.get(k), (int, float))]
        if isinstance(vector.get(k), (int, float)):
            values.append(vector[k])
        vector[f"{k}_s"] = (round(sum(values) / len(values), 4)
                            if len(values) >= SMOOTH_MIN_READINGS else None)


def _json_safe(value):
    """NaN/inf are not valid JSON (PostgreSQL rejects them): store them as null."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def explain_stored_reading(db: Session, reading_id: int | None, astronaut_id: str) -> dict | None:
    """Explanation for a stored reading (recomputed, so nothing extra is stored)."""
    reading = db.get(HealthReading, reading_id) if reading_id else None
    if reading is None or not reading.wearable_json:
        return None
    return ai.explain(reading.wearable_json, load_baseline(db, astronaut_id))


VITAL_KEYS = ("hr", "hrv", "spo2", "resp_rate", "temp", "sleep_hours", "sleep_quality", "activity")
SUIT_KEYS = ("cabin_pressure_kpa", "suit_temp_c", "o2_pct", "co2_pct")
VISION_KEYS = ("posture_score", "movement_quality", "fatigue_indicator")


def fusion_summary(db: Session, reading_id: int | None) -> dict | None:
    """The suit, camera and fatigue values AI 3 put in the stored vector of one reading."""
    reading = db.get(HealthReading, reading_id) if reading_id else None
    v = reading.vector_json if reading is not None else None
    if not v:
        return None
    risk = v.get("fatigue_risk")              # AI 3 gives "Low" / "Medium" / "High"
    level = v.get("fatigue_level") or (risk if isinstance(risk, str) else None)
    return {"vitals": {k: v.get(k) for k in VITAL_KEYS}, "suit": {k: v.get(k) for k in SUIT_KEYS}, "vision": {k: v.get(k) for k in VISION_KEYS},
            "fatigue_risk": risk if isinstance(risk, (int, float)) else None, "fatigue_level": level,
            "environment_flags": v.get("environment_flags") or [], "imputed": v.get("imputed") or []}


def process_health_data(db: Session, astronaut: Astronaut, payload: HealthDataIn) -> PipelineResult:
    wearable = payload.wearable.model_dump(exclude_none=True)
    suit = payload.suit.model_dump(exclude_none=True)
    vision = payload.vision.model_dump(exclude_none=True)

    baseline = load_baseline(db, astronaut.id)                              # AI 1
    vector = ai.build_health_vector(wearable, suit, vision, baseline)       # AI 3
    imputed = list(vector.get("imputed", []))
    history = recent_history(db, astronaut.id, payload.timestamp)
    history.append({"timestamp": payload.timestamp, **wearable})
    vector.update(ai.history_features(history, baseline))                   # AI 1 (training parity)
    vector = _json_safe(vector)
    add_24h_means(db, astronaut.id, payload.timestamp, vector)              # AI 2 inputs (training parity)
    risk = ai.predict_risk(vector)                                          # AI 2
    explanation = ai.explain(wearable, baseline) if wearable else None      # AI 1

    reading = HealthReading(astronaut_id=astronaut.id, ts=payload.timestamp,
                            wearable_json=wearable, suit_json=suit, vision_json=vision,
                            vector_json=vector)
    db.add(reading)
    db.flush()
    risk_row = RiskScore(astronaut_id=astronaut.id, reading_id=reading.id,
                         ts=payload.timestamp, risk_score=risk["risk_score"],
                         level=risk["level"], top_factors_json=risk["top_factors"],
                         recommendation=risk["recommendation"])
    db.add(risk_row)

    astronaut.status = risk["level"]
    if payload.mission_day is not None:
        astronaut.mission_day = payload.mission_day

    alert = maybe_create_health_alert(db, astronaut, risk, explanation)
    # NASA space weather at this mission time (crew-wide, once per event)
    sw_alert = space_weather.maybe_create_alert(db, space_weather.nasa_time(payload.timestamp, payload.mission_day))
    db.commit()

    log.info("%s %s -> baseline -> fusion -> risk %s %s%s", astronaut.id,
             payload.timestamp.isoformat(), risk["risk_score"], risk["level"],
             f" -> ALERT #{alert.id} {alert.severity}" if alert else "")

    # Downlink to Ground Control: Emergency jumps the queue
    comm_link.enqueue("risk", risk["level"], astronaut.id,
                      f"{astronaut.name} risk {risk['risk_score']} {risk['level']}")
    if alert is not None:
        comm_link.enqueue("alert", risk["level"], astronaut.id, alert.message)
    if sw_alert is not None:
        comm_link.enqueue("space wx", {"critical": "Emergency", "high": "High Risk"}.get(sw_alert.severity, "Attention"),
                          None, sw_alert.message)

    return PipelineResult(reading, risk_row, risk, alert, imputed, explanation)
