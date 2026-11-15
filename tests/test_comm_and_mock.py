from fastapi.testclient import TestClient

from app.mock_api import app as mock_app
from app.services.comm_link import CommLink
from tests.conftest import CONTRACT_PAYLOAD


def test_emergency_jumps_the_queue_after_blackout():
    link = CommLink(delay_seconds=1)
    link.start_blackout(60)
    link.enqueue("risk", "Normal", "AST-001", "ethan ok")
    link.enqueue("risk", "Attention", "AST-002", "emily attention")
    link.enqueue("alert", "Emergency", "AST-003", "ryan emergency")
    assert link.transmit_next() is None  # nothing leaves during loss of signal

    link.blackout_until = None  # signal is back
    order = [link.transmit_next().astronaut_id for _ in range(3)]
    assert order == ["AST-003", "AST-002", "AST-001"]
    assert link.transmit_next() is None


def test_comm_status_endpoint(client, auth):
    client.post("/health-data", json=CONTRACT_PAYLOAD, headers=auth("device"))
    status = client.get("/comm/status", headers=auth("ground")).json()
    assert status["queued_count"] + len(status["sent"]) >= 1
    assert client.post("/comm/blackout", json={"seconds": 1}, headers=auth("ground")).status_code == 200
    assert client.post("/comm/blackout", json={"seconds": 1}, headers=auth("ethan")).status_code == 403


def test_mock_api_serves_contract_shapes():
    with TestClient(mock_app) as mock:
        login = mock.post("/login", json={"username": "ryan", "password": "anything"}).json()
        assert login["role"] == "astronaut" and login["astronaut_id"] == "AST-003"

        assert mock.post("/health-data", json=CONTRACT_PAYLOAD).json()["level"] == "Normal"
        assert mock.get("/astronaut-profile/AST-001").json()["baseline"]["hr"] == [56.47, 68.33]
        assert mock.get("/risk-score/AST-003").json()["explanation"]["reasons"][0]["feature"] == "spo2"
        assert mock.get("/risk-score/AST-003").json()["level"] == "Emergency"
        assert len(mock.get("/crew").json()) == 3
        assert mock.get("/risk-history/AST-002").json()["points"][-1]["level"] == "Attention"

        alerts = mock.get("/alerts").json()
        assert alerts[0]["severity"] == "critical"
        assert mock.post(f"/alerts/{alerts[0]['id']}/ack").json()["acknowledged"] is True
        assert mock.get("/risk-score/AST-999").status_code == 404
