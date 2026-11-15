import numpy as np
import pandas as pd
import pytest

from astroguardian_digital_twin.data_cleaning import CANONICAL_COLUMNS, clean_wearable_data
from astroguardian_digital_twin.feature_engineering import engineer_features
from conftest import make_frame


def _day(i):
    return (pd.Timestamp("2026-08-25T00:00:00Z") + pd.Timedelta(days=i)).isoformat()


def test_canonical_columns_present_and_first(pipeline):
    assert list(pipeline.features.columns[:12]) == CANONICAL_COLUMNS


def test_rolling_mean_uses_exactly_current_and_past_24h(pipeline):
    clean, feats = pipeline.clean, pipeline.features
    g = clean[clean["astronaut_id"] == "AST-002"].reset_index(drop=True)
    f = feats[feats["astronaut_id"] == "AST-002"].reset_index(drop=True)
    for i in (30, 500, 1000):
        t = g.loc[i, "timestamp"]
        window = g[(g["timestamp"] > t - pd.Timedelta(hours=24)) & (g["timestamp"] <= t)]
        assert len(window) == 24
        assert f.loc[i, "hr_roll24h_mean"] == pytest.approx(window["hr"].mean())
        assert f.loc[i, "hr_roll24h_std"] == pytest.approx(window["hr"].std())


def test_rolling_does_not_cross_astronauts(pipeline):
    f = pipeline.features
    first = f.groupby("astronaut_id").head(1)
    assert first["hr_roll24h_mean"].isna().all()          # min_periods not met at first row


def test_no_future_leakage_truncation_invariance(pipeline):
    """Features at time t must not change if all later data is removed."""
    clean, full = pipeline.clean, pipeline.features
    cut = clean[clean["mission_day"] <= 25]
    part = engineer_features(cut, calibration_days=14)
    ref = full[full["mission_day"] <= 25]
    cols = [c for c in part.columns if c in ref.columns and not c.endswith("_pct_dev") and c != "temp_delta_c"]
    pd.testing.assert_frame_equal(part[cols].reset_index(drop=True), ref[cols].reset_index(drop=True),
                                  check_exact=False, rtol=1e-9, atol=1e-9)


def test_changing_future_data_does_not_change_past_features(pipeline):
    clean = pipeline.clean.copy()
    base = engineer_features(clean, calibration_days=14)
    mutated = clean.copy()
    late = mutated["mission_day"] > 30
    mutated.loc[late, "hr"] += 40
    mutated.loc[late, "sleep_hours"] = 2.0
    alt = engineer_features(mutated, calibration_days=14)
    early = base["mission_day"] <= 30
    cols = [c for c in base.columns if base[c].dtype.kind == "f"]
    pd.testing.assert_frame_equal(base.loc[early, cols], alt.loc[early, cols])


def test_sleep_debt_formula():
    days = [7.0, 6.0, 8.0, 5.0, 9.0]
    frames = [make_frame(24, start=_day(i), sleep_hours=s) for i, s in enumerate(days)]
    clean, _ = clean_wearable_data(pd.concat(frames, ignore_index=True), mission_start="2026-08-25T00:00:00Z")
    out = engineer_features(clean, {"sleep_need_hours": 8.0})
    debt = out.groupby("mission_day")["sleep_debt_7d"].first().tolist()
    assert debt == [1.0, 3.0, 3.0, 6.0, 6.0]             # deficits 1,2,0,3,0 accumulated
    mean7 = out.groupby("mission_day")["sleep_hours_roll7d_mean"].first().tolist()
    assert mean7[-1] == pytest.approx(np.mean(days))


def test_sleep_debt_window_drops_old_days():
    days = [4.0] + [8.0] * 7                              # a 4 h night (deficit 4) leaves the 7-day window
    frames = [make_frame(24, start=_day(i), sleep_hours=s) for i, s in enumerate(days)]
    clean, _ = clean_wearable_data(pd.concat(frames, ignore_index=True), mission_start="2026-08-25T00:00:00Z")
    out = engineer_features(clean, {"sleep_need_hours": 8.0})
    debt = out.groupby("mission_day")["sleep_debt_7d"].first()
    assert debt.iloc[6] == 4.0 and debt.iloc[7] == 0.0


def test_stress_score_range_warmup_and_ordering(pipeline):
    f = pipeline.features
    assert f["stress_score"].dropna().between(0, 100).all()
    first_day = f[(f["mission_day"] == 1)]
    assert first_day.groupby("astronaut_id")["stress_score"].apply(lambda s: s.isna().any()).all()
    post = f[f["mission_day"] > 14]
    ahmed = post[post["astronaut_id"] == "AST-001"]["stress_score"].mean()
    omar_last = f[(f["astronaut_id"] == "AST-003") & (f["mission_day"] >= 58)]["stress_score"].mean()
    assert 15 < ahmed < 35 and omar_last > 80


def test_stress_reference_ignores_post_calibration_data(pipeline):
    clean = pipeline.clean.copy()
    clean.loc[clean["mission_day"] > 14, "hr"] = 150.0
    alt = engineer_features(clean, calibration_days=14)
    base = pipeline.features
    m = base["mission_day"] <= 14
    pd.testing.assert_series_equal(base.loc[m, "stress_score"], alt.loc[m, "stress_score"])


def test_is_calibration_flag(pipeline):
    f = pipeline.features
    assert (f["is_calibration"] == (f["mission_day"] <= 14)).all()
