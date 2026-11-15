"""Contract tests for the AI functions (real modules in ai_modules/ or stubs).

AI team: run `python -m pytest tests/test_ai_contract.py -v` before opening a PR.
"""
import pandas as pd
import pytest

from app import ai
from app.ai import _normalize_risk
from tests.conftest import ROOT, SCENARIO_FILES, scenario_rows

LEVELS = {"Normal", "Attention", "High Risk", "Emergency"}
DEMO = [("AST-001", "Normal"), ("AST-002", "Attention"), ("AST-003", "Emergency")]


@pytest.mark.parametrize("astronaut_id", ["AST-001", "AST-002", "AST-003"])
def test_get_baseline_shape(astronaut_id):
    profile = ai.get_baseline(astronaut_id)
    base = profile["baseline"]
    for key in ("hr", "hrv", "spo2", "temp", "sleep_hours", "activity"):
        assert key in base, key
    assert base["hr"][0] < base["hr"][1]


def test_baselines_are_personal():
    hrs = {ai.get_baseline(a)["baseline"]["hr"][0] for a in ("AST-001", "AST-002", "AST-003")}
    assert len(hrs) > 1, "every astronaut must have their own baseline"


def test_compute_deviation_example():
    base = ai.get_baseline("AST-001")["baseline"]
    dev = ai.compute_deviation({"hr": 72, "sleep_hours": 4.9}, base)
    assert dev["hr"] > 10
    assert dev["sleep_hours"] == pytest.approx(-30.0, abs=1.0)


def test_vector_has_fixed_columns_even_with_missing_sources():
    base = ai.get_baseline("AST-001")
    full = ai.build_health_vector(
        {"hr": 62, "hrv": 60, "spo2": 98, "resp_rate": 15, "temp": 36.7, "sleep_hours": 7,
         "sleep_quality": 0.8, "activity": 0.55},
        {"cabin_pressure_kpa": 101.3, "suit_temp_c": 22, "o2_pct": 20.9, "co2_pct": 0.04},
        {"posture_score": 0.8, "movement_quality": 0.8, "fatigue_indicator": 0.2},
        base,
    )
    partial = ai.build_health_vector({"hr": 62}, {}, {}, base)
    cols = lambda v: [k for k in v if k != "imputed"]  # noqa: E731
    assert cols(full) == cols(partial)
    assert "fatigue_risk" in full and "hr_dev_pct" in full


@pytest.mark.parametrize("vector", [{}, {"hr": None}, {"hr": 250, "spo2": 50, "temp": 45}])
def test_predict_risk_never_crashes(vector):
    out = ai.predict_risk(vector)
    assert 0 <= out["risk_score"] <= 100 and out["level"] in LEVELS


def test_level_matches_score_bands():
    from app.ai.stubs.risk import level_for
    assert [level_for(s) for s in (0, 24, 25, 49, 50, 74, 75, 100)] == [
        "Normal", "Normal", "Attention", "Attention", "High Risk", "High Risk",
        "Emergency", "Emergency"]


def _training_inputs(astronaut_id):
    """AI 1's training table for one astronaut + AI 2's 24 h means (<k>_s), as the backend builds them."""
    df = pd.read_csv(ROOT / "data" / "scenarios" / SCENARIO_FILES[astronaut_id])
    post = ~df["is_calibration"]
    for k in [c for c in df.columns if c.endswith("_pct_dev") or c == "temp_delta_c"]:
        df.loc[post, k + "_s"] = df.loc[post, k].rolling(24, min_periods=6).mean()
    return df


@pytest.mark.parametrize("astronaut_id,expected", DEMO)
def test_demo_scenarios(astronaut_id, expected):
    """With the inputs the models were trained on: expected level every hour of day 60, Normal in calibration."""
    base = ai.get_baseline(astronaut_id)
    table = _training_inputs(astronaut_id)
    wearable = ["hr", "hrv", "spo2", "resp_rate", "temp", "sleep_hours", "sleep_quality", "activity"]
    history_cols = [c for c in table.columns if c.endswith(("_mean", "_std", "_pct_dev", "_s"))
                    or c in ("sleep_debt_7d", "sleep_hours_roll7d_mean", "stress_score", "temp_delta_c")]

    def level(row):
        vector = ai.build_health_vector({k: row[k] for k in wearable}, {}, {}, base)
        vector.update({c: (None if pd.isna(row[c]) else float(row[c])) for c in history_cols})
        return ai.predict_risk(vector)["level"]

    last_day = table[table["mission_day"] == 60]
    assert {level(r) for _, r in last_day.iterrows()} == {expected}
    calibration = table[table["mission_day"] <= 14]
    assert {level(r) for _, r in calibration.iterrows()} == {"Normal"}


def test_digital_twin_is_shimaas_module():
    assert ai.ai_status()["digital_twin"] == "real"
    profile = ai.get_baseline("AST-002")
    assert profile["name"] == "Emily Carter" and profile["schema_version"] == "1.1.0"
    assert profile["synthetic"] is True and "baseline_detail" in profile
    assert profile["online_reference"]["stress"]["hr6_mean"] is not None


def test_unknown_astronaut_falls_back_instead_of_crashing():
    # Shimaa's get_baseline raises UnknownAstronautError; the adapter answers with the stub
    profile = ai.get_baseline("AST-999")
    assert "hr" in profile["baseline"]


def test_missing_sensor_is_filled_with_the_personal_median():
    from ai_modules import fusion
    fusion.reset_cache("AST-003")     # no earlier value for Ryan: fusion falls back to his median
    base = ai.get_baseline("AST-003")
    vector = ai.build_health_vector({"hr": 70}, {}, {}, base)
    assert vector["sleep_quality"] == base["baseline_detail"]["sleep_quality"]["center"]
    assert vector["resp_rate"] == base["baseline_detail"]["resp_rate"]["center"]
    assert "sleep_quality" in vector["imputed"]


def test_normalize_fixes_bad_model_output():
    out = _normalize_risk({"risk_score": 140.7, "level": "HIGH",
                           "top_factors": [{"feature": "hr", "change_pct": "12"}, "junk"]})
    assert out == {"risk_score": 100, "level": "Emergency",
                   "top_factors": [{"feature": "hr", "change_pct": 12.0}], "recommendation": ""}


def test_shown_score_always_matches_the_level():
    from app.ai import _normalize_risk
    assert _normalize_risk({"risk_score": 49.9, "level": "Attention"})["risk_score"] == 49
    assert _normalize_risk({"risk_score": 74.6, "level": "High Risk"})["risk_score"] == 74
    assert _normalize_risk({"risk_score": 60.2, "level": "High Risk"})["risk_score"] == 60
