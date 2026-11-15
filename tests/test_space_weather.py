"""NASA space weather (OMNIWeb Kp/Dst + DONKI events) replayed on the mission timeline."""
from datetime import datetime, timezone

from app.services import space_weather as sw
from scripts.fetch_nasa_space_weather import parse_omni, trim_gst, trim_sep


def test_nasa_files_cover_the_60_mission_days():
    data = sw.load()
    assert len(data["hourly"]) == 60 * 24
    assert min(data["hourly"]) == sw.NASA_START
    assert any(e["over_100mev"] and e["at_earth"] for e in data["sep"])     # 2024-10-09 storm


def test_mission_day_maps_to_the_real_nasa_date():
    t = sw.nasa_time(datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc), 46)
    assert t == datetime(2024, 10, 9, 6, 0, tzinfo=timezone.utc)
    assert sw.nasa_time(datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc)) == t      # same without mission_day


def test_9_october_2024_radiation_storm_and_10_october_severe_storm():
    c = sw.conditions(datetime(2024, 10, 9, 6, 0, tzinfo=timezone.utc))
    assert c["radiation"]["active"] and c["radiation"]["level"] == "severe"
    c = sw.conditions(datetime(2024, 10, 10, 22, 0, tzinfo=timezone.utc))
    assert c["kp"] == 8.7 and c["geomagnetic"]["level"] == "G4" and c["dst_nt"] < -200
    assert not sw.conditions(datetime(2024, 8, 25, 12, tzinfo=timezone.utc))["radiation"]["active"]


def test_g_scale():
    assert [sw.geomagnetic_level(k)["level"] for k in (2.0, 5.0, 6.0, 7.0, 8.7, 9.0)] == ["G0", "G1", "G2", "G3", "G4", "G5"]


def test_replaying_the_storm_creates_one_crew_wide_alert(client, auth):
    h = auth("device")
    for hour in (5, 6, 7):
        for aid in ("AST-001", "AST-002"):
            body = {"astronaut_id": aid, "timestamp": f"2026-10-09T{hour:02d}:00:00Z", "mission_day": 46,
                    "wearable": {"hr": 64}}
            assert client.post("/health-data", json=body, headers=h).status_code == 200
    alerts = client.get("/alerts", params={"type": "space_weather"}, headers=auth("ground")).json()
    assert len(alerts) == 1
    a = alerts[0]
    # two days later the same storm is still one alert (its >10 MeV channel was logged as a second event)
    client.post("/health-data", json={"astronaut_id": "AST-001", "timestamp": "2026-10-11T04:30:00Z",
                                      "mission_day": 48, "wearable": {"hr": 64}}, headers=h)
    later = client.get("/alerts", params={"type": "space_weather"}, headers=auth("ground")).json()
    assert sum("radiation storm" in x["message"] for x in later) == 1     # (a G4 storm alert may follow)
    assert a["severity"] == "critical" and a["astronaut_id"] is None and "NASA DONKI" in a["message"]
    # doctors see health alerts only; the space-weather alert is for Ground Control
    assert all(x["type"] == "health" for x in client.get("/alerts", headers=auth("doctor")).json())


def test_space_weather_endpoint_follows_the_latest_reading(client, auth):
    body = {"astronaut_id": "AST-003", "timestamp": "2026-10-10T22:00:00Z", "mission_day": 47, "wearable": {"hr": 70}}
    client.post("/health-data", json=body, headers=auth("device"))
    w = client.get("/space-weather", headers=auth("ground")).json()
    assert w["nasa_time"] == "2024-10-10T22:00Z" and w["mission_day"] == 47
    assert w["geomagnetic"]["level"] == "G4" and len(w["kp_last_7_days"]) == 168
    assert {s["name"].split(" ")[1] for s in w["sources"]} == {"OMNIWeb", "DONKI"}


def test_fetch_script_parses_nasa_formats():
    line = "2024 284 22 2596 51 52 60 36 " + " ".join(["1.0"] * 30) + " 87 155 -243 1000 " + " ".join(["99999.99"] * 6) + " 0"
    assert parse_omni([line]) == [{"timestamp_utc": "2024-10-10T22:00:00Z", "kp": 8.7, "dst_nt": -243}]
    sep = trim_sep([{"sepID": "X", "eventTime": "2024-10-09T03:50Z", "instruments": [{"displayName": "GOES-P: SEISS >100 MeV"}], "link": "L"}])
    assert sep[0]["instruments"] == ["GOES-P: SEISS >100 MeV"]
    gst = trim_gst([{"gstID": "G", "startTime": "2024-10-10T15:00Z", "allKpIndex": [{"kpIndex": 8.33}, {"kpIndex": 8.67}]}])
    assert gst[0]["kpMax"] == 8.67
