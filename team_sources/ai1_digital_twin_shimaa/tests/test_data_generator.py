import pandas as pd
import pytest

from astroguardian_digital_twin.data_cleaning import DEFAULT_VALID_RANGES, check_daily_consistency
from astroguardian_digital_twin.data_generator import (MISSION_START, generate_dataset,
                                                       get_astronaut_specs, inject_faults, severity)


@pytest.fixture(scope="module")
def raw():
    return generate_dataset(seed=42)


def test_deterministic_for_fixed_seed(raw):
    pd.testing.assert_frame_equal(raw, generate_dataset(seed=42))


def test_different_seed_changes_data(raw):
    other = generate_dataset(seed=43)
    assert not raw["hr"].equals(other["hr"])


def test_ten_astronauts_sixty_days_hourly(raw):
    assert raw["astronaut_id"].nunique() == 10
    for aid, g in raw.groupby("astronaut_id"):
        assert len(g) == 60 * 24
        assert g["mission_day"].min() == 1 and g["mission_day"].max() == 60
        assert (g.groupby("mission_day").size() == 24).all()


def test_timestamps_unique_ordered_hourly(raw):
    for aid, g in raw.groupby("astronaut_id"):
        assert g["timestamp"].is_unique and g["timestamp"].is_monotonic_increasing
        assert (g["timestamp"].diff().dropna() == pd.Timedelta(hours=1)).all()
        assert g["timestamp"].iloc[0] == pd.Timestamp(MISSION_START)


def test_daily_values_constant_within_day(raw):
    assert check_daily_consistency(raw, ("sleep_hours", "sleep_quality", "exercise_score")).empty


def test_values_within_bounds_and_no_nan(raw):
    for col, (lo, hi) in DEFAULT_VALID_RANGES.items():
        if col in raw.columns:
            assert raw[col].notna().all()
            assert raw[col].between(lo, hi).all(), col


def test_labeled_synthetic(raw):
    assert raw["is_synthetic"].all()


def test_each_astronaut_has_distinct_personal_level(raw):
    cal = raw[raw["mission_day"] <= 14].groupby("astronaut_id")["hr"].median()
    assert cal.round(1).nunique() == 10


def test_circadian_pattern_hr_lower_at_night(raw):
    g = raw[raw["astronaut_id"] == "AST-001"].copy()
    h = g["timestamp"].dt.hour
    assert g.loc[h.isin([2, 3, 4]), "hr"].mean() < g.loc[h.isin([14, 15, 16]), "hr"].mean() - 2


def test_calibration_days_unaffected_by_scenarios(raw):
    for aid, g in raw.groupby("astronaut_id"):
        cal = g[g["mission_day"] <= 14]
        later = g[(g["mission_day"] > 14) & (g["mission_day"] <= 25)]
        assert abs(cal["hr"].mean() - later["hr"].mean()) < 3.0


def test_scenario_severity_shapes():
    import numpy as np
    t = np.array([0.0, 38.9, 50.0, 59.99, 54.9, 55.1])
    sara, omar = severity("attention", t), severity("emergency", t)
    assert sara[0] == 0 and sara[1] == 0 and 0 < sara[2] < sara[3] <= 1
    assert omar[4] == 0 and omar[5] > 0.3 and (omar[[0, 1, 2, 4]] == 0).all() and omar[3] > 0.9
    assert (severity("normal", t) == 0).all()


def test_demo_astronaut_specs():
    specs = {s.astronaut_id: s for s in get_astronaut_specs(42)}
    assert [specs[i].name for i in ("AST-001", "AST-002", "AST-003")] == ["Ahmed", "Sara", "Omar"]
    assert len(specs) == 10


def test_inject_faults_is_reproducible(raw):
    a, ca = inject_faults(raw.head(2000), seed=1)
    b, cb = inject_faults(raw.head(2000), seed=1)
    pd.testing.assert_frame_equal(a, b)
    assert ca == cb and ca["missing_cells_injected"] > 0
