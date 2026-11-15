"""The Ground Control dashboard is served and only uses endpoints that exist."""
import re


def test_root_redirects_to_dashboard(client):
    res = client.get("/", follow_redirects=False)
    assert res.status_code in (302, 307) and res.headers["location"] == "/dashboard"


def test_dashboard_page_is_served_offline(client):
    res = client.get("/dashboard")
    assert res.status_code == 200 and "text/html" in res.headers["content-type"]
    html = res.text
    assert "<title>STELLAR Ground Control</title>" in html
    assert "http://" not in html.replace("http://www.w3.org/2000/svg", "")   # no external files: works offline
    assert "<script src" not in html


def test_every_api_path_the_page_calls_exists(client):
    html = client.get("/dashboard").text
    called = set(re.findall(r'"(/(?:login|health|crew|alerts|risk-score|astronaut-profile|risk-history|comm|space-weather)[^"?]*)', html))
    routes = set(client.get("/openapi.json").json()["paths"])
    assert len(called) >= 8
    for path in called:
        base = path.rstrip("/")
        assert any(r == base or r.startswith(base + "/") or r.startswith(base + "{") for r in routes), path
