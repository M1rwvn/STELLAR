"""Online (runtime) features: the SAME history features as the training data, for one new reading.

Why: the training table (``engineer_features``) has rolling means, sleep debt and the stress
indicator, which need history.  The backend receives one reading at a time, so without this
module a model trained on ``features_all_astronauts.csv`` would get different inputs at
runtime than in training (train/serve skew).

``online_features(history, profile)`` takes the astronaut's readings of the last 7 days (the
backend reads them from its database; the newest reading is the one being scored) and
returns the training columns for that newest reading, computed with the same formulas and
windows as ``feature_engineering.engineer_features``:

* ``<f>_roll24h_mean`` / ``<f>_roll168h_mean`` / ``hr_roll24h_std``: rows in (t - W, t]
* ``sleep_debt_7d``, ``sleep_hours_roll7d_mean``: daily values of the last 7 mission days
* ``stress_score``: uses the calibration reference frozen in ``profile["online_reference"]``
  (identical to the training value after calibration; ``None`` during calibration days)
* ``<m>_pct_dev`` / ``temp_delta_c``: deviation from the personal baseline (``None`` during
  calibration, as in training)

A value that cannot be computed (too little history) is ``None`` - never invented.
Equality with the training table is checked by ``tests/test_online.py``.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional

import numpy as np
import pandas as pd

from .data_cleaning import HOURLY_COLUMNS, WEARABLE_FIELDS
from .deviation import SUPPORTED_METRICS, _ZERO_EPS

ONLINE_SCHEMA_VERSION = "1.1.0"


# --------------------------------------------------------------------------- reference
def compute_online_reference(features: pd.DataFrame, fe_config: Mapping[str, Any],
                             calibration_days: int, mission_start: str) -> dict[str, dict]:
    """Per-astronaut constants that ``online_features`` needs, frozen at the end of calibration.

    The stress reference is the mean/std of the trailing 6 h HR/HRV means over the calibration
    rows - exactly the values ``engineer_features`` uses for every post-calibration row.
    """
    sw = fe_config["stress_window_hours"]
    min_obs = fe_config["stress_min_calibration_obs"]
    min_frac = fe_config["stress_min_scale_fraction"]
    refs: dict[str, dict] = {}
    for aid, g in features.groupby("astronaut_id", sort=True):
        g = g.sort_values("timestamp")
        idx = g.set_index("timestamp")
        cal = (g["mission_day"] <= calibration_days).to_numpy()
        stress: dict[str, Optional[float]] = {}
        for f in ("hr", "hrv"):
            six = idx[f].rolling(f"{sw}h", min_periods=3).mean().to_numpy()[cal]
            six = six[~np.isnan(six)]
            if six.size < min_obs:
                stress.update({f"{f}6_mean": None, f"{f}6_scale": None})
                continue
            mean = float(six.mean())
            std = float(np.std(six, ddof=1))
            stress.update({f"{f}6_mean": mean, f"{f}6_scale": max(std, min_frac * abs(mean))})
        refs[str(aid)] = {
            "schema_version": ONLINE_SCHEMA_VERSION,
            "mission_start": mission_start,
            "calibration_days": calibration_days,
            "stress": stress,
            "feature_config": {k: fe_config[k] for k in (
                "rolling_short_hours", "rolling_long_hours", "rolling_min_periods",
                "stress_window_hours", "stress_baseline_level", "stress_gain",
                "sleep_need_hours", "sleep_debt_window_days")},
        }
    return refs


# --------------------------------------------------------------------------- helpers
def _ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _flatten(row: Mapping) -> dict:
    """Accept flat rows or contract payloads ({"wearable": {...}})."""
    wearable = row.get("wearable")
    src = wearable if isinstance(wearable, Mapping) else row
    out = {k: _num(src.get(k)) for k in WEARABLE_FIELDS}
    out["timestamp"] = _ts(row["timestamp"])
    return out


def _window(rows: list[dict], key: str, now: datetime, hours: int) -> list[float]:
    start = now - timedelta(hours=hours)
    return [r[key] for r in rows if start < r["timestamp"] <= now and r[key] is not None]


def _mean(values: list[float], min_periods: int) -> Optional[float]:
    return float(np.mean(values)) if len(values) >= min_periods else None


def _std(values: list[float], min_periods: int) -> Optional[float]:
    return float(np.std(values, ddof=1)) if len(values) >= max(min_periods, 2) else None


# --------------------------------------------------------------------------- main API
def online_features(history: Iterable[Mapping], profile: Mapping) -> dict[str, Optional[float]]:
    """Training-identical history features for the NEWEST reading in ``history``.

    ``history``: the astronaut's readings (flat rows or POST /health-data payloads), including
    the newest one; order does not matter; at least the last 7 days for complete features.
    ``profile``: from ``get_baseline`` (needs ``online_reference``, schema >= 1.1.0).
    """
    ref = profile.get("online_reference")
    if not ref:
        raise ValueError("profile has no 'online_reference' (rebuild profiles with v1.1.0+)")
    cfg = ref["feature_config"]
    rows = sorted((_flatten(r) for r in history), key=lambda r: r["timestamp"])
    if not rows:
        raise ValueError("history is empty")
    now = rows[-1]["timestamp"]
    start = _ts(ref["mission_start"])
    day_of = lambda t: int((t - start) // timedelta(days=1)) + 1  # noqa: E731
    mission_day = day_of(now)
    calibrating = mission_day <= ref["calibration_days"]

    short, long_, mp = cfg["rolling_short_hours"], cfg["rolling_long_hours"], cfg["rolling_min_periods"]
    out: dict[str, Optional[float]] = {}
    for f in HOURLY_COLUMNS:
        out[f"{f}_roll{short}h_mean"] = _mean(_window(rows, f, now, short), mp)
        out[f"{f}_roll{long_}h_mean"] = _mean(_window(rows, f, now, long_), mp)
    out[f"hr_roll{short}h_std"] = _std(_window(rows, "hr", now, short), mp)

    # daily sleep values: first reading of each mission day, last N days incl. today
    win = cfg["sleep_debt_window_days"]
    daily: dict[int, float] = {}
    for r in rows:
        d = day_of(r["timestamp"])
        if mission_day - win < d <= mission_day and d not in daily and r["sleep_hours"] is not None:
            daily[d] = r["sleep_hours"]
    if daily:
        out["sleep_debt_7d"] = float(sum(max(0.0, cfg["sleep_need_hours"] - v) for v in daily.values()))
        out["sleep_hours_roll7d_mean"] = float(np.mean(list(daily.values())))
    else:
        out["sleep_debt_7d"] = out["sleep_hours_roll7d_mean"] = None

    # stress indicator (frozen calibration reference -> identical to training after calibration)
    s = ref["stress"]
    hr6 = _mean(_window(rows, "hr", now, cfg["stress_window_hours"]), 3)
    hrv6 = _mean(_window(rows, "hrv", now, cfg["stress_window_hours"]), 3)
    if calibrating or None in (hr6, hrv6, s.get("hr6_mean"), s.get("hrv6_mean")):
        out["stress_score"] = None
    else:
        z = 0.5 * ((hr6 - s["hr6_mean"]) / s["hr6_scale"] - (hrv6 - s["hrv6_mean"]) / s["hrv6_scale"])
        out["stress_score"] = float(min(100.0, max(0.0, cfg["stress_baseline_level"] + cfg["stress_gain"] * z)))
    out["exercise_score"] = None  # daily training-plan adherence is not in the wearable payload

    # deviation columns, as in add_deviation_columns (None during calibration)
    current = dict(rows[-1])
    current["stress_score"] = out["stress_score"]
    current["exercise_score"] = None
    detail = profile.get("baseline_detail") or {}
    for m in SUPPORTED_METRICS:
        col = "temp_delta_c" if m == "temp" else f"{m}_pct_dev"
        c = (detail.get(m) or {}).get("center")
        v = current.get(m)
        if calibrating or c is None or v is None:
            out[col] = None
        elif m == "temp":
            out[col] = round(v - c, 4)
        elif abs(c) >= _ZERO_EPS:
            out[col] = round((v - c) / abs(c) * 100.0, 2)
        else:
            out[col] = None
    out["mission_day"] = mission_day
    return out
