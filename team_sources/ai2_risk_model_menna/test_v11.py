"""v1.1 checks (pytest):  pip install pytest  ->  python -m pytest test_v11.py -q

Locks in the integration fixes and the Definition of Done on Shimaa's data
(Ahmed green, Sara yellow, Omar red - every hour, using the 24 h averages the model was trained on).
"""
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import physio_model as pm  # noqa: E402
import physio_risk as pr  # noqa: E402

OMAR = {"hr_pct_dev": 28.6, "hrv_pct_dev": -35.4, "spo2_pct_dev": -3.2, "resp_rate_pct_dev": 25,
        "temp_delta_c": 0.66, "sleep_hours_pct_dev": -34.8, "stress_score_pct_dev": 150, "activity_pct_dev": -30}


def test_works_from_any_folder(tmp_path):
    """v1.0 returned a silent 'Normal 12' when called from another folder (model path was relative)."""
    code = (f"import sys; sys.path.insert(0, {str(HERE)!r}); from physio_model import predict_risk; "
            f"print(predict_risk({OMAR!r})['level'])")
    out = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "Emergency"


def test_broken_model_is_loud_not_normal(monkeypatch, tmp_path):
    monkeypatch.setattr(pm, "_M", None)
    monkeypatch.setattr(pm, "MODEL_PATH", str(tmp_path / "missing.joblib"))
    monkeypatch.setattr(pm.load_model, "__defaults__", (str(tmp_path / "missing.joblib"),))
    with pytest.raises(FileNotFoundError):
        pm.predict_risk(OMAR)


def test_import_has_no_side_effects():
    code = (f"import sys; sys.path.insert(0, {str(HERE)!r}); import physio_model; "
            "print('matplotlib' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_prefers_the_24h_average_it_was_trained_on():
    avg = {c + "_s": v for c, v in OMAR.items()}
    noisy_now = {c: 0.0 for c in OMAR}                    # instantaneous values disagree
    assert pm.predict_risk({**noisy_now, **avg}) == pm.predict_risk(avg)
    assert pm.predict_risk(noisy_now)["level"] == "Normal"  # falls back to instantaneous when no average


@pytest.fixture(scope="module")
def scored():
    df = pm.load()                                         # Shimaa's data, 24 h smoothed, post-calibration
    pm.load_model()
    s = pm.score(pm._M, df)[1]
    return df.assign(level=pm.lv(s), score=s)


def test_ahmed_green_every_hour(scored):
    assert (scored[scored.astronaut_id == "AST-001"].level == 0).all()


def test_sara_yellow_never_orange(scored):
    sara = scored[scored.astronaut_id == "AST-002"]
    assert (sara.level <= 1).all()                                 # never High Risk / Emergency
    assert (sara[sara.mission_day >= 50].level == 1).all()         # yellow every hour of days 50-60
    assert int(sara[sara.level == 1].mission_day.min()) <= 42      # early warning kept (decline starts day 40)


def test_omar_red_at_the_end_and_green_before(scored):
    omar = scored[scored.astronaut_id == "AST-003"]
    assert (omar[omar.mission_day >= 57].level == 3).all()
    assert (omar[omar.mission_day <= 54].level == 0).all()
    assert (omar[omar.mission_day == 56].level >= 1).all()         # early warning on day 56


def test_stress_counts_at_most_two_points():
    assert pr.news_points({"stress_score_pct_dev": 500})[0] == 2
    assert pr.news_points({"stress_score_pct_dev": 35})[0] == 1
