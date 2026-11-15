import numpy as np
import pandas as pd
import pytest

from astroguardian_digital_twin.baseline import (build_baselines, compute_astronaut_baseline,
                                                 compute_feature_baseline, load_config, validate_config)


def test_calibration_limited_to_first_14_days(pipeline):
    b = pipeline.baselines["AST-001"]
    cal = b["calibration"]
    assert cal["start"] == "2026-08-25T00:00:00Z" and cal["end"] == "2026-09-07T23:00:00Z"
    assert cal["n_rows"] == 14 * 24 and cal["n_days_present"] == 14 and cal["complete"]
    assert b["features"]["hr"]["n_samples"] == 336
    assert b["features"]["sleep_hours"]["n_samples"] == 14          # one value per day, not 336


def test_center_is_median_and_median_mad_interval_of_calibration_data(pipeline):
    f = pipeline.features
    g = f[(f["astronaut_id"] == "AST-002") & (f["mission_day"] <= 14)]
    hr = pipeline.baselines["AST-002"]["features"]["hr"]
    med = g["hr"].median()
    mad = 1.4826 * (g["hr"] - med).abs().median()
    k = load_config()["baseline"]["dispersion_k"]
    assert k == 2.0
    assert hr["center"] == pytest.approx(med)
    assert hr["low"] == pytest.approx(med - k * mad)
    assert hr["high"] == pytest.approx(med + k * mad)
    assert hr["low"] < hr["center"] < hr["high"]


@pytest.mark.parametrize("astronaut_id", ["AST-001", "AST-002", "AST-003"])
def test_normal_range_contains_most_normal_readings(pipeline, astronaut_id):
    """The range the app shows as 'your normal' must not flag half of a healthy person's readings."""
    f = pipeline.features
    cal = f[(f["astronaut_id"] == astronaut_id) & (f["mission_day"] <= 14)]
    for m in ("hr", "hrv", "spo2", "temp", "resp_rate"):
        d = pipeline.profiles[astronaut_id]["baseline_detail"][m]
        inside = cal[m].between(d["low"], d["high"]).mean()
        assert inside >= 0.90, (m, inside)


def test_baselines_differ_between_astronauts(pipeline):
    centers = {a: b["features"]["hr"]["center"] for a, b in pipeline.baselines.items()}
    assert len({round(c, 1) for c in centers.values()}) == 10


def test_baseline_ignores_everything_after_day_14(pipeline):
    f = pipeline.features
    tampered = f.copy()
    late = tampered["mission_day"] > 14
    for c in ("hr", "hrv", "spo2", "temp", "sleep_hours", "activity"):
        tampered.loc[late, c] = 0.0
    assert build_baselines(tampered) == pipeline.baselines


def test_baseline_stable_under_later_deterioration(pipeline):
    f = pipeline.features
    only14 = f[f["mission_day"] <= 14]
    for aid in ("AST-002", "AST-003"):
        a = compute_astronaut_baseline(only14[only14["astronaut_id"] == aid])
        b = compute_astronaut_baseline(f[f["astronaut_id"] == aid])
        assert a == b


def test_demo_hr_baselines_match_design_ranges(pipeline):
    c = pipeline.baselines["AST-001"]["features"]["hr"]
    assert 60 < c["center"] < 65


def test_constant_feature_handled():
    r = compute_feature_baseline([5.0] * 300, "hr", "hourly")
    assert r["status"] == "constant" and r["center"] == r["low"] == r["high"] == 5.0
    assert r["robust_sigma"] is None


def test_insufficient_and_empty_data_handled():
    assert compute_feature_baseline([1.0] * 10, "hr", "hourly")["status"] == "insufficient_data"
    assert compute_feature_baseline([1.0] * 10, "hr", "hourly")["center"] is None
    assert compute_feature_baseline([np.nan] * 400, "hr", "hourly")["status"] == "no_data"
    assert compute_feature_baseline([1, 2, 3, 4, 5, 6], "sleep_hours", "daily")["status"] == "insufficient_data"


def test_nan_values_ignored_in_statistics():
    vals = list(range(1, 201)) + [np.nan] * 50
    r = compute_feature_baseline(vals, "hr", "hourly")
    assert r["n_samples"] == 200 and r["center"] == pytest.approx(100.5)


def test_interval_methods_formulas():
    vals = np.arange(1.0, 10.0)                       # 1..9, median 5, MAD = 2
    # stress_score (0-100) so the plausibility clamp does not touch these toy values
    cfg = load_config()
    cfg["baseline"].update(min_hourly_samples=1, dispersion_k=1.5)
    cfg["baseline"]["interval_method_overrides"] = {"stress_score": "iqr"}
    r = compute_feature_baseline(vals, "stress_score", "hourly", cfg)
    assert (r["low"], r["center"], r["high"]) == (3.0, 5.0, 7.0)          # Q1, median, Q3
    cfg["baseline"]["interval_method_overrides"] = {"stress_score": "median_mad"}
    r = compute_feature_baseline(vals, "stress_score", "hourly", cfg)
    assert r["low"] == pytest.approx(5 - 1.5 * 1.4826 * 2) and r["high"] == pytest.approx(5 + 1.5 * 1.4826 * 2)
    cfg["baseline"]["interval_method_overrides"] = {"stress_score": "mean_std"}
    r = compute_feature_baseline(vals, "stress_score", "hourly", cfg)
    assert r["center"] == 5.0 and r["low"] == pytest.approx(5 - 1.5 * vals.std(ddof=1))


def test_missing_feature_column_gives_no_data():
    from conftest import make_frame
    from astroguardian_digital_twin.data_cleaning import add_mission_day
    df = add_mission_day(make_frame(400))
    b = compute_astronaut_baseline(df)
    assert b["features"]["stress_score"]["status"] == "no_data"
    assert b["features"]["hr"]["status"] == "ok"


def test_single_astronaut_required():
    from conftest import make_frame
    from astroguardian_digital_twin.data_cleaning import add_mission_day
    df = add_mission_day(pd.concat([make_frame(5, "A"), make_frame(5, "B")]))
    with pytest.raises(ValueError, match="exactly one astronaut"):
        compute_astronaut_baseline(df)


def test_config_validation():
    cfg = load_config()
    cfg["baseline"]["default_interval_method"] = "magic"
    with pytest.raises(ValueError):
        validate_config(cfg)
    cfg = load_config()
    cfg["baseline"]["calibration_days"] = 0
    with pytest.raises(ValueError):
        validate_config(cfg)
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/config.json")


def test_json_config_matches_defaults():
    cfg = load_config()
    assert cfg["baseline"]["calibration_days"] == 14 and cfg["baseline"]["default_interval_method"] == "median_mad"


def test_intervals_stay_inside_plausible_ranges(pipeline):
    """median +/- 2 SD must not produce impossible values (negative stress, SpO2 > 100, ...)."""
    from astroguardian_digital_twin.data_cleaning import DEFAULT_VALID_RANGES
    for aid, prof in pipeline.profiles.items():
        for m, d in prof["baseline_detail"].items():
            lo, hi = DEFAULT_VALID_RANGES[m]
            if d["low"] is not None:
                assert lo <= d["low"] <= d["center"] <= d["high"] <= hi, (aid, m, d)
