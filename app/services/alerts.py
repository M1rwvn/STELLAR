"""Alert rules: High Risk / Emergency readings create alerts automatically."""
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.models import Alert, Astronaut

SEVERITY_FOR_LEVEL = {"Emergency": "critical", "High Risk": "high"}
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

HEADLINES = {
    "sleep_hours": "Possible fatigue - sleep well below personal baseline",
    "sleep_quality": "Poor sleep quality",
    "fatigue_risk": "Possible fatigue detected",
    "fatigue_indicator": "Possible fatigue detected",
    "hr": "Elevated heart rate",
    "hrv": "Low HRV (stress / poor recovery)",
    "spo2": "Low blood oxygen",
    "temp": "Elevated body temperature",
    "resp_rate": "Abnormal breathing rate",
    "activity": "Activity well below baseline",
    "co2_pct": "High CO2 level",
    "o2_pct": "Low O2 level",
    "cabin_pressure_kpa": "Pressure anomaly",
    "suit_temp_c": "Suit temperature anomaly",
}

# Unacknowledged first, then most severe, then newest = "Emergency first"
ALERT_ORDER = (
    Alert.acknowledged.asc(),
    case(SEVERITY_RANK, value=Alert.severity, else_=9).asc(),
    Alert.created_at.desc(),
    Alert.id.desc(),
)


def build_message(astronaut: Astronaut, risk: dict, explanation: dict | None = None) -> str:
    reasons = (explanation or {}).get("reasons") or []
    if reasons:
        # AI 1's sentences, rewritten from the astronaut's view ("your normal") to Ground's
        details = "; ".join(r["text"]["en"].replace("your normal", "personal normal")
                            for r in reasons[:2])
        return (f"{risk['level']}: {astronaut.name} ({astronaut.id}) - {details}. "
                f"Risk {risk['risk_score']}/100")
    factors = risk.get("top_factors") or []
    headline = HEADLINES.get(factors[0]["feature"], "Health risk detected") if factors else "Health risk detected"
    details = ", ".join(f"{f['feature']} {f['change_pct']:+.0f}%" for f in factors)
    return (f"{risk['level']}: {astronaut.name} ({astronaut.id}) - {headline}. "
            f"Risk {risk['risk_score']}/100" + (f" [{details}]" if details else ""))


def maybe_create_health_alert(db: Session, astronaut: Astronaut, risk: dict,
                              explanation: dict | None = None) -> Alert | None:
    """Create an alert for High Risk / Emergency.

    De-duplicated: if the astronaut already has an open (unacknowledged) health
    alert at the same or higher severity, no new alert is created. An
    escalation (high -> critical) always creates a new one.
    """
    severity = SEVERITY_FOR_LEVEL.get(risk["level"])
    if severity is None:
        return None

    open_alert = db.scalar(
        select(Alert)
        .where(Alert.astronaut_id == astronaut.id, Alert.type == "health",
               Alert.acknowledged.is_(False))
        .order_by(*ALERT_ORDER[1:])
        .limit(1)
    )
    if open_alert and SEVERITY_RANK[open_alert.severity] <= SEVERITY_RANK[severity]:
        return None

    alert = Alert(astronaut_id=astronaut.id, type="health", severity=severity,
                  message=build_message(astronaut, risk, explanation))
    db.add(alert)
    return alert
