"""AI 3 (Mariam's cv-fusion): her fusion layer inside the backend, the demo sensors, and the full flow."""
import glob

from app import ai
from ai_modules import demo_sensors, fusion


def _profile(aid):
    return ai.get_baseline(aid)


def test_fusion_module_is_live_and_is_mariams():
    assert ai.ai_status()["fusion"] == "real"
    assert fusion.MODEL_VERSION == "1.0"
    assert len(fusion.FEATURE_COLUMNS) == 24            # her Core v1.0 columns


def test_vector_keeps_her_fixed_columns_plus_backend_extras():
    fusion.reset_cache("AST-001")
    v = ai.build_health_vector({"hr": 62}, {}, {}, _profile("AST-001"))
    assert list(v)[:24] == fusion.FEATURE_COLUMNS
    assert list(v)[24:] == ["environment_flags", "imputed"]
    assert "co2_pct" in v["imputed"] and "posture_score" in v["imputed"] and "hr" not in v["imputed"]


def test_deviation_comes_from_the_digital_twin_not_the_placeholder():
    p = _profile("AST-002")
    reading = {"hr": 80, "sleep_hours": 5.0}
    v = ai.build_health_vector(reading, {}, {}, p)
    twin = ai.compute_deviation({k: v[k] for k in ("hr", "sleep_hours")}, p)
    assert v["hr_dev_pct"] == twin["hr"] and v["sleep_hours_dev_pct"] == twin["sleep_hours"]


def test_missing_value_uses_this_astronauts_own_history_only():
    fusion.reset_cache()
    ai.build_health_vector({"hr": 70, "spo2": 91.0}, {}, {}, _profile("AST-003"))   # Ryan: low SpO2
    emily = ai.build_health_vector({"hr": 70}, {}, {}, _profile("AST-002"))
    assert emily["spo2"] != 91.0                          # never Ryan's value
    again = ai.build_health_vector({"hr": 70}, {}, {}, _profile("AST-003"))
    assert again["spo2"] == 91.0                         # Ryan's own last known value


def test_briefs_example_normal_hr_short_sleep_little_movement_is_high():
    p = _profile("AST-001")
    hr = p["baseline_detail"]["hr"]["center"]
    v = ai.build_health_vector({"hr": hr, "sleep_hours": 4.0, "activity": 0.1}, {}, {}, p)
    assert v["fatigue_risk"] == "High"


def test_unsafe_measured_suit_values_are_flagged_and_estimates_are_not():
    v = ai.build_health_vector({"hr": 65}, {"co2_pct": 0.8, "o2_pct": 18.0}, {}, _profile("AST-002"))
    assert {f["field"] for f in v["environment_flags"]} == {"co2_pct", "o2_pct"}
    v = ai.build_health_vector({"hr": 65}, {}, {}, _profile("AST-002"))
    assert v["environment_flags"] == []


def test_demo_sensors_add_suit_every_hour_and_a_daily_camera_check():
    from scripts.replay import load_rows
    rows = demo_sensors.enrich(load_rows(sorted(glob.glob("data/scenarios/*.csv"))))
    assert all(None not in r["suit"].values() for r in rows)
    assert all(fusion.environment_flags(r["suit"]) == [] for r in rows)
    late = [r for r in rows if r["mission_day"] == 58 and r["timestamp"][11:13] == "12"]
    fat = {r["astronaut_id"]: r["vision"]["fatigue_indicator"] for r in late}
    assert fat["AST-003"] > fat["AST-001"] + 0.2          # Ryan looks more tired than Ethan on camera
    again = demo_sensors.enrich(load_rows(sorted(glob.glob("data/scenarios/*.csv"))))
    assert [r["suit"] for r in again[:50]] == [r["suit"] for r in rows[:50]]   # same every run


def test_risk_score_shows_the_fused_suit_and_camera_data(client, auth):
    body = {"astronaut_id": "AST-002", "timestamp": "2026-10-20T10:00:00Z",
            "wearable": {"hr": 70, "sleep_hours": 4.2, "activity": 0.1},
            "suit": {"cabin_pressure_kpa": 101.2, "suit_temp_c": 22.8, "o2_pct": 20.9, "co2_pct": 0.31},
            "vision": {"posture_score": 0.7, "movement_quality": 0.6, "fatigue_indicator": 0.6}}
    assert client.post("/health-data", json=body, headers=auth("device")).status_code == 200
    out = client.get("/risk-score/AST-002", headers=auth("ground")).json()["fusion"]
    assert out["suit"]["co2_pct"] == 0.31 and out["vision"]["fatigue_indicator"] == 0.6
    assert out["fatigue_level"] == "High" and out["environment_flags"] == []
