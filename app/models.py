"""Database tables (see docs/ERD.md).

Matches the table list in the Backend Lead brief. A few nullable columns were
added where the flow needs them (vector_json, reading_id, ack metadata).
"""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    # astronaut | doctor | ground | admin | device
    role: Mapped[str] = mapped_column(String(16))
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Astronaut(Base):
    __tablename__ = "astronauts"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # e.g. AST-001
    name: Mapped[str] = mapped_column(String(64))
    mission_day: Mapped[int] = mapped_column(Integer, default=1)
    # Normal | Attention | High Risk | Emergency
    status: Mapped[str] = mapped_column(String(16), default="Normal")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class Baseline(Base):
    __tablename__ = "baselines"

    astronaut_id: Mapped[str] = mapped_column(ForeignKey("astronauts.id"), primary_key=True)
    data_json: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HealthReading(Base):
    __tablename__ = "health_readings"
    __table_args__ = (Index("ix_health_readings_astronaut_ts", "astronaut_id", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    astronaut_id: Mapped[str] = mapped_column(ForeignKey("astronauts.id"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    wearable_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    suit_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    vision_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Unified Health Vector produced by the fusion layer (AI 3)
    vector_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class RiskScore(Base):
    __tablename__ = "risk_scores"
    __table_args__ = (Index("ix_risk_scores_astronaut_ts", "astronaut_id", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    astronaut_id: Mapped[str] = mapped_column(ForeignKey("astronauts.id"))
    reading_id: Mapped[int | None] = mapped_column(ForeignKey("health_readings.id"), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    risk_score: Mapped[float] = mapped_column(Float)
    level: Mapped[str] = mapped_column(String(16))
    top_factors_json: Mapped[list] = mapped_column(JSON, default=list)
    recommendation: Mapped[str] = mapped_column(Text, default="")


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_open", "acknowledged", "severity", "created_at"),
        Index("ix_alerts_astronaut", "astronaut_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # NULL for security alerts that are not about one astronaut
    astronaut_id: Mapped[str | None] = mapped_column(ForeignKey("astronauts.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(16))  # health | security | space_weather
    severity: Mapped[str] = mapped_column(String(16))  # critical | high | medium | low
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SecurityEvent(Base):
    __tablename__ = "security_events"
    __table_args__ = (Index("ix_security_events_ts", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # login_success | login_failed | account_locked | login_while_locked | forbidden | invalid_token
    event_type: Mapped[str] = mapped_column(String(32))
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
