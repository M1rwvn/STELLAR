"""STUB for AI 3 (Mariam) - Data Fusion -> Unified Health Vector.

Follows Mariam's brief:
  * merge wearable + suit + vision
  * add `<metric>_dev_pct` from compute_deviation (AI 1)
  * add `fatigue_risk` (HR normal + 4h sleep + low movement -> high fatigue)
  * missing values: fill from the baseline / nominal value and report them
  * columns always have the same names and order (the model trains on them)

History features (rolling means, sleep debt, stress_score, `<m>_pct_dev`) are NOT made here:
the pipeline adds them from AI 1's `online_features`, with the training formulas.

Replace with the real module by dropping `ai_modules/fusion.py`.
"""

WEARABLE_FIELDS = ["hr", "hrv", "spo2", "resp_rate", "temp",
                   "sleep_hours", "sleep_quality", "activity"]
SUIT_FIELDS = ["cabin_pressure_kpa", "suit_temp_c", "o2_pct", "co2_pct"]
VISION_FIELDS = ["posture_score", "movement_quality", "fatigue_indicator"]
DEV_FIELDS = [f"{k}_dev_pct" for k in WEARABLE_FIELDS]

# Fixed column order of the Unified Health Vector
FEATURE_COLUMNS = WEARABLE_FIELDS + SUIT_FIELDS + VISION_FIELDS + DEV_FIELDS + ["fatigue_risk"]

WEARABLE_FALLBACK = {"hr": 65.0, "hrv": 60.0, "spo2": 97.5, "resp_rate": 15.0, "temp": 36.7,
                     "sleep_hours": 7.0, "sleep_quality": 0.78, "activity": 0.5}
SUIT_NOMINAL = {"cabin_pressure_kpa": 101.3, "suit_temp_c": 22.0, "o2_pct": 20.9, "co2_pct": 0.04}
VISION_NEUTRAL = {"posture_score": 0.8, "movement_quality": 0.75, "fatigue_indicator": 0.3}


def _center(value) -> float:
    if isinstance(value, (list, tuple)):
        return (float(value[0]) + float(value[1])) / 2
    return float(value)


def _normal_value(profile: dict, key: str) -> float | None:
    """The astronaut's normal value for one metric.

    Prefers AI 1's `baseline_detail[key].center` (median over the calibration days),
    which also covers metrics that are not in the short `baseline` dict
    (resp_rate, sleep_quality, ...); falls back to the `baseline` range midpoint.
    """
    detail = (profile.get("baseline_detail") or {}).get(key) or {}
    if detail.get("center") is not None:
        return float(detail["center"])
    base = profile.get("baseline", profile)
    return _center(base[key]) if base.get(key) is not None else None


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def fatigue_rule(v: dict) -> float:
    """0-1 fatigue risk combining sleep debt, camera fatigue and movement quality."""
    sleep_debt = _clamp(-v.get("sleep_hours_dev_pct", 0.0) / 50)
    low_activity = _clamp(-v.get("activity_dev_pct", 0.0) / 60)
    camera = v.get("fatigue_indicator", 0.3)
    poor_movement = 1 - v.get("movement_quality", 0.75)
    return round(_clamp(0.4 * sleep_debt + 0.25 * camera + 0.2 * poor_movement
                        + 0.15 * low_activity), 3)


def build_health_vector(wearable: dict, suit: dict, vision: dict, baseline: dict) -> dict:
    from app.ai import compute_deviation  # AI 1 (real module if installed)

    # Keep the full profile: AI 1 uses its baseline_detail for precise centers
    profile = baseline
    wearable, suit, vision = wearable or {}, suit or {}, vision or {}
    imputed: list[str] = []
    v: dict = {}

    for k in WEARABLE_FIELDS:
        if wearable.get(k) is not None:
            v[k] = float(wearable[k])
        else:
            normal = _normal_value(profile, k)
            v[k] = normal if normal is not None else WEARABLE_FALLBACK[k]
            imputed.append(k)
    for k in SUIT_FIELDS:
        if suit.get(k) is not None:
            v[k] = float(suit[k])
        else:
            v[k] = SUIT_NOMINAL[k]
            imputed.append(k)
    for k in VISION_FIELDS:
        if vision.get(k) is not None:
            v[k] = float(vision[k])
        else:
            v[k] = VISION_NEUTRAL[k]
            imputed.append(k)

    dev = compute_deviation({k: v[k] for k in WEARABLE_FIELDS}, profile)
    for k in WEARABLE_FIELDS:
        v[f"{k}_dev_pct"] = dev.get(k, 0.0)

    v["fatigue_risk"] = fatigue_rule(v)

    vector = {k: v[k] for k in FEATURE_COLUMNS}
    vector["imputed"] = imputed
    return vector
