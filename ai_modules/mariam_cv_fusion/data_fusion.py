"""Data Fusion Layer: Wearable + Suit + Vision -> Unified Health Vector (Core v1.0).

Main function for the Backend (signature must not change):
    build_health_vector(wearable, suit, vision, baseline) -> dict
The returned dict ALWAYS has exactly the keys of CORE_COLUMNS, in order.
"""

import math

from schema import (CORE_COLUMNS, WEARABLE_KEYS, SUIT_KEYS, VISION_KEYS,
                    WEARABLE_DEFAULTS, SUIT_DEFAULTS, VISION_DEFAULT)

# Last known real value per key (used when a value is missing later).
_LAST_KNOWN = {}


def reset_cache():
    """Forget last-known values (useful in tests)."""
    _LAST_KNOWN.clear()


def _is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def baseline_value(baseline, key):
    """Baseline can be a number or a [low, high] range (-> midpoint). None if unknown."""
    try:
        b = (baseline or {}).get(key)
        if _is_number(b):
            return float(b)
        if isinstance(b, (list, tuple)) and len(b) == 2 and all(_is_number(i) for i in b):
            return (b[0] + b[1]) / 2.0
    except Exception:
        pass
    return None


def compute_deviation(reading: dict, baseline: dict) -> dict:
    """PLACEHOLDER for Shimaa's function (same signature).

    Signed % deviation per wearable metric: (value - baseline) / baseline * 100.
    Negative = below baseline (e.g. sleep_hours -30). None if it can't be computed.
    """
    out = {}
    for key in WEARABLE_KEYS:
        value = (reading or {}).get(key)
        base = baseline_value(baseline, key)
        if _is_number(value) and base not in (None, 0):
            out[key] = round((value - base) / abs(base) * 100, 2)
        else:
            out[key] = None
    return out


def fatigue_rule(v: dict) -> str:
    """Transparent rule-based fatigue risk: "Low" / "Medium" / "High".

    Points: very short sleep +2 (short +1), low activity +1, HR 15%+ above
    baseline +1, poor movement quality +1, high vision fatigue +1.
    High if score >= 3, or if (sleep < 5h AND activity < 0.3), even when
    HR and vision look normal. Medium if score >= 2.
    """
    def num(k, default):
        x = v.get(k)
        return x if _is_number(x) else default

    sleep = num("sleep_hours", 7.0)
    activity = num("activity", 0.5)
    hr_dev = num("hr_dev_pct", 0.0)

    score = 0
    if sleep < 5:
        score += 2
    elif sleep < 6.5:
        score += 1
    if activity < 0.3:
        score += 1
    if hr_dev >= 15:
        score += 1
    if num("movement_quality", 0.5) < 0.4:
        score += 1
    if num("fatigue_indicator", 0.5) >= 0.6:
        score += 1

    if score >= 3 or (sleep < 5 and activity < 0.3):
        return "High"
    if score >= 2:
        return "Medium"
    return "Low"


def _resolve(source, key, baseline, default, estimated, prefix, use_baseline=True):
    """Pick the real value, else last known, else baseline, else default."""
    value = source.get(key) if isinstance(source, dict) else None
    if _is_number(value):
        _LAST_KNOWN[key] = float(value)
        return value
    estimated.append(f"{prefix}.{key}")
    if key in _LAST_KNOWN:
        return _LAST_KNOWN[key]
    if use_baseline:
        b = baseline_value(baseline, key)
        if b is not None:
            return b
    return default


def build_health_vector_with_meta(wearable, suit, vision, baseline):
    """Same as build_health_vector but also returns meta = estimated fields info."""
    estimated = []
    try:
        w = {k: _resolve(wearable, k, baseline, WEARABLE_DEFAULTS[k], estimated, "wearable")
             for k in WEARABLE_KEYS}
        s = {k: _resolve(suit, k, baseline, SUIT_DEFAULTS[k], estimated, "suit",
                         use_baseline=False) for k in SUIT_KEYS}
        vis = {k: _resolve(vision, k, baseline, VISION_DEFAULT, estimated, "vision",
                           use_baseline=False) for k in VISION_KEYS}
        dev = compute_deviation(w, baseline)

        vector = {}
        vector.update(w)
        vector.update(s)
        vector.update(vis)
        for k in WEARABLE_KEYS:
            vector[f"{k}_dev_pct"] = dev.get(k)
        vector["fatigue_risk"] = fatigue_rule(vector)
    except Exception as exc:  # the Backend must never crash because of us
        estimated.append(f"error:{exc}")
        vector = {c: None for c in CORE_COLUMNS}
        vector.update(WEARABLE_DEFAULTS)
        vector.update(SUIT_DEFAULTS)
        vector.update({k: VISION_DEFAULT for k in VISION_KEYS})
        vector["fatigue_risk"] = "Low"
    vector = {c: vector.get(c) for c in CORE_COLUMNS}  # force order
    return vector, {"estimated_fields": estimated, "estimated_count": len(estimated)}


def build_health_vector(wearable: dict, suit: dict, vision: dict, baseline: dict) -> dict:
    """Backend entry point: returns the Core vector (CORE_COLUMNS order)."""
    return build_health_vector_with_meta(wearable, suit, vision, baseline)[0]
