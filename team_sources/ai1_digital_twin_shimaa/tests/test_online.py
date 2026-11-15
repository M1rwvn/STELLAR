"""Train/serve parity: online_features (runtime, 7 days of history) == engineer_features (training)."""
import math
from pathlib import Path

import pandas as pd
import pytest

from astroguardian_digital_twin.data_cleaning import WEARABLE_FIELDS
from astroguardian_digital_twin.online import online_features

ROOT = Path(__file__).resolve().parents[1]
HISTORY_HOURS = 168

ROLLING = [f"{f}_roll{w}h_mean" for f in ("hr", "hrv", "spo2", "resp_rate", "temp", "activity")
           for w in (24, 168)] + ["hr_roll24h_std", "sleep_debt_7d", "sleep_hours_roll7d_mean"]
DEVIATIONS = ["hr_pct_dev", "hrv_pct_dev", "spo2_pct_dev", "resp_rate_pct_dev", "temp_delta_c",
              "sleep_hours_pct_dev", "sleep_quality_pct_dev", "activity_pct_dev",
              "stress_score_pct_dev"]


def _history(df: pd.DataFrame, t: pd.Timestamp) -> list[dict]:
    win = df[(df["timestamp"] > t - pd.Timedelta(hours=HISTORY_HOURS)) & (df["timestamp"] <= t)]
    return [{"timestamp": r.timestamp.to_pydatetime(), **{k: getattr(r, k) for k in WEARABLE_FIELDS}}
            for r in win.itertuples()]


def _same(expected, actual, tol):
    if expected is None or (isinstance(expected, float) and math.isnan(expected)):
        return actual is None
    return actual is not None and abs(float(expected) - actual) <= tol


@pytest.mark.parametrize("astronaut_id", [f"AST-{i:03d}" for i in range(1, 11)])
def test_online_features_equal_training_features(pipeline, astronaut_id):
    feats = pipeline.features
    df = feats[feats["astronaut_id"] == astronaut_id].sort_values("timestamp").reset_index(drop=True)
    profile = pipeline.profiles[astronaut_id]
    # every 7th hour from day 8 (full 7-day window) to day 60: ~180 checks per astronaut
    checked = 0
    for row in df[df["mission_day"] >= 8].iloc[::7].itertuples():
        online = online_features(_history(df, row.timestamp), profile)
        for col in ROLLING + DEVIATIONS:
            assert _same(getattr(row, col), online[col], 1e-6), (astronaut_id, row.timestamp, col)
        if row.mission_day > 14:  # stress reference is frozen after calibration
            assert _same(row.stress_score, online["stress_score"], 1e-6), (astronaut_id, row.timestamp)
        else:
            assert online["stress_score"] is None
        checked += 1
    assert checked > 150


def test_parity_with_the_delivered_demo_csv():
    """The exact file Menna trains on (4 decimals) matches what the backend computes at runtime."""
    from astroguardian_digital_twin import get_baseline
    df = pd.read_csv(ROOT / "data/demo/omar_emergency.csv", parse_dates=["timestamp"])
    profile = get_baseline("AST-003")
    for row in df[df["mission_day"].isin([20, 45, 57, 60])].iloc[::5].itertuples():
        online = online_features(_history(df, row.timestamp), profile)
        for col in ROLLING + DEVIATIONS + ["stress_score"]:
            assert _same(getattr(row, col), online[col], 1e-3), (row.timestamp, col)


def test_accepts_contract_payloads_and_any_order(pipeline):
    df = pipeline.features[pipeline.features["astronaut_id"] == "AST-002"].sort_values("timestamp")
    t = df[df["mission_day"] == 50]["timestamp"].iloc[12]
    flat = _history(df, t)
    payloads = [{"astronaut_id": "AST-002", "timestamp": r["timestamp"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "wearable": {k: r[k] for k in WEARABLE_FIELDS}} for r in reversed(flat)]
    assert online_features(payloads, pipeline.profiles["AST-002"]) == online_features(
        flat, pipeline.profiles["AST-002"])


def test_short_history_gives_none_not_guesses(pipeline):
    df = pipeline.features[pipeline.features["astronaut_id"] == "AST-001"].sort_values("timestamp")
    one = _history(df, df["timestamp"].iloc[30 * 24])[-1:]
    out = online_features(one, pipeline.profiles["AST-001"])
    assert out["hr_roll24h_mean"] is None and out["hr_roll24h_std"] is None
    assert out["stress_score"] is None            # needs >= 3 readings in 6 h
    assert out["sleep_debt_7d"] is not None       # today's daily value is enough
    assert out["hr_pct_dev"] is not None          # deviation needs only the current reading


def test_missing_sensor_values_are_skipped(pipeline):
    df = pipeline.features[pipeline.features["astronaut_id"] == "AST-003"].sort_values("timestamp")
    hist = _history(df, df["timestamp"].iloc[40 * 24])
    hist[-1]["spo2"] = None
    hist[-2]["hr"] = float("nan")
    out = online_features(hist, pipeline.profiles["AST-003"])
    assert out["spo2_pct_dev"] is None and out["hr_roll24h_mean"] is not None


def test_profile_without_reference_is_rejected():
    with pytest.raises(ValueError, match="online_reference"):
        online_features([{"timestamp": "2026-10-01T00:00:00Z", "hr": 60}], {"baseline": {}})
