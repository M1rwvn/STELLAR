"""Mock API (day 8): same paths and JSON shapes as the real API, fixed data, no DB.

Lets Lena (Flutter) and Marwan (Web) build against the contract before the
real backend and AI models are ready. Any username/password logs in; the
role is guessed from the username (ethan/emily/ryan -> astronaut).

    uvicorn app.mock_api:app --port 8001      # or: docker compose up mock
"""
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.schemas import (
    AlertOut,
    CrewMember,
    HealthDataIn,
    HealthDataOut,
    LoginIn,
    ProfileOut,
    RiskHistoryOut,
    RiskScoreOut,
    TokenOut,
)

FIXTURES = json.loads((Path(__file__).resolve().parent.parent / "mock" / "fixtures.json")
                      .read_text(encoding="utf-8"))
ASTRONAUT_USERS = {"ethan": "AST-001", "emily": "AST-002", "ryan": "AST-003"}
STAFF_ROLES = {"doctor", "ground", "admin", "device"}

app = FastAPI(title="STELLAR MOCK API", version="1.0.0-mock",
              description="Fixed data with the exact contract shapes. **Not the real backend.**")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_alerts = deepcopy(FIXTURES["alerts"])


def _known(astronaut_id: str) -> None:
    if astronaut_id not in FIXTURES["profiles"]:
        raise HTTPException(status_code=404, detail=f"Unknown astronaut {astronaut_id}")


@app.get("/health")
def health():
    return {"status": "ok", "mock": True}


@app.post("/login", response_model=TokenOut)
def login(body: LoginIn):
    astronaut_id = ASTRONAUT_USERS.get(body.username)
    role = "astronaut" if astronaut_id else (body.username if body.username in STAFF_ROLES else "ground")
    return TokenOut(access_token=f"mock-token-{body.username}", role=role,
                    astronaut_id=astronaut_id, expires_in=43200)


@app.post("/health-data", response_model=HealthDataOut)
def health_data(payload: HealthDataIn):
    _known(payload.astronaut_id)
    risk = deepcopy(FIXTURES["risk_scores"][payload.astronaut_id])
    risk["timestamp"] = payload.timestamp
    alert = next((a for a in _alerts if a["astronaut_id"] == payload.astronaut_id
                  and not a["acknowledged"]), None) if risk["level"] in ("High Risk", "Emergency") else None
    return HealthDataOut(reading_id=1, alert=alert, imputed=[], **risk)


@app.get("/astronaut-profile/{astronaut_id}", response_model=ProfileOut)
def profile(astronaut_id: str):
    _known(astronaut_id)
    return FIXTURES["profiles"][astronaut_id]


@app.get("/risk-score/{astronaut_id}", response_model=RiskScoreOut)
def risk_score(astronaut_id: str):
    _known(astronaut_id)
    return FIXTURES["risk_scores"][astronaut_id]


@app.get("/risk-history/{astronaut_id}", response_model=RiskHistoryOut)
def risk_history(astronaut_id: str, limit: int = Query(60, ge=1, le=5000)):
    _known(astronaut_id)
    final = FIXTURES["risk_scores"][astronaut_id]["risk_score"]
    start = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
    points = []
    n = min(limit, 42)
    for i in range(n):
        # flat for most of the mission, then rises to today's value
        score = round(final * max(0.0, (i - n * 0.6) / (n * 0.4))) if final > 25 else min(final, 5 + i % 4)
        level = "Emergency" if score >= 75 else "High Risk" if score >= 50 else "Attention" if score >= 25 else "Normal"
        points.append({"timestamp": start + timedelta(days=i), "risk_score": score, "level": level})
    return {"astronaut_id": astronaut_id, "points": points}


@app.get("/crew", response_model=list[CrewMember])
def crew():
    out = []
    for astronaut_id, p in FIXTURES["profiles"].items():
        r = FIXTURES["risk_scores"][astronaut_id]
        out.append({"astronaut_id": astronaut_id, "name": p["name"], "mission_day": p["mission_day"],
                    "status": p["status"], "risk_score": r["risk_score"], "level": r["level"],
                    "last_update": r["timestamp"],
                    "open_alerts": sum(1 for a in _alerts
                                       if a["astronaut_id"] == astronaut_id and not a["acknowledged"])})
    return out


@app.get("/alerts", response_model=list[AlertOut])
def alerts(astronaut_id: str | None = None, type: str | None = None,  # noqa: A002
           acknowledged: bool | None = None):
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    items = [a for a in _alerts
             if (astronaut_id is None or a["astronaut_id"] == astronaut_id)
             and (type is None or a["type"] == type)
             and (acknowledged is None or a["acknowledged"] == acknowledged)]
    newest_first = lambda a: -datetime.fromisoformat(a["created_at"].replace("Z", "+00:00")).timestamp()  # noqa: E731
    return sorted(items, key=lambda a: (a["acknowledged"], rank[a["severity"]], newest_first(a)))


@app.post("/alerts/{alert_id}/ack", response_model=AlertOut)
def ack(alert_id: int):
    for a in _alerts:
        if a["id"] == alert_id:
            a["acknowledged"] = True
            return a
    raise HTTPException(status_code=404, detail="Alert not found")
