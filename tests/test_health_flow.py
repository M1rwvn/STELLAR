"""The full flow: POST /health-data -> risk -> store -> alert -> read endpoints."""
import copy
import time

import pytest

from tests.conftest import CONTRACT_PAYLOAD, RYAN_EMERGENCY, scenario_rows

LEVELS = {"Normal", "Attention", "High Risk", "Emergency"}


def test_health_endpoint(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["database"] is True
    assert set(body["ai"]) == {"digital_twin", "fusion", "risk"}
    assert body["ai"]["digital_twin"] == "real"  # Shimaa's module in ai_modules/


def test_contract_example_returns_risk_shape(client, auth):
    res = client.post("/health-data", json=CONTRACT_PAYLOAD, headers=auth("device"))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["astronaut_id"] == "AST-001"
    assert body["timestamp"] == "2026-10-05T10:00:00Z"
    assert isinstance(body["risk_score"], int) and 0 <= body["risk_score"] <= 100
    assert body["level"] in LEVELS
    assert 1 <= len(body["top_factors"]) <= 3
    assert set(body["top_factors"][0]) == {"feature", "change_pct"}
    assert isinstance(body["recommendation"], str) and body["recommendation"]
    assert body["imputed"] == []


def test_emergency_creates_critical_alert_once(client, auth):
    device = auth("device")
    first = client.post("/health-data", json=RYAN_EMERGENCY, headers=device).json()
    assert first["level"] == "Emergency"
    assert first["alert"]["severity"] == "critical"
    assert first["alert"]["astronaut_id"] == "AST-003"

    # Same situation 6 hours later: no duplicate alert while the first is open
    later = copy.deepcopy(RYAN_EMERGENCY)
    later["timestamp"] = "2026-10-20T18:00:00Z"
    assert client.post("/health-data", json=later, headers=device).json()["alert"] is None

    alerts = client.get("/alerts", params={"astronaut_id": "AST-003"}, headers=auth("ground")).json()
    assert len(alerts) == 1

    # Once acknowledged, a new emergency raises a new alert
    client.post(f"/alerts/{alerts[0]['id']}/ack", headers=auth("doctor"))
    later["timestamp"] = "2026-10-21T00:00:00Z"
    assert client.post("/health-data", json=later, headers=device).json()["alert"] is not None


def test_missing_sensors_do_not_crash(client, auth):
    payload = {"astronaut_id": "AST-002", "timestamp": "2026-10-05T10:00:00Z",
               "wearable": {"hr": 70}}
    res = client.post("/health-data", json=payload, headers=auth("device"))
    assert res.status_code == 200, res.text
    imputed = res.json()["imputed"]
    assert "spo2" in imputed and "co2_pct" in imputed and "fatigue_indicator" in imputed
    assert "hr" not in imputed


@pytest.mark.parametrize("change", [
    {"astronaut_id": "Ethan"},                       # bad id format
    {"timestamp": "yesterday"},                      # bad timestamp
    {"wearable": {"spo2": 150}},                     # out of physical range
    {"vision": {"fatigue_indicator": 3}},            # out of 0-1
])
def test_validation_errors_are_422(client, auth, change):
    payload = {**copy.deepcopy(CONTRACT_PAYLOAD), **change}
    assert client.post("/health-data", json=payload, headers=auth("device")).status_code == 422


def test_unknown_astronaut_is_404(client, auth):
    payload = {**CONTRACT_PAYLOAD, "astronaut_id": "AST-999"}
    assert client.post("/health-data", json=payload, headers=auth("device")).status_code == 404


def test_astronaut_can_only_post_own_data(client, auth):
    assert client.post("/health-data", json=CONTRACT_PAYLOAD, headers=auth("ethan")).status_code == 200
    assert client.post("/health-data", json=CONTRACT_PAYLOAD, headers=auth("ryan")).status_code == 403
    assert client.post("/health-data", json=CONTRACT_PAYLOAD, headers=auth("doctor")).status_code == 403


def test_read_endpoints_after_ingest(client, auth):
    client.post("/health-data", json=CONTRACT_PAYLOAD, headers=auth("device"))
    ethan = auth("ethan")

    profile = client.get("/astronaut-profile/AST-001", headers=ethan).json()
    assert profile["name"] == "Ethan Cole"
    assert profile["baseline"]["hr"] == [56.47, 68.33]  # Shimaa v1.1: median +- 2 robust SD, seed 42
    assert profile["recovery_score"] == 78 and isinstance(profile["recovery_score"], int)
    assert profile["status"] in LEVELS

    risk = client.get("/risk-score/AST-001", headers=ethan).json()
    assert set(risk) == {"astronaut_id", "timestamp", "risk_score", "level", "top_factors",
                         "recommendation", "explanation", "fusion"}
    assert set(risk["explanation"]) == {"reasons", "summary", "recommendation"}

    history = client.get("/risk-history/AST-001", headers=ethan).json()
    assert len(history["points"]) == 1

    crew = client.get("/crew", headers=auth("ground")).json()
    assert [m["astronaut_id"] for m in crew] == ["AST-001", "AST-002", "AST-003"]
    assert crew[0]["risk_score"] is not None and crew[1]["risk_score"] is None


def test_risk_score_404_before_any_reading(client, auth):
    assert client.get("/risk-score/AST-002", headers=auth("doctor")).status_code == 404


def _replay(client, headers, astronaut_id, days, hours=None):
    levels = []
    for row in scenario_rows(astronaut_id, days, hours):
        res = client.post("/health-data", json=row, headers=headers)
        assert res.status_code == 200, res.text
        levels.append(res.json()["level"])
    return levels


def test_demo_scenarios_end_in_expected_levels(client, auth):
    """Definition of Done: Ethan green, Emily yellow, Ryan red - every hour of the last day.

    7 days of hourly history first, as a real wearable sends: AI 1's 7-day features and AI 2's 24 h
    means are then identical to the training data.
    """
    device = auth("device")
    for aid in ("AST-001", "AST-002", "AST-003"):
        _replay(client, device, aid, range(53, 60))
    assert set(_replay(client, device, "AST-001", [60])) == {"Normal"}
    assert set(_replay(client, device, "AST-002", [60])) == {"Attention"}
    assert set(_replay(client, device, "AST-003", [60])) == {"Emergency"}

    crew = {m["name"].split()[0]: m for m in client.get("/crew", headers=auth("ground")).json()}   # by first name
    # Ryan: an early High Risk alert (day 56), then the escalation to Emergency (day 57)
    ryan_alerts = client.get("/alerts", params={"astronaut_id": "AST-003"}, headers=auth("ground")).json()
    assert [a["severity"] for a in ryan_alerts] == ["critical", "high"]          # Emergency listed first
    assert crew["Ryan"]["open_alerts"] == 2
    assert crew["Ethan"]["open_alerts"] == 0 and crew["Emily"]["open_alerts"] == 0
    assert crew["Ryan"]["mission_day"] == 60


def test_ryan_is_flagged_before_the_emergency(client, auth):
    """Early warning: Ryan is already above Normal on day 56, Emergency from day 58."""
    device = auth("device")
    _replay(client, device, "AST-003", range(47, 54))                     # 7 days of history
    levels = {d: set(_replay(client, device, "AST-003", [d])) for d in range(54, 61)}   # every hour
    assert levels[54] == levels[55] == {"Normal"}
    assert levels[56] & {"Attention", "High Risk"}
    assert all(levels[d] == {"Emergency"} for d in (58, 59, 60))


def test_emily_trends_from_green_to_yellow(client, auth):
    device = auth("device")
    _replay(client, device, "AST-002", range(30, 61, 2), hours=[12])
    points = client.get("/risk-history/AST-002", headers=auth("doctor")).json()["points"]
    assert points[0]["level"] == "Normal" and points[-1]["level"] == "Attention"
    assert all(p["level"] in ("Normal", "Attention") for p in points)


def test_endpoints_respond_under_one_second(client, auth):
    device, ground = auth("device"), auth("ground")
    for path_call in (
        lambda: client.post("/health-data", json=CONTRACT_PAYLOAD, headers=device),
        lambda: client.get("/crew", headers=ground),
        lambda: client.get("/alerts", headers=ground),
        lambda: client.get("/risk-history/AST-001", headers=ground),
    ):
        start = time.perf_counter()
        assert path_call().status_code == 200
        assert time.perf_counter() - start < 1.0
