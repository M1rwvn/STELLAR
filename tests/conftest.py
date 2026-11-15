import os
import tempfile
from pathlib import Path

# Must be set before the app is imported (the engine is created at import time)
_DB_FILE = Path(tempfile.gettempdir()) / "stellar_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.as_posix()}"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_PASSWORD"] = "test-pass"
os.environ["COMM_LINK_ENABLED"] = "false"
os.environ["AI_MODE"] = os.environ.get("AI_MODE", "auto")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402
from scripts.replay import load_rows  # noqa: E402

PASSWORD = "test-pass"
ROOT = Path(__file__).resolve().parent.parent
SCENARIO_FILES = {"AST-001": "ethan_normal.csv", "AST-002": "emily_attention.csv",
                  "AST-003": "ryan_emergency.csv"}


def scenario_rows(astronaut_id: str, days=None, hours=None) -> list[dict]:
    """Shimaa's demo data as POST /health-data payloads (same loader as the replay script)."""
    rows = load_rows([str(ROOT / "data" / "scenarios" / SCENARIO_FILES[astronaut_id])])
    return [r for r in rows
            if (days is None or r["mission_day"] in days)
            and (hours is None or int(r["timestamp"][11:13]) in hours)]

CONTRACT_PAYLOAD = {
    "astronaut_id": "AST-001",
    "timestamp": "2026-10-05T10:00:00Z",
    "wearable": {"hr": 72, "hrv": 48, "spo2": 97, "resp_rate": 16, "temp": 36.7,
                 "sleep_hours": 6.5, "sleep_quality": 0.72, "activity": 0.40},
    "suit": {"cabin_pressure_kpa": 101.3, "suit_temp_c": 22.1, "o2_pct": 20.9, "co2_pct": 0.04},
    "vision": {"posture_score": 0.80, "movement_quality": 0.70, "fatigue_indicator": 0.30},
}

RYAN_EMERGENCY = {
    "astronaut_id": "AST-003",
    "timestamp": "2026-10-20T12:00:00Z",
    "wearable": {"hr": 98, "hrv": 30, "spo2": 93, "resp_rate": 20, "temp": 37.8,
                 "sleep_hours": 4.0, "sleep_quality": 0.5, "activity": 0.35},
    "suit": {"cabin_pressure_kpa": 101.3, "suit_temp_c": 22.0, "o2_pct": 20.9, "co2_pct": 0.04},
    "vision": {"posture_score": 0.7, "movement_quality": 0.5, "fatigue_indicator": 0.7},
}


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    with TestClient(app) as c:
        yield c


def token_for(client: TestClient, username: str) -> dict:
    res = client.post("/login", json={"username": username, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture()
def auth(client):
    cache: dict[str, dict] = {}

    def _get(username: str) -> dict:
        if username not in cache:
            cache[username] = token_for(client, username)
        return cache[username]

    return _get
