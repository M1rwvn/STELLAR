import json

import pandas as pd
import pytest

from astroguardian_digital_twin.data_cleaning import CANONICAL_COLUMNS
from astroguardian_digital_twin.demo_scenarios import (DEMO_SCENARIOS, daily_table, evaluate_demo_patterns,
                                                       file_sha256, write_demo_artifacts)
from astroguardian_digital_twin.profiles import run_pipeline


def test_expected_patterns_seed_42(pipeline):
    ev = evaluate_demo_patterns(pipeline)
    assert ev["distinct_baselines"] and ev["ahmed_stable"] and ev["sara_progressive"] and ev["omar_emergency_pattern"]


@pytest.mark.parametrize("seed", [7, 2024])
def test_patterns_hold_for_other_seeds(seed):
    assert evaluate_demo_patterns(run_pipeline(seed=seed))["all_passed"]


def test_ahmed_stays_in_personal_pattern(pipeline):
    f = pipeline.features
    a = f[(f.astronaut_id == "AST-001") & (f.mission_day > 14)]
    assert a["hr_pct_dev"].abs().mean() < 5          # hourly: includes the normal circadian swing
    assert daily_table(f, "AST-001")["hr_pct_dev"].abs().mean() < 3
    assert 15 < a["stress_score"].mean() < 35
    daily = daily_table(f, "AST-001")
    assert daily["hr_pct_dev"].abs().max() < 5            # no day drifts far from his own baseline


def test_sara_deviations_grow_progressively(pipeline):
    d = daily_table(pipeline.features, "AST-002")
    pre, early, mid, late = (d.loc[a:b, "sleep_hours_pct_dev"].mean() for a, b in [(15, 39), (41, 47), (48, 54), (55, 60)])
    assert pre > early > mid > late
    assert abs(pre) < 6 and late < -12                    # ~7h -> ~5.5h
    hr = [d.loc[a:b, "hr_pct_dev"].mean() for a, b in [(15, 39), (41, 47), (48, 54), (55, 60)]]
    assert hr == sorted(hr) and hr[-1] > 5
    act = [d.loc[a:b, "activity_pct_dev"].mean() for a, b in [(15, 39), (41, 47), (48, 54), (55, 60)]]
    assert act == sorted(act, reverse=True) and act[-1] < -10


def test_sara_changes_start_around_day_40(pipeline):
    d = daily_table(pipeline.features, "AST-002")
    assert d.loc[15:38, "sleep_hours_pct_dev"].abs().mean() < 6
    assert d.loc[55:60, "sleep_hours_pct_dev"].mean() < d.loc[15:38, "sleep_hours_pct_dev"].mean() - 10


def test_omar_final_five_days_show_injected_changes(pipeline):
    f = pipeline.features
    o = f[f.astronaut_id == "AST-003"]
    last, calm = o[o.mission_day >= 56], o[(o.mission_day > 14) & (o.mission_day < 56)]
    assert last["hr_pct_dev"].mean() > 15 and daily_table(f, "AST-003").loc[15:55, "hr_pct_dev"].abs().mean() < 3
    assert last["hrv_pct_dev"].mean() < -25 and last["spo2_pct_dev"].mean() < -2
    assert last["sleep_hours_pct_dev"].mean() < -25 and last["temp_delta_c"].mean() > 0.5
    final = o[o.mission_day == 60]
    assert final["spo2"].mean() < 94.5 and final["temp"].mean() > 37.4 and final["sleep_hours"].mean() < 4.6
    assert last["stress_score"].mean() > calm["stress_score"].mean() + 40
    # onset is clean: nothing unusual in the days just before day 56
    assert daily_table(f, "AST-003").loc[50:55, "hr_pct_dev"].abs().mean() < 3


def test_calibration_period_free_of_scenario_effects(pipeline):
    f = pipeline.raw
    for aid in ("AST-002", "AST-003"):
        g = f[f.astronaut_id == aid]
        cal, nxt = g[g.mission_day <= 14], g[(g.mission_day > 14) & (g.mission_day <= 30)]
        assert abs(cal["sleep_hours"].mean() - nxt["sleep_hours"].mean()) < 0.5


def test_write_artifacts_and_reproducibility(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    m = write_demo_artifacts(a, seed=42)
    write_demo_artifacts(b, seed=42)
    for name, (aid, fname, _) in DEMO_SCENARIOS.items():
        df = pd.read_csv(a / "data/demo" / fname)
        assert len(df) == 1440 and set(df.astronaut_id) == {aid}
        assert list(df.columns[:12]) == CANONICAL_COLUMNS
        assert df["timestamp"].is_monotonic_increasing and df["is_synthetic"].all()
        assert file_sha256(a / "data/demo" / fname) == file_sha256(b / "data/demo" / fname)
    assert (a / "outputs/profiles/all_profiles.json").read_bytes() == (b / "outputs/profiles/all_profiles.json").read_bytes()
    assert m["report"]["pattern_checks"]["all_passed"]
    json.loads((a / "outputs/demo_report.json").read_text())


def test_demo_csvs_consumable_by_downstream_without_extra_cleaning(tmp_path):
    write_demo_artifacts(tmp_path, seed=42)
    df = pd.read_csv(tmp_path / "data/demo/ahmed_normal.csv")
    core = ["hr", "hrv", "spo2", "resp_rate", "temp", "sleep_hours", "sleep_quality", "activity", "exercise_score"]
    assert df[core].notna().all().all()
    assert df["stress_score"].isna().sum() < 20          # only the documented warm-up hours
