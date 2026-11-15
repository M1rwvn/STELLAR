from app.config import get_settings
from tests.conftest import PASSWORD


def test_login_returns_jwt_with_role(client):
    res = client.post("/login", json={"username": "ethan", "password": PASSWORD})
    assert res.status_code == 200
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "astronaut"
    assert body["astronaut_id"] == "AST-001"
    assert body["access_token"].count(".") == 2


def test_wrong_password_is_401(client):
    res = client.post("/login", json={"username": "ethan", "password": "nope"})
    assert res.status_code == 401


def test_protected_endpoint_needs_token(client):
    assert client.get("/crew").status_code == 401
    bad = {"Authorization": "Bearer not-a-jwt"}
    assert client.get("/crew", headers=bad).status_code == 401


def test_lockout_after_max_failed_logins(client, auth):
    max_fails = get_settings().max_failed_logins
    for _ in range(max_fails):
        assert client.post("/login", json={"username": "emily", "password": "x"}).status_code == 401
    # even the right password is refused while locked
    res = client.post("/login", json={"username": "emily", "password": PASSWORD})
    assert res.status_code == 423

    ground = auth("ground")
    security_alerts = client.get("/alerts", params={"type": "security"}, headers=ground).json()
    assert any("emily" in a["message"] and a["severity"] == "high" for a in security_alerts)

    events = {e["event_type"] for e in client.get("/security-events", headers=ground).json()}
    assert {"login_failed", "account_locked", "login_while_locked"} <= events


def test_role_restrictions(client, auth):
    assert client.get("/crew", headers=auth("ethan")).status_code == 403
    assert client.get("/crew", headers=auth("device")).status_code == 403
    assert client.get("/crew", headers=auth("doctor")).status_code == 200
    assert client.get("/crew", headers=auth("admin")).status_code == 200
    assert client.get("/security-events", headers=auth("doctor")).status_code == 403


def test_astronaut_sees_only_own_data(client, auth):
    ethan = auth("ethan")
    assert client.get("/astronaut-profile/AST-001", headers=ethan).status_code == 200
    assert client.get("/astronaut-profile/AST-002", headers=ethan).status_code == 403
    assert client.get("/risk-history/AST-003", headers=ethan).status_code == 403

    events = client.get("/security-events", params={"event_type": "forbidden"},
                        headers=auth("ground")).json()
    assert any(e["username"] == "ethan" for e in events)


def test_me(client, auth):
    assert client.get("/me", headers=auth("ryan")).json() == {
        "username": "ryan", "role": "astronaut", "astronaut_id": "AST-003"}
