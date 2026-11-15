"""Feature engineering (causal: every value uses only current and past rows).

Formulas (see docs/data_dictionary.md):

* ``<f>_roll24h_mean`` / ``<f>_roll168h_mean``: mean of the astronaut's own values in the
  time window (t - W, t]  (current + past only), W = 24 h or 168 h, needs >= min_periods rows.
* ``hr_roll24h_std``: standard deviation over the same 24 h window.
* ``sleep_debt_7d`` (hours) = sum over the last 7 mission days (including today) of
  max(0, sleep_need - sleep_hours_of_that_day).  sleep_need is an ENGINEERING ASSUMPTION
  (default 8.0 h) - not a medical requirement.
* ``sleep_hours_roll7d_mean``: mean of the daily sleep values over the last 7 days.
* ``stress_score`` (0-100, internal indicator, NOT a clinical stress measure):
      z_hr  = (hr_6h  - ref_mean_hr ) / ref_std_hr
      z_hrv = (ref_mean_hrv - hrv_6h) / ref_std_hrv
      stress = clip(25 + 12.5 * (z_hr + z_hrv) / 2, 0, 100)
  hr_6h / hrv_6h are trailing 6 h means.  The reference mean/std are EXPANDING statistics
  computed from calibration-period rows only (mission day <= calibration_days) that are
  already available at time t, then frozen when calibration ends.  So the score never uses
  future data and never uses post-calibration (possibly deteriorated) data as reference.
  The first ~14 hours of the mission have NaN (warm-up).
* ``exercise_score``: pass-through of the daily training-plan adherence value.
* ``is_calibration``: mission_day <= calibration_days.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

from .data_cleaning import (CANONICAL_COLUMNS, HOURLY_COLUMNS, REQUIRED_COLUMNS,
                            add_mission_day, validate_columns)

DEFAULT_FE_CONFIG: dict[str, Any] = {
    "rolling_short_hours": 24,
    "rolling_long_hours": 168,
    "rolling_min_periods": 6,
    "stress_window_hours": 6,
    "stress_min_calibration_obs": 12,
    "stress_baseline_level": 25.0,
    "stress_gain": 12.5,
    "sleep_need_hours": 8.0,
    "sleep_debt_window_days": 7,
    "stress_min_scale_fraction": 0.01,
}


def _causal_z(values: np.ndarray, is_cal: np.ndarray, min_obs: int, min_frac: float) -> np.ndarray:
    """z-score of ``values`` against expanding calibration-only mean/std (frozen after calibration)."""
    s = pd.Series(np.where(is_cal, values, np.nan))
    mean = s.expanding(min_periods=min_obs).mean().to_numpy()
    std = s.expanding(min_periods=min_obs).std().to_numpy()
    scale = np.maximum(std, min_frac * np.abs(mean))   # floor avoids division by ~0; NaN propagates
    return (values - mean) / scale


def engineer_features(df: pd.DataFrame, config: Optional[Mapping[str, Any]] = None,
                      calibration_days: int = 14, mission_start: Any = None) -> pd.DataFrame:
    """Add causal features to a cleaned table and return a model-ready dataset."""
    cfg = copy.deepcopy(DEFAULT_FE_CONFIG)
    if config:
        cfg.update(config)
    validate_columns(df)
    work = df.sort_values(["astronaut_id", "timestamp"], kind="mergesort").reset_index(drop=True)
    if "mission_day" not in work.columns:
        work = add_mission_day(work, mission_start)
    if "exercise_score" not in work.columns:
        work["exercise_score"] = np.nan

    short, long_, mp = cfg["rolling_short_hours"], cfg["rolling_long_hours"], cfg["rolling_min_periods"]
    sw = cfg["stress_window_hours"]
    parts = []
    for _, g in work.groupby("astronaut_id", sort=True):
        g = g.copy()
        idx = g.set_index("timestamp")
        for f in HOURLY_COLUMNS:
            g[f"{f}_roll{short}h_mean"] = idx[f].rolling(f"{short}h", min_periods=mp).mean().to_numpy()
            g[f"{f}_roll{long_}h_mean"] = idx[f].rolling(f"{long_}h", min_periods=mp).mean().to_numpy()
        g[f"hr_roll{short}h_std"] = idx["hr"].rolling(f"{short}h", min_periods=mp).std().to_numpy()

        # sleep debt on daily values (first row of each day = value known at the day's start)
        daily = g.groupby("mission_day")["sleep_hours"].first()
        full = daily.reindex(range(int(daily.index.min()), int(daily.index.max()) + 1))
        deficit = (cfg["sleep_need_hours"] - full).clip(lower=0)
        win = cfg["sleep_debt_window_days"]
        g["sleep_debt_7d"] = g["mission_day"].map(deficit.rolling(win, min_periods=1).sum())
        g["sleep_hours_roll7d_mean"] = g["mission_day"].map(full.rolling(win, min_periods=1).mean())

        # stress indicator with calibration-only, causal reference
        is_cal = (g["mission_day"] <= calibration_days).to_numpy()
        hr6 = idx["hr"].rolling(f"{sw}h", min_periods=3).mean().to_numpy()
        hrv6 = idx["hrv"].rolling(f"{sw}h", min_periods=3).mean().to_numpy()
        mo, mf = cfg["stress_min_calibration_obs"], cfg["stress_min_scale_fraction"]
        z = 0.5 * (_causal_z(hr6, is_cal, mo, mf) - _causal_z(hrv6, is_cal, mo, mf))
        g["stress_score"] = np.clip(cfg["stress_baseline_level"] + cfg["stress_gain"] * z, 0, 100)
        parts.append(g)

    out = pd.concat(parts, ignore_index=True)
    out["is_calibration"] = out["mission_day"] <= calibration_days
    first = [c for c in CANONICAL_COLUMNS if c in out.columns]
    rest = [c for c in out.columns if c not in first]
    return out[first + rest]
