"""Data validation and cleaning for wearable data (synthetic in this project).

Rules (all configurable, see ``DEFAULT_CLEANING_CONFIG``):

* required columns/types are validated; timestamps are parsed as UTC;
* duplicates on (astronaut_id, timestamp) are removed (first record kept);
* non-numeric and out-of-range values become missing (NaN) and are counted;
* missing values are filled ONLY with a *causal* forward fill (uses past values
  only), limited in time, and NEVER across astronaut IDs.  No interpolation
  and no back-fill, because both would use future information;
* rows that are still incomplete are dropped (configurable);
* output is sorted by astronaut and timestamp.

The valid ranges are *plausibility bounds for synthetic inputs*.  They are NOT
medical reference intervals.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

CANONICAL_COLUMNS = [
    "astronaut_id", "timestamp", "hr", "hrv", "spo2", "resp_rate", "temp",
    "sleep_hours", "sleep_quality", "activity", "stress_score", "exercise_score",
]
WEARABLE_FIELDS = (
    "hr", "hrv", "spo2", "resp_rate", "temp", "sleep_hours", "sleep_quality", "activity",
)
REQUIRED_COLUMNS = ["astronaut_id", "timestamp", *WEARABLE_FIELDS]
OPTIONAL_NUMERIC = ["exercise_score", "stress_score"]
HOURLY_COLUMNS = ["hr", "hrv", "spo2", "resp_rate", "temp", "activity"]
DAILY_COLUMNS = ["sleep_hours", "sleep_quality", "exercise_score"]

FEATURE_UNITS = {
    "hr": "bpm", "hrv": "ms", "spo2": "%", "resp_rate": "breaths/min", "temp": "degC",
    "sleep_hours": "hours/day", "sleep_quality": "score 0-1", "activity": "score 0-1",
    "stress_score": "score 0-100", "exercise_score": "score 0-100",
}

# Plausibility bounds for SYNTHETIC inputs (not medical reference ranges).
DEFAULT_VALID_RANGES: dict[str, tuple[float, float]] = {
    "hr": (30.0, 220.0), "hrv": (5.0, 200.0), "spo2": (70.0, 100.0),
    "resp_rate": (4.0, 60.0), "temp": (33.0, 42.0), "sleep_hours": (0.0, 16.0),
    "sleep_quality": (0.0, 1.0), "activity": (0.0, 1.0),
    "stress_score": (0.0, 100.0), "exercise_score": (0.0, 100.0),
}

DEFAULT_CLEANING_CONFIG: dict[str, Any] = {
    "valid_ranges": {k: list(v) for k, v in DEFAULT_VALID_RANGES.items()},
    "max_ffill_hours": 3,                 # hourly signals: fill gaps up to 3 h old
    "max_ffill_hours_daily_features": 24, # daily signals (sleep): up to 24 h old
    "duplicate_keep": "first",            # "first" | "last"
    "drop_unrecoverable": True,           # drop rows still missing a required value
}


class DataValidationError(ValueError):
    """Raised when the input table does not meet the schema requirements."""


@dataclass
class CleaningReport:
    """Counts of everything the cleaning pipeline found or changed."""

    rows_in: int = 0
    rows_out: int = 0
    invalid_astronaut_id_rows: int = 0
    invalid_timestamp_rows: int = 0
    rows_before_mission_start_dropped: int = 0
    duplicate_rows_removed: int = 0
    missing_values_original: int = 0
    non_numeric_values: int = 0
    out_of_range_values: int = 0
    out_of_range_by_column: dict = field(default_factory=dict)
    imputed_values: int = 0
    unrecoverable_rows_dropped: int = 0

    @property
    def invalid_records_total(self) -> int:
        """Rows dropped as invalid plus cells invalidated (bad type/out of range)."""
        return (self.invalid_astronaut_id_rows + self.invalid_timestamp_rows
                + self.non_numeric_values + self.out_of_range_values)

    @property
    def corrected_values(self) -> int:
        """Cells repaired by the documented causal forward fill."""
        return self.imputed_values

    def to_dict(self) -> dict:
        d = asdict(self)
        d["invalid_records_total"] = self.invalid_records_total
        d["corrected_values"] = self.corrected_values
        return d


def _merge_config(config: Optional[Mapping[str, Any]]) -> dict:
    cfg = copy.deepcopy(DEFAULT_CLEANING_CONFIG)
    if config:
        for key, value in config.items():
            if key == "valid_ranges":
                cfg["valid_ranges"].update({k: list(v) for k, v in value.items()})
            else:
                cfg[key] = value
    if cfg["duplicate_keep"] not in ("first", "last"):
        raise ValueError("cleaning config 'duplicate_keep' must be 'first' or 'last'")
    return cfg


def validate_columns(df: pd.DataFrame) -> None:
    """Raise DataValidationError if required columns are missing."""
    if not isinstance(df, pd.DataFrame):
        raise DataValidationError(f"Expected a pandas DataFrame, got {type(df).__name__}")
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise DataValidationError(f"Missing required column(s): {missing}")


def _parse_timestamps(col: pd.Series) -> pd.Series:
    """Parse to timezone-aware UTC; unparseable values become NaT."""
    if pd.api.types.is_datetime64_any_dtype(col):
        return pd.to_datetime(col, utc=True)
    return pd.to_datetime(col.astype("object"), utc=True, errors="coerce", format="ISO8601")


def add_mission_day(df: pd.DataFrame, mission_start: Any = None) -> pd.DataFrame:
    """Add ``mission_day`` (1-based). Day 1 starts at ``mission_start`` (UTC)."""
    out = df.copy()
    if mission_start is None:
        start = out["timestamp"].min().normalize()
    else:
        start = pd.Timestamp(mission_start)
        start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
    out["mission_day"] = ((out["timestamp"] - start) // pd.Timedelta(days=1)).astype(int) + 1
    return out


def _causal_ffill(df: pd.DataFrame, col: str, max_age: pd.Timedelta) -> tuple[pd.Series, pd.Series]:
    """Forward-fill ``col`` within each astronaut, only from values <= max_age old."""
    grp = df["astronaut_id"]
    last_valid_ts = df["timestamp"].where(df[col].notna()).groupby(grp).ffill()
    filled = df[col].groupby(grp).ffill()
    age = df["timestamp"] - last_valid_ts
    fill_mask = df[col].isna() & filled.notna() & (age <= max_age)
    result = df[col].copy()
    result[fill_mask] = filled[fill_mask]
    return result, fill_mask


def clean_wearable_data(
    df: pd.DataFrame,
    config: Optional[Mapping[str, Any]] = None,
    mission_start: Any = None,
) -> tuple[pd.DataFrame, CleaningReport]:
    """Validate and clean a wearable table. Returns ``(clean_df, report)``."""
    cfg = _merge_config(config)
    validate_columns(df)
    report = CleaningReport(rows_in=len(df))
    out = df.copy()

    # 1) astronaut id
    ids = out["astronaut_id"]
    bad_id = ids.isna() | (ids.astype(str).str.strip() == "")
    report.invalid_astronaut_id_rows = int(bad_id.sum())
    out = out.loc[~bad_id].copy()
    out["astronaut_id"] = out["astronaut_id"].astype(str).str.strip()

    # 2) timestamps
    ts = _parse_timestamps(out["timestamp"])
    bad_ts = ts.isna()
    report.invalid_timestamp_rows = int(bad_ts.sum())
    out = out.loc[~bad_ts].copy()
    out["timestamp"] = ts.loc[~bad_ts]

    # 3) duplicates (same astronaut + timestamp)
    dup = out.duplicated(subset=["astronaut_id", "timestamp"], keep=cfg["duplicate_keep"])
    report.duplicate_rows_removed = int(dup.sum())
    out = out.loc[~dup].copy()

    # 4) numeric coercion + range checks
    numeric_cols = [c for c in REQUIRED_COLUMNS[2:] + OPTIONAL_NUMERIC if c in out.columns]
    report.missing_values_original = int(out[numeric_cols].isna().sum().sum())
    oor_by_col: dict[str, int] = {}
    for col in numeric_cols:
        original = out[col]
        num = pd.to_numeric(original, errors="coerce").astype("float64")
        bad_type = num.isna() & original.notna()
        inf = np.isinf(num)
        report.non_numeric_values += int(bad_type.sum() + inf.sum())
        num[inf] = np.nan
        lo, hi = cfg["valid_ranges"][col]
        oor = (num < lo) | (num > hi)
        if int(oor.sum()):
            oor_by_col[col] = int(oor.sum())
        report.out_of_range_values += int(oor.sum())
        num[oor] = np.nan
        out[col] = num
    report.out_of_range_by_column = oor_by_col

    # 5) sort (never mix astronauts)
    out = out.sort_values(["astronaut_id", "timestamp"], kind="mergesort").reset_index(drop=True)

    # 6) mission day (+ drop rows before mission start when it is given)
    out = add_mission_day(out, mission_start)
    if mission_start is not None:
        early = out["mission_day"] < 1
        report.rows_before_mission_start_dropped = int(early.sum())
        out = out.loc[~early].reset_index(drop=True)

    # 7) causal, time-limited forward fill within astronaut
    out["was_imputed"] = False
    for col in numeric_cols:
        hours = (cfg["max_ffill_hours_daily_features"] if col in DAILY_COLUMNS
                 else cfg["max_ffill_hours"])
        filled, mask = _causal_ffill(out, col, pd.Timedelta(hours=hours))
        out[col] = filled
        report.imputed_values += int(mask.sum())
        out["was_imputed"] = out["was_imputed"] | mask

    # 8) drop rows still missing a required value
    if cfg["drop_unrecoverable"]:
        still_missing = out[list(REQUIRED_COLUMNS[2:])].isna().any(axis=1)
        report.unrecoverable_rows_dropped = int(still_missing.sum())
        out = out.loc[~still_missing].reset_index(drop=True)

    report.rows_out = len(out)
    return out, report


def check_daily_consistency(df: pd.DataFrame, columns: tuple[str, ...] = ("sleep_hours", "sleep_quality")) -> pd.DataFrame:
    """Return (astronaut, mission_day, column) groups whose 'daily' value changes within a day."""
    problems = []
    for col in columns:
        if col not in df.columns:
            continue
        n = df.groupby(["astronaut_id", "mission_day"])[col].nunique(dropna=True)
        bad = n[n > 1].reset_index()
        bad["column"] = col
        problems.append(bad[["astronaut_id", "mission_day", "column"]])
    if not problems:
        return pd.DataFrame(columns=["astronaut_id", "mission_day", "column"])
    return pd.concat(problems, ignore_index=True)
