"""Backend + Menna's risk model (AI 2) working together, end to end."""
import logging
import os
import pickle
import time

import pandas as pd
import pytest

from app import ai
from app.ai.stubs import risk as stub_risk
from app.database import SessionLocal
from app.models import HealthReading
from tests.conftest import ROOT, SCENARIO_FILES, scenario_rows

DEV = ["hr_pct_dev", "hrv_pct_dev", "spo2_pct_dev", "resp_rate_pct_dev", "temp_delta_c",
       "sleep_hours_pct_dev", "stress_score_pct_dev", "activity_pct_dev"]


def test_risk_is_mennas_model():
    import ai_modules.risk as menna
    assert ai.ai_status()["risk"] == "real"
    assert menna.MODEL_VERSION == "1.1.0"
    assert menna._model["rf"].n_jobs == 1


class _Evil:
    def __reduce__(self):
        return (os.system, ("echo should-never-run",))


def test_tampered_model_file_is_refused_before_running(tmp_path):
    import ai_modules.risk as menna
    bad = tmp_path / "physio_model.joblib"
    bad.write_bytes(pickle.dumps(_Evil()))
    with pytest.raises(RuntimeError, match="Refusing to load"):
        menna._safe_load(bad)


def test_24h_means_equal_the_training_feature(client, auth):
    device = auth("device")
    for row in scenario_rows("AST-002", range(55, 61)):
        assert client.post("/health-data", json=row, headers=device).status_code == 200
    table = pd.read_csv(ROOT / "data" / "scenarios" / SCENARIO_FILES["AST-002"]).set_index("timestamp")
    post = ~table["is_calibration"]
    with SessionLocal() as db:
        stored = db.query(HealthReading).filter_by(astronaut_id="AST-002").order_by(HealthReading.ts).all()
    for reading in stored[-24:]:                                  # day 60: a full 24 h window behind it
        ts = reading.ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        for k in DEV:
            expected = table.loc[post, k].rolling(24, min_periods=6).mean().loc[ts]
            assert reading.vector_json[k + "_s"] == pytest.approx(expected, abs=1e-3), (ts, k)


def test_failing_model_falls_back_loudly_not_silently(monkeypatch, caplog):
    def broken(vector):
        raise RuntimeError("model file damaged")

    monkeypatch.setattr(ai._risk, "predict_risk", broken)
    vector = {"hr": 95, "spo2": 92, "temp": 38.0, "hr_dev_pct": 45.0, "sleep_hours_dev_pct": -45.0}
    with caplog.at_level(logging.ERROR, logger="stellar.ai"):
        out = ai.predict_risk(vector)
    assert "falling back to stub" in caplog.text                 # visible in the logs
    assert out["level"] == ai._normalize_risk(stub_risk.predict_risk(vector))["level"] == "Emergency"


def test_real_model_answers_under_one_second(client, auth):
    device = auth("device")
    rows = scenario_rows("AST-003", [57, 58])
    slowest = 0.0
    for row in rows:
        start = time.perf_counter()
        assert client.post("/health-data", json=row, headers=device).status_code == 200
        slowest = max(slowest, time.perf_counter() - start)
    assert slowest < 1.0, slowest
