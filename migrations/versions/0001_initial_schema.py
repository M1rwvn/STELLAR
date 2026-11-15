"""initial schema: users, astronauts, baselines, health_readings, risk_scores, alerts, security_events

Revision ID: 0001
Revises:
Create Date: 2026-10-26
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(128), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "astronauts",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("mission_day", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )

    op.create_table(
        "baselines",
        sa.Column("astronaut_id", sa.String(16), sa.ForeignKey("astronauts.id"), primary_key=True),
        sa.Column("data_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "health_readings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("astronaut_id", sa.String(16), sa.ForeignKey("astronauts.id"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("wearable_json", sa.JSON(), nullable=True),
        sa.Column("suit_json", sa.JSON(), nullable=True),
        sa.Column("vision_json", sa.JSON(), nullable=True),
        sa.Column("vector_json", sa.JSON(), nullable=True),
    )
    op.create_index("ix_health_readings_astronaut_ts", "health_readings", ["astronaut_id", "ts"])

    op.create_table(
        "risk_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("astronaut_id", sa.String(16), sa.ForeignKey("astronauts.id"), nullable=False),
        sa.Column("reading_id", sa.Integer(), sa.ForeignKey("health_readings.id"), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("top_factors_json", sa.JSON(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
    )
    op.create_index("ix_risk_scores_astronaut_ts", "risk_scores", ["astronaut_id", "ts"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("astronaut_id", sa.String(16), sa.ForeignKey("astronauts.id"), nullable=True),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged", sa.Boolean(), nullable=False),
        sa.Column("acknowledged_by", sa.String(64), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_alerts_open", "alerts", ["acknowledged", "severity", "created_at"])
    op.create_index("ix_alerts_astronaut", "alerts", ["astronaut_id", "created_at"])

    op.create_table(
        "security_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
    )
    op.create_index("ix_security_events_ts", "security_events", ["ts"])


def downgrade() -> None:
    for table in ("security_events", "alerts", "risk_scores", "health_readings",
                  "baselines", "astronauts", "users"):
        op.drop_table(table)
