import numpy as np
import pandas as pd
import pytest

from astroguardian_digital_twin.data_cleaning import (DataValidationError, clean_wearable_data,
                                                      validate_columns)
from astroguardian_digital_twin.data_generator import generate_dataset, inject_faults
from conftest import make_frame


def test_missing_required_column_raises():
    df = make_frame().drop(columns=["hr"])
    with pytest.raises(DataValidationError, match="hr"):
        clean_wearable_data(df)
    with pytest.raises(DataValidationError):
        validate_columns("not a dataframe")


def test_clean_input_is_unchanged_and_reports_zeros():
    df = make_frame(30)
    out, rep = clean_wearable_data(df)
    assert len(out) == 30 and rep.invalid_records_total == 0 and rep.imputed_values == 0
    assert rep.duplicate_rows_removed == 0 and rep.rows_in == rep.rows_out == 30
    np.testing.assert_allclose(out["hr"], df["hr"])


def test_duplicates_removed_and_counted():
    df = make_frame(10)
    df = pd.concat([df, df.iloc[[2, 5]]], ignore_index=True)
    out, rep = clean_wearable_data(df)
    assert rep.duplicate_rows_removed == 2 and len(out) == 10


def test_out_of_range_and_non_numeric_become_missing_then_handled():
    df = make_frame(10)
    df["hr"] = df["hr"].astype(object)
    df.loc[3, "hr"] = 999            # out of range -> NaN -> causal fill from row 2
    df.loc[6, "hr"] = "abc"          # non numeric
    out, rep = clean_wearable_data(df)
    assert rep.out_of_range_values == 1 and rep.non_numeric_values == 1
    assert rep.out_of_range_by_column == {"hr": 1}
    assert rep.imputed_values == 2 and rep.corrected_values == 2
    assert out.loc[out["timestamp"] == df["timestamp"][3], "hr"].iloc[0] == 62.0  # value of row 2
    assert out["was_imputed"].sum() == 2


def test_invalid_timestamp_and_astronaut_id_rows_dropped():
    df = make_frame(6)
    df["timestamp"] = df["timestamp"].astype(str)
    df.loc[1, "timestamp"] = "not a time"
    df["astronaut_id"] = df["astronaut_id"].astype(object)
    df.loc[2, "astronaut_id"] = None
    out, rep = clean_wearable_data(df)
    assert rep.invalid_timestamp_rows == 1 and rep.invalid_astronaut_id_rows == 1 and len(out) == 4
    assert str(out["timestamp"].dt.tz) == "UTC"


def test_never_fills_across_astronauts():
    a = make_frame(5, aid="A")
    b = make_frame(5, aid="B")
    b.loc[0, "hr"] = np.nan                       # first row of B has no past value of its OWN
    out, rep = clean_wearable_data(pd.concat([a, b], ignore_index=True))
    assert rep.imputed_values == 0 and rep.unrecoverable_rows_dropped == 1
    assert len(out[out["astronaut_id"] == "B"]) == 4
    assert out[out["astronaut_id"] == "A"]["hr"].tolist() == a["hr"].tolist()


def test_ffill_is_causal_and_time_limited():
    df = make_frame(10)
    df.loc[2:6, "hr"] = np.nan                    # 5 consecutive missing hours
    out, rep = clean_wearable_data(df)            # default limit: 3 hours old
    assert rep.imputed_values == 3 and rep.unrecoverable_rows_dropped == 2
    filled = out.set_index("timestamp")["hr"]
    assert (filled.iloc[2:5] == df["hr"].iloc[1]).all()   # filled from the PAST value only
    assert len(out) == 8


def test_first_row_missing_is_not_backfilled():
    df = make_frame(5)
    df.loc[0, "hr"] = np.nan
    out, rep = clean_wearable_data(df)
    assert len(out) == 4 and rep.unrecoverable_rows_dropped == 1


def test_output_sorted_by_astronaut_and_timestamp():
    df = pd.concat([make_frame(5, "B"), make_frame(5, "A")]).sample(frac=1, random_state=3)
    out, _ = clean_wearable_data(df)
    keys = list(zip(out["astronaut_id"], out["timestamp"]))
    assert keys == sorted(keys)


def test_pipeline_report_on_injected_faults_matches_injection():
    raw = generate_dataset(seed=42).head(3000)
    bad, counts = inject_faults(raw, seed=5)
    out, rep = clean_wearable_data(bad)
    assert rep.duplicate_rows_removed == counts["duplicates_injected"]
    assert rep.out_of_range_values == counts["invalid_hr_injected"]
    assert rep.missing_values_original >= counts["missing_cells_injected"] - counts["duplicates_injected"] * 6
    assert out.duplicated(["astronaut_id", "timestamp"]).sum() == 0
    assert out[["hr", "hrv", "spo2", "resp_rate", "temp", "activity"]].notna().all().all()


def test_mission_start_drops_earlier_rows_and_counts():
    df = make_frame(5, start="2026-08-24T22:00:00Z")
    out, rep = clean_wearable_data(df, mission_start="2026-08-25T00:00:00Z")
    assert rep.rows_before_mission_start_dropped == 2 and out["mission_day"].min() == 1


def test_bad_config_rejected():
    with pytest.raises(ValueError):
        clean_wearable_data(make_frame(), {"duplicate_keep": "middle"})
