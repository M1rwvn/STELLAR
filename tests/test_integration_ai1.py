"""Backend + Shimaa's Digital Twin working together, end to end through the API.

The key guarantee: the features the backend stores for a reading (vector_json) are the SAME
numbers as in AI 1's training table, so a model trained on that table (Menna) gets identical
inputs at runtime.
"""
import json

import pandas as pd
import pytest

from app.database import SessionLocal
from app.models import HealthReading
from tests.conftest import ROOT, SCENARIO_FILES, scenario_rows

TRAINING_COLUMNS = (
    [f"{f}_roll{w}h_mean" for f in ("hr", "hrv", "spo2", "resp_rate", "temp", "activity") for w in (24, 168)]
    + ["hr_roll24h_std", "sleep_debt_7d", "sleep_hours_roll7d_mean", "stress_score",
       "hr_pct_dev", "hrv_pct_dev", "spo2_pct_dev", "resp_rate_pct_dev", "temp_delta_c",
       "sleep_hours_pct_dev", "sleep_quality_pct_dev", "activity_pct_dev", "stress_score_pct_dev"])


def _post_days(client, headers, astronaut_id, days):
    for row in scenario_rows(astronaut_id, days):
        res = client.post("/health-data", json=row, headers=headers)
        assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.parametrize("astronaut_id", ["AST-002", "AST-003"])
def test_runtime_features_equal_training_table(client, auth, astronaut_id):
    _post_days(client, auth("device"), astronaut_id, range(52, 60))   # 8 days hourly
    training = pd.read_csv(ROOT / "data" / "scenarios" / SCENARIO_FILES[astronaut_id])
    training = training.set_index("timestamp")
    with SessionLocal() as db:
        stored = db.query(HealthReading).filter_by(astronaut_id=astronaut_id).order_by(HealthReading.ts).all()
    checked = 0
    for reading in stored[-24:]:                                         # day 59: full 7-day history
        ts = reading.ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        expected = training.loc[ts]
        for col in TRAINING_COLUMNS:
            got = reading.vector_json[col]
            assert got == pytest.approx(expected[col], abs=1e-3), (ts, col, got, expected[col])
        checked += 1
    assert checked == 24


def test_vector_is_strict_json_even_without_history(client, auth):
    res = client.post("/health-data", json=scenario_rows("AST-001", [30], [12])[0], headers=auth("device"))
    assert res.status_code == 200
    with SessionLocal() as db:
        vector = db.query(HealthReading).one().vector_json
    json.dumps(vector, allow_nan=False)                                   # PostgreSQL-safe
    assert vector["hr_roll24h_mean"] is None                             # 1 reading: not invented
    assert vector["hr_pct_dev"] is not None and vector["stress_score"] is None


def test_explanation_reaches_the_app_and_the_alert(client, auth):
    out = _post_days(client, auth("device"), "AST-003", [60])
    assert out["level"] == "Emergency"
    reasons = out["explanation"]["reasons"]
    assert 1 <= len(reasons) <= 3 and all(r["text"]["en"] and set(r["text"]) == {"en"} for r in reasons)

    risk = client.get("/risk-score/AST-003", headers=auth("ryan")).json()
    assert risk["explanation"]["summary"]["en"]                           # English for the app
    alert = client.get("/alerts", params={"astronaut_id": "AST-003"}, headers=auth("ground")).json()[0]
    assert "personal normal" in alert["message"] and "your normal" not in alert["message"]


def test_normal_reading_explains_all_is_well(client, auth):
    out = _post_days(client, auth("device"), "AST-001", [40])
    assert out["level"] == "Normal" and out["explanation"]["reasons"] == []
    assert out["explanation"]["summary"]["en"].startswith("All measured values are within")


def test_profile_range_holds_most_normal_readings(client, auth):
    profile = client.get("/astronaut-profile/AST-001", headers=auth("ethan")).json()
    lo, hi = profile["baseline"]["spo2"]
    readings = [r["wearable"]["spo2"] for r in scenario_rows("AST-001", range(15, 61))]
    inside = sum(lo <= v <= hi for v in readings) / len(readings)
    assert inside >= 0.9, inside                                           # v1.0 (Q1-Q3) gave 53%
