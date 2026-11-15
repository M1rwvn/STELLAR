"""Deviation of a reading from a personal baseline.

    pct_deviation = (value - baseline_center) / |baseline_center| * 100

Sign convention: POSITIVE = above baseline, NEGATIVE = below baseline.

``compute_deviation`` returns the flat contract shape ``{metric: pct}`` (e.g.
``{"hr": 14.4, "sleep_hours": -30.0}``).  ``compute_deviation_detailed`` returns the
extra information downstream components may need (center, interval, absolute and
scaled deviation, skipped metrics + reasons).  Neither function produces a risk score.

Excluded from percentages: ``temp`` (degC is an interval scale, see PCT_EXCLUDED_REASONS);
its absolute (degC) and scaled deviation are still available in the detailed result.
A metric is also skipped when its baseline center is 0 / missing, or its value is missing/invalid.
"""
from __future__ import annotations

import logging
import math
from numbers import Real
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

from .baseline import PCT_EXCLUDED_REASONS

logger = logging.getLogger(__name__)

SUPPORTED_METRICS = ("hr", "hrv", "spo2", "resp_rate", "temp", "sleep_hours",
                     "sleep_quality", "activity", "stress_score", "exercise_score")
_META_KEYS = {"astronaut_id", "timestamp", "wearable", "suit", "vision"}
SIGN_CONVENTION = "positive = above baseline center, negative = below baseline center"
_ZERO_EPS = 1e-12


def _as_number(v: Any) -> Optional[float]:
    """Finite real number or None (bools, strings, NaN, inf are invalid)."""
    if isinstance(v, (bool, np.bool_)) or not isinstance(v, (Real, np.number)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _metrics_from_reading(reading: Mapping) -> dict:
    if not isinstance(reading, Mapping):
        raise TypeError(f"reading must be a dict, got {type(reading).__name__}")
    nested = reading.get("wearable")
    src = nested if isinstance(nested, Mapping) else reading
    metrics = {k: v for k, v in src.items() if k not in _META_KEYS}
    if not metrics:
        raise ValueError("reading contains no metrics (expected e.g. {'hr': 72, 'sleep_hours': 4.9})")
    return metrics


def _resolve_baseline(baseline: Mapping) -> dict[str, dict]:
    """Map metric -> {center, interval, sigma, source} from a profile or a bare baseline dict."""
    if not isinstance(baseline, Mapping):
        raise TypeError(f"baseline must be a dict, got {type(baseline).__name__}")
    detail = baseline.get("baseline_detail")
    inner = baseline.get("baseline") if isinstance(baseline.get("baseline"), Mapping) else (
        baseline if "baseline_detail" not in baseline else {})
    resolved: dict[str, dict] = {}
    if isinstance(detail, Mapping):
        for m, d in detail.items():
            if isinstance(d, Mapping):
                low, high = _as_number(d.get("low")), _as_number(d.get("high"))
                resolved[m] = {"center": _as_number(d.get("center")),
                               "interval": [low, high] if low is not None and high is not None else None,
                               "sigma": _as_number(d.get("robust_sigma")),
                               "source": "baseline_detail.center"}
    for m, v in inner.items():
        if m in resolved:
            continue
        if isinstance(v, (list, tuple)) and len(v) == 2 and all(_as_number(x) is not None for x in v):
            lo, hi = float(v[0]), float(v[1])
            resolved[m] = {"center": (lo + hi) / 2, "interval": [lo, hi], "sigma": None,
                           "source": "interval_midpoint"}
        elif _as_number(v) is not None:
            resolved[m] = {"center": float(v), "interval": None, "sigma": None, "source": "scalar"}
    if not resolved:
        raise ValueError("baseline contains no usable metrics")
    return resolved


def compute_deviation_detailed(reading: dict, baseline: dict) -> dict:
    """Full deviation report. See module docstring."""
    metrics = _metrics_from_reading(reading)
    base = _resolve_baseline(baseline)
    rid, bid = reading.get("astronaut_id"), baseline.get("astronaut_id")
    if rid is not None and bid is not None and rid != bid:
        raise ValueError(f"reading astronaut_id {rid!r} does not match baseline astronaut_id {bid!r}")

    out: dict[str, Any] = {"astronaut_id": bid if bid is not None else rid,
                           "timestamp": reading.get("timestamp"),
                           "sign_convention": SIGN_CONVENTION,
                           "deviations_pct": {}, "metrics": {}, "skipped": {}}
    for m, raw in metrics.items():
        if m not in SUPPORTED_METRICS:
            out["skipped"][m] = "unsupported_metric"
            continue
        value = _as_number(raw)
        if value is None:
            out["skipped"][m] = "invalid_or_missing_value"
            continue
        b = base.get(m)
        if b is None or b["center"] is None:
            out["skipped"][m] = "no_baseline_for_metric"
            continue
        center = b["center"]
        info = {"value": value, "center": center, "center_source": b["source"],
                "interval": b["interval"], "abs_deviation": round(value - center, 4),
                "pct_deviation": None, "position": "no_interval", "scaled_deviation": None}
        if b["interval"]:
            lo, hi = b["interval"]
            info["position"] = "below_interval" if value < lo else "above_interval" if value > hi else "within_interval"
        if b["sigma"]:
            info["scaled_deviation"] = round((value - center) / b["sigma"], 4)
        if m in PCT_EXCLUDED_REASONS:
            out["skipped"][m] = "pct_excluded: " + PCT_EXCLUDED_REASONS[m]
        elif abs(center) < _ZERO_EPS:
            out["skipped"][m] = "zero_baseline"
        else:
            pct = round((value - center) / abs(center) * 100.0, 2)
            info["pct_deviation"] = pct
            out["deviations_pct"][m] = pct
        out["metrics"][m] = info
    return out


def compute_deviation(reading: dict, baseline: dict) -> dict:
    """Calculate percentage deviations for supported metrics.

    Returns ``{metric: pct}`` (positive = above baseline).  Metrics that cannot be computed
    (missing/invalid value, zero or missing baseline, temp) are omitted and logged at WARNING level;
    use :func:`compute_deviation_detailed` to see why.
    """
    detailed = compute_deviation_detailed(reading, baseline)
    for m, reason in detailed["skipped"].items():
        if not reason.startswith("pct_excluded"):
            logger.warning("compute_deviation skipped %r: %s", m, reason)
    return dict(detailed["deviations_pct"])


def add_deviation_columns(df: pd.DataFrame, profiles: Mapping[str, Mapping], calibration_days: int = 14) -> pd.DataFrame:
    """Add ``<metric>_pct_dev`` (and ``temp_delta_c``) columns.  Same formula as compute_deviation.

    Rows inside the calibration period get NaN: the baseline is only final after calibration ends,
    so using it earlier would use future information.
    """
    out = df.copy()
    post = out["mission_day"] > calibration_days
    for m in SUPPORTED_METRICS:
        col = "temp_delta_c" if m == "temp" else f"{m}_pct_dev"
        out[col] = np.nan
    for aid, idx in out.groupby("astronaut_id").groups.items():
        detail = profiles[aid]["baseline_detail"]
        for m in SUPPORTED_METRICS:
            c = detail.get(m, {}).get("center")
            if c is None or m not in out.columns:
                continue
            rows = idx[post.loc[idx].to_numpy()]
            if m == "temp":
                out.loc[rows, "temp_delta_c"] = (out.loc[rows, m] - c).round(4)
            elif abs(c) >= _ZERO_EPS:
                out.loc[rows, f"{m}_pct_dev"] = ((out.loc[rows, m] - c) / abs(c) * 100.0).round(2)
    return out
