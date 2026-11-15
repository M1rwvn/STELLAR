"""AI 3 - Computer Vision + Data Fusion (Mariam), plugged into the backend.

Source: Mariam's `astroguardian-cv-fusion` (schema.py, data_fusion.py, suit_simulator.py), copied
unmodified into `ai_modules/mariam_cv_fusion/`. Her video analysis (MediaPipe Pose on a squat video ->
posture_score, movement_quality, fatigue_indicator) runs on the device that has the camera; the backend
receives the three numbers in POST /health-data and only needs her fusion layer.

What this connector adds around her code:
  * her `compute_deviation` is a placeholder (her README says so): it is replaced by AI 1's real one,
    called with the astronaut's full Digital Twin profile;
  * her `baseline_value` expects flat values or [low, high]: she gets the profile's ranges, with AI 1's
    personal medians where they exist;
  * her "last known value" memory is kept per astronaut (one crew member's value never fills another's);
  * `environment_flags`: measured suit / cabin values outside safe limits;
  * `imputed`: her `estimated_fields` without the source prefix ("wearable.spo2" -> "spo2").
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().with_name("mariam_cv_fusion")
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))
import data_fusion as _df  # noqa: E402  (her module; imports her schema.py next to it)
import schema as _schema  # noqa: E402

MODEL_VERSION = _schema.CORE_VERSION
FEATURE_COLUMNS = list(_schema.CORE_COLUMNS)

# Safe cabin / suit ranges (ISS-like, approximate). None = no limit on that side.
LIMITS = {
    "cabin_pressure_kpa": (97.9, 102.7, "Cabin pressure", "kPa"),
    "suit_temp_c": (18.3, 26.7, "Suit temperature", "°C"),
    "o2_pct": (19.5, 23.5, "Oxygen", "%"),
    "co2_pct": (None, 0.53, "CO2", "%"),
}

_lock = threading.Lock()
_last_known: dict[str, dict] = {}


def reset_cache(astronaut_id: str | None = None) -> None:
    """Forget the last-known values of one astronaut (or of everyone)."""
    with _lock:
        if astronaut_id is None:
            _last_known.clear()
        else:
            _last_known.pop(astronaut_id, None)


def _flat_baseline(profile: dict) -> dict:
    base = dict(profile.get("baseline") or {})
    for key, detail in (profile.get("baseline_detail") or {}).items():
        if isinstance(detail, dict) and detail.get("center") is not None:
            base[key] = detail["center"]
    return base


def environment_flags(suit: dict) -> list[dict]:
    flags = []
    for key, (lo, hi, label, unit) in LIMITS.items():
        x = suit.get(key)
        if not isinstance(x, (int, float)) or isinstance(x, bool):
            continue
        if lo is not None and x < lo:
            flags.append({"field": key, "value": x, "limit": lo, "direction": "low",
                          "text": f"{label} is low: {x} {unit} (limit {lo})"})
        elif hi is not None and x > hi:
            flags.append({"field": key, "value": x, "limit": hi, "direction": "high",
                          "text": f"{label} is high: {x} {unit} (limit {hi})"})
    return flags


def build_health_vector(wearable: dict, suit: dict, vision: dict, baseline: dict) -> dict:
    from app.ai import compute_deviation as twin_deviation  # AI 1 (falls back safely)

    profile = baseline or {}
    astronaut_id = str(profile.get("astronaut_id", "unknown"))
    with _lock:
        _df._LAST_KNOWN = _last_known.setdefault(astronaut_id, {})
        placeholder = _df.compute_deviation
        _df.compute_deviation = lambda reading, _flat: twin_deviation(reading, profile)
        try:
            vector, meta = _df.build_health_vector_with_meta(wearable or {}, suit or {}, vision or {},
                                                             _flat_baseline(profile))
        finally:
            _df.compute_deviation = placeholder
    measured_suit = {k: v for k, v in (suit or {}).items() if k in LIMITS}
    vector["environment_flags"] = environment_flags(measured_suit)
    vector["imputed"] = [f.split(".", 1)[1] for f in meta.get("estimated_fields", []) if "." in f]
    return vector
