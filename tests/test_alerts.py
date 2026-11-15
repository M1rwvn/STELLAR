import copy

from tests.conftest import RYAN_EMERGENCY

HIGH_RISK_EMILY = {
    "astronaut_id": "AST-002",
    "timestamp": "2026-10-20T12:00:00Z",
    "wearable": {"hr": 80, "hrv": 44, "spo2": 96.5, "resp_rate": 17, "temp": 37.0,
                 "sleep_hours": 4.6, "sleep_quality": 0.5, "activity": 0.4},
    "vision": {"fatigue_indicator": 0.55, "movement_quality": 0.6},
}


def _post(client, headers, payload, ts):
    p = copy.deepcopy(payload)
    p["timestamp"] = ts
    res = client.post("/health-data", json=p, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def test_emergency_listed_first(client, auth):
    device = auth("device")
    high = _post(client, device, HIGH_RISK_EMILY, "2026-10-20T13:00:00Z")  # newer
    assert high["level"] == "High Risk" and high["alert"]["severity"] == "high"
    _post(client, device, RYAN_EMERGENCY, "2026-10-20T12:00:00Z")

    alerts = client.get("/alerts", headers=auth("ground")).json()
    assert [a["severity"] for a in alerts[:2]] == ["critical", "high"]


def test_acknowledge_moves_alert_down(client, auth):
    device, doctor = auth("device"), auth("doctor")
    emergency = _post(client, device, RYAN_EMERGENCY, "2026-10-20T12:00:00Z")["alert"]
    _post(client, device, HIGH_RISK_EMILY, "2026-10-20T13:00:00Z")

    acked = client.post(f"/alerts/{emergency['id']}/ack", headers=doctor)
    assert acked.status_code == 200 and acked.json()["acknowledged"] is True
    # idempotent
    assert client.post(f"/alerts/{emergency['id']}/ack", headers=doctor).status_code == 200

    alerts = client.get("/alerts", headers=doctor).json()
    assert alerts[0]["severity"] == "high" and alerts[-1]["acknowledged"] is True
    open_only = client.get("/alerts", params={"acknowledged": False}, headers=doctor).json()
    assert all(not a["acknowledged"] for a in open_only)


def test_ack_permissions_and_404(client, auth):
    alert = _post(client, auth("device"), RYAN_EMERGENCY, "2026-10-20T12:00:00Z")["alert"]
    assert client.post(f"/alerts/{alert['id']}/ack", headers=auth("ryan")).status_code == 403
    assert client.post("/alerts/9999/ack", headers=auth("ground")).status_code == 404


def test_astronaut_sees_only_own_health_alerts(client, auth):
    device = auth("device")
    _post(client, device, RYAN_EMERGENCY, "2026-10-20T12:00:00Z")
    _post(client, device, HIGH_RISK_EMILY, "2026-10-20T13:00:00Z")

    ryan_view = client.get("/alerts", headers=auth("ryan")).json()
    assert {a["astronaut_id"] for a in ryan_view} == {"AST-003"}
    assert client.get("/alerts", params={"astronaut_id": "AST-002"},
                      headers=auth("ryan")).status_code == 403
    assert client.get("/alerts", params={"type": "security"},
                      headers=auth("ryan")).status_code == 403
    assert client.get("/alerts", params={"type": "security"},
                      headers=auth("doctor")).status_code == 403


def test_filter_by_type(client, auth):
    for _ in range(5):
        client.post("/login", json={"username": "ryan", "password": "wrong"})
    _post(client, auth("device"), RYAN_EMERGENCY, "2026-10-20T12:00:00Z")
    ground = auth("ground")
    assert {a["type"] for a in client.get("/alerts", headers=ground).json()} == {"health", "security"}
    assert {a["type"] for a in client.get("/alerts", params={"type": "health"},
                                          headers=ground).json()} == {"health"}
