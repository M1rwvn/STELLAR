"""Pydantic models = the Interface Contract (Annex 2) in code.

Any change here is a contract change: announce it in the team group first.
"""
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def _ensure_utc(v: datetime) -> datetime:
    # SQLite drops tzinfo; treat naive datetimes as UTC so output always ends in "Z"
    if v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc)


UTCDateTime = Annotated[datetime, AfterValidator(_ensure_utc)]

RiskLevel = Literal["Normal", "Attention", "High Risk", "Emergency"]
AlertType = Literal["health", "security", "space_weather"]
Severity = Literal["critical", "high", "medium", "low"]
Role = Literal["astronaut", "doctor", "ground", "admin", "device"]

AstronautId = Annotated[str, Field(pattern=r"^AST-\d{3}$", examples=["AST-001"])]


# ---------- POST /health-data ----------
# Every field is optional: a missing sensor must not crash the pipeline
# (fusion fills it from the baseline and reports it in "imputed").

class Wearable(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hr: float | None = Field(None, ge=20, le=250, description="Heart rate, bpm")
    hrv: float | None = Field(None, ge=0, le=300, description="HRV, ms")
    spo2: float | None = Field(None, ge=50, le=100, description="SpO2, %")
    resp_rate: float | None = Field(None, ge=0, le=80, description="Breaths/min")
    temp: float | None = Field(None, ge=30, le=45, description="Body temperature, C")
    sleep_hours: float | None = Field(None, ge=0, le=24)
    sleep_quality: float | None = Field(None, ge=0, le=1)
    activity: float | None = Field(None, ge=0, le=1)


class Suit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cabin_pressure_kpa: float | None = Field(None, ge=0, le=200)
    suit_temp_c: float | None = Field(None, ge=-50, le=80)
    o2_pct: float | None = Field(None, ge=0, le=100)
    co2_pct: float | None = Field(None, ge=0, le=100)


class Vision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    posture_score: float | None = Field(None, ge=0, le=1)
    movement_quality: float | None = Field(None, ge=0, le=1)
    fatigue_indicator: float | None = Field(None, ge=0, le=1)


class HealthDataIn(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "astronaut_id": "AST-001",
                "timestamp": "2026-10-05T10:00:00Z",
                "wearable": {"hr": 72, "hrv": 48, "spo2": 97, "resp_rate": 16, "temp": 36.7,
                             "sleep_hours": 6.5, "sleep_quality": 0.72, "activity": 0.40},
                "suit": {"cabin_pressure_kpa": 101.3, "suit_temp_c": 22.1,
                         "o2_pct": 20.9, "co2_pct": 0.04},
                "vision": {"posture_score": 0.80, "movement_quality": 0.70,
                           "fatigue_indicator": 0.30},
            }
        },
    )

    astronaut_id: AstronautId
    timestamp: UTCDateTime
    wearable: Wearable = Field(default_factory=Wearable)
    suit: Suit = Field(default_factory=Suit)
    vision: Vision = Field(default_factory=Vision)
    # Optional, additive to the contract: lets the replay script advance the mission day
    mission_day: int | None = Field(None, ge=0, le=1000)


class TopFactor(BaseModel):
    feature: str
    change_pct: float


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    astronaut_id: str | None
    type: AlertType
    severity: Severity
    message: str
    created_at: UTCDateTime
    acknowledged: bool


class LocalizedText(BaseModel):
    """English text (other languages from AI 1 are dropped: STELLAR's interface is English)."""
    en: str


class ExplanationReason(BaseModel):
    feature: str
    text: LocalizedText


class Explanation(BaseModel):
    """AI 1's plain-language reasons (English), e.g. "Sleep is 29% below your normal"."""
    reasons: list[ExplanationReason]
    summary: LocalizedText
    recommendation: LocalizedText


class FusionOut(BaseModel):
    """What AI 3 fused for this reading: suit / cabin telemetry, camera features, fatigue."""
    vitals: dict = Field(default_factory=dict)
    suit: dict = Field(default_factory=dict)
    vision: dict = Field(default_factory=dict)
    fatigue_risk: float | None = None
    fatigue_level: str | None = None
    environment_flags: list[dict] = Field(default_factory=list)
    imputed: list[str] = Field(default_factory=list)


class RiskScoreOut(BaseModel):
    astronaut_id: str
    timestamp: UTCDateTime
    risk_score: int
    level: RiskLevel
    top_factors: list[TopFactor]
    recommendation: str
    # Optional, additive (contract v1.1): null when AI 1 gives no explanation
    explanation: Explanation | None = None
    # Optional, additive (contract v1.2): the fused suit + camera data behind this score
    fusion: FusionOut | None = None

    @staticmethod
    def explanation_from(raw: dict | None) -> "Explanation | None":
        if not raw:
            return None
        return Explanation(
            reasons=[ExplanationReason(feature=r["metric"], text=r["text"]) for r in raw["reasons"]],
            summary=raw["summary"], recommendation=raw["recommendation"])


class HealthDataOut(RiskScoreOut):
    reading_id: int
    alert: AlertOut | None = None
    imputed: list[str] = Field(default_factory=list, description="Fields filled by fusion because the sensor value was missing")


# ---------- GET /astronaut-profile/{id} ----------

class ProfileOut(BaseModel):
    astronaut_id: str
    name: str
    mission_day: int
    status: RiskLevel
    baseline: dict
    # int stays int in JSON (contract example: 78); a model may still send a decimal
    recovery_score: int | float | None = None


# ---------- Extras: /crew, /risk-history ----------

class CrewMember(BaseModel):
    astronaut_id: str
    name: str
    mission_day: int
    status: RiskLevel
    risk_score: int | None = None
    level: RiskLevel | None = None
    last_update: UTCDateTime | None = None
    open_alerts: int = 0


class RiskHistoryPoint(BaseModel):
    timestamp: UTCDateTime
    risk_score: int
    level: RiskLevel


class RiskHistoryOut(BaseModel):
    astronaut_id: str
    points: list[RiskHistoryPoint]


# ---------- Auth ----------

class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: Role
    astronaut_id: str | None = None
    expires_in: int


class SecurityEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: UTCDateTime
    event_type: str
    username: str | None
    ip: str | None
    details: str | None
