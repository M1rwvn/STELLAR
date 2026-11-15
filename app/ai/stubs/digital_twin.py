"""FALLBACK for AI 1 (Shimaa) - Digital Twin.

The real module is live (ai_modules/digital_twin.py). This stub only answers if
it fails to import (e.g. pandas missing) or raises on a request:
  * baseline = normal range per metric from the calibration days (1-14)
  * deviation_pct = (current - normal) / normal * 100
"""

# Copied from Shimaa's profiles (ai_modules/profiles/all_profiles.json, seed 42), so this
# fallback answers like the real module. Ranges are median +- 2 robust SD; scalars are the median.
_PROFILES: dict[str, dict] = {
    "AST-001": {
        "name": "Ethan Cole",
        "baseline": {"hr": [56.47, 68.33], "hrv": [51.513, 70.787], "spo2": [96.61, 98.39], "sleep_hours": 6.905, "temp": [36.393, 36.987], "activity": 0.527, "resp_rate": [13.017, 15.983], "stress_score": [0.0, 57.157], "exercise_score": [77.84, 84.66], "sleep_quality": 0.782},
        "recovery_score": 78,
    },
    "AST-002": {
        "name": "Emily Carter",
        "baseline": {"hr": [59.377, 72.423], "hrv": [44.848, 70.052], "spo2": [95.914, 98.286], "sleep_hours": 7.24, "temp": [36.245, 37.015], "activity": 0.49, "resp_rate": [13.024, 17.176], "stress_score": [4.789, 46.962], "exercise_score": [74.894, 90.906], "sleep_quality": 0.779},
        "recovery_score": 77,
    },
    "AST-003": {
        "name": "Ryan Mitchell",
        "baseline": {"hr": [61.77, 73.63], "hrv": [46.71, 65.39], "spo2": [96.61, 98.39], "sleep_hours": 6.82, "temp": [36.454, 37.106], "activity": 0.603, "resp_rate": [14.214, 16.586], "stress_score": [2.515, 51.174], "exercise_score": [80.602, 89.498], "sleep_quality": 0.708},
        "recovery_score": 72,
    },
}

_POPULATION_DEFAULT = {
    "hr": [60, 75], "hrv": [45, 70], "spo2": [95, 99], "resp_rate": [12, 18],
    "temp": [36.4, 37.0], "sleep_hours": 7.0, "sleep_quality": 0.75, "activity": 0.5,
    "stress_score": [20, 35], "exercise_score": [65, 85],
}


def _center(value) -> float:
    if isinstance(value, (list, tuple)):
        return (float(value[0]) + float(value[1])) / 2
    return float(value)


def get_baseline(astronaut_id: str) -> dict:
    """Return the Astronaut Profile (the personal baseline)."""
    profile = _PROFILES.get(astronaut_id)
    if profile is None:
        return {"astronaut_id": astronaut_id, "name": astronaut_id,
                "baseline": dict(_POPULATION_DEFAULT), "recovery_score": None}
    return {"astronaut_id": astronaut_id, "name": profile["name"],
            "baseline": dict(profile["baseline"]), "recovery_score": profile["recovery_score"]}


def compute_deviation(reading: dict, baseline: dict) -> dict:
    """% deviation of each metric from the personal normal mean.

    compute_deviation({"hr": 72, "sleep_hours": 4.9}, baseline) -> {"hr": +15.2, "sleep_hours": -30.0}
    Missing / non-numeric values are skipped.
    """
    base = baseline.get("baseline", baseline)
    out = {}
    for key, value in reading.items():
        # temp is skipped like in the real module: a % of degC has no physical meaning
        if key not in base or value is None or key == "temp":
            continue
        try:
            center = _center(base[key])
            out[key] = round((float(value) - center) / center * 100, 1) if center else 0.0
        except (TypeError, ValueError):
            continue
    return out
