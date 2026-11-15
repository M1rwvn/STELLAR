"""Personal baseline model (robust statistics, calibration days only).

For each astronaut and feature we use ONLY mission days 1..calibration_days (default 14):

* central value  = median (robust to outliers);
* reference interval = one of (configurable per feature):
    - "median_mad" : median +/- k * 1.4826 * MAD       (default since v1.1, k = 2; robust sigma =
                     1.4826 * MAD; covers >= 91 % of every astronaut's calibration readings)
    - "iqr"        : [Q1, Q3]                         (v1.0 default; robust sigma = IQR / 1.349;
                     covers only ~50 % by definition, so half of normal readings look "out of range")
    - "mean_std"   : mean +/- k * sample std           (sigma = std; center stays the median)
* hourly features use all hourly calibration samples; DAILY features (sleep_hours,
  sleep_quality, exercise_score) use ONE value per mission day so that repeated hourly
  copies do not inflate the sample size.

The interval is a PERSONAL reference for one synthetic astronaut, not a medical threshold.
Statuses: "ok", "constant" (zero spread -> low == high == center), "insufficient_data"
(too few samples -> center/low/high are None), "no_data" (column missing or all NaN).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

from .data_cleaning import DEFAULT_CLEANING_CONFIG, DEFAULT_VALID_RANGES, FEATURE_UNITS
from .feature_engineering import DEFAULT_FE_CONFIG

INTERVAL_METHODS = ("iqr", "median_mad", "mean_std")
HOURLY_BASELINE_FEATURES = ["hr", "hrv", "spo2", "resp_rate", "temp", "activity", "stress_score"]
DAILY_BASELINE_FEATURES = ["sleep_hours", "sleep_quality", "exercise_score"]
BASELINE_FEATURES = HOURLY_BASELINE_FEATURES + DAILY_BASELINE_FEATURES

PCT_EXCLUDED_REASONS = {
    "temp": ("degC is an interval scale (0 degC is arbitrary), so a percentage of the baseline "
             "has no physical meaning. Use abs_deviation (degC) / scaled_deviation instead."),
}

DEFAULT_CONFIG: dict[str, Any] = {
    "baseline": {
        "calibration_days": 14,
        "central_statistic": "median",
        "default_interval_method": "median_mad",
        "interval_method_overrides": {},
        "dispersion_k": 2.0,
        "min_hourly_samples": 168,
        "min_daily_samples": 7,
        "constant_tolerance": 1e-9,
    },
    "cleaning": DEFAULT_CLEANING_CONFIG,
    "feature_engineering": DEFAULT_FE_CONFIG,
    "deviation": {"pct_excluded_features": sorted(PCT_EXCLUDED_REASONS)},
}


def default_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "baseline_config.json"


def _deep_merge(base: dict, extra: Mapping) -> dict:
    for k, v in extra.items():
        if isinstance(v, Mapping) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = copy.deepcopy(v)
    return base


def validate_config(cfg: Mapping[str, Any]) -> None:
    b = cfg["baseline"]
    if not isinstance(b["calibration_days"], int) or b["calibration_days"] < 1:
        raise ValueError("baseline.calibration_days must be an integer >= 1")
    if b["central_statistic"] != "median":
        raise ValueError("baseline.central_statistic: only 'median' is supported")
    methods = [b["default_interval_method"], *b["interval_method_overrides"].values()]
    for m in methods:
        if m not in INTERVAL_METHODS:
            raise ValueError(f"Unknown interval method {m!r}; choose from {INTERVAL_METHODS}")
    if b["dispersion_k"] <= 0:
        raise ValueError("baseline.dispersion_k must be > 0")


def load_config(path: Optional[str | Path] = None) -> dict:
    """Defaults, overridden by a JSON file (``config/baseline_config.json`` if present)."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    p = Path(path) if path else default_config_path()
    if path and not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")
    if p.exists():
        with open(p, encoding="utf-8") as fh:
            _deep_merge(cfg, json.load(fh))
    validate_config(cfg)
    return cfg


def _interval(values: np.ndarray, method: str, k: float) -> tuple[float, float, float]:
    """Return (low, high, robust_sigma)."""
    if method == "iqr":
        q1, q3 = np.quantile(values, [0.25, 0.75])
        return float(q1), float(q3), float((q3 - q1) / 1.349)
    if method == "median_mad":
        med = np.median(values)
        mad = 1.4826 * np.median(np.abs(values - med))
        return float(med - k * mad), float(med + k * mad), float(mad)
    mean, sd = float(np.mean(values)), float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
    return mean - k * sd, mean + k * sd, sd


def compute_feature_baseline(values, feature: str, kind: str, config: Optional[Mapping] = None) -> dict:
    """Baseline for one feature from calibration values (NaN ignored)."""
    cfg = (config or load_config())["baseline"]
    arr = np.asarray(pd.Series(values, dtype="float64").dropna(), dtype=float)
    method = cfg["interval_method_overrides"].get(feature, cfg["default_interval_method"])
    min_n = cfg["min_hourly_samples"] if kind == "hourly" else cfg["min_daily_samples"]
    res = {"center": None, "low": None, "high": None, "robust_sigma": None,
           "interval_method": method, "n_samples": int(arr.size), "min_samples_required": int(min_n),
           "unit": FEATURE_UNITS.get(feature), "status": "ok"}
    if arr.size == 0:
        res["status"] = "no_data"
        return res
    if arr.size < min_n:
        res["status"] = "insufficient_data"
        return res
    center = float(np.median(arr))
    res["center"] = center
    if float(np.ptp(arr)) <= cfg["constant_tolerance"]:
        res.update(low=center, high=center, status="constant")
        return res
    low, high, sigma = _interval(arr, method, cfg["dispersion_k"])
    # median +/- k*sigma can leave the scale (e.g. a stress score below 0): keep it plausible
    lo_ok, hi_ok = DEFAULT_VALID_RANGES.get(feature, (-np.inf, np.inf))
    low, high = max(low, lo_ok), min(high, hi_ok)
    res.update(low=low, high=high, robust_sigma=sigma if sigma > cfg["constant_tolerance"] else None)
    return res


def _iso(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_astronaut_baseline(df: pd.DataFrame, config: Optional[Mapping] = None) -> dict:
    """Baseline for ONE astronaut. Rows after the calibration period are ignored."""
    cfg = config or load_config()
    days = cfg["baseline"]["calibration_days"]
    if "mission_day" not in df.columns:
        raise ValueError("DataFrame needs a 'mission_day' column (run the cleaning step first)")
    ids = df["astronaut_id"].unique()
    if len(ids) != 1:
        raise ValueError(f"compute_astronaut_baseline expects exactly one astronaut, got {list(ids)}")
    cal = df[(df["mission_day"] >= 1) & (df["mission_day"] <= days)].sort_values("timestamp")
    features = {}
    for f in HOURLY_BASELINE_FEATURES:
        vals = cal[f] if f in cal.columns else pd.Series(dtype=float)
        features[f] = compute_feature_baseline(vals, f, "hourly", cfg)
    for f in DAILY_BASELINE_FEATURES:
        vals = cal.groupby("mission_day")[f].first() if f in cal.columns else pd.Series(dtype=float)
        features[f] = compute_feature_baseline(vals, f, "daily", cfg)
    n_days = int(cal["mission_day"].nunique()) if len(cal) else 0
    calibration = {
        "calibration_days": days,
        "start": _iso(cal["timestamp"].min()) if len(cal) else None,
        "end": _iso(cal["timestamp"].max()) if len(cal) else None,
        "n_rows": int(len(cal)), "n_days_present": n_days,
        "complete": bool(n_days >= days),
        "note": "Only mission days 1..calibration_days were used; later data was ignored.",
    }
    return {"astronaut_id": str(ids[0]), "features": features, "calibration": calibration}


def build_baselines(df: pd.DataFrame, config: Optional[Mapping] = None) -> dict[str, dict]:
    """Per-astronaut baselines for every astronaut in ``df`` (each fitted independently)."""
    cfg = config or load_config()
    return {str(aid): compute_astronaut_baseline(g, cfg) for aid, g in df.groupby("astronaut_id", sort=True)}
