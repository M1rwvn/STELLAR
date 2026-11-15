"""STUB for AI 2 (Menna) - Risk Prediction.

A transparent rule-based early-warning score (NEWS-style): every metric adds
points when it moves away from the personal baseline in the harmful
direction. It produces the agreed output and the expected demo behaviour
(Ethan = Normal, Emily = Attention, Ryan = Emergency) until the trained
model (Random Forest / XGBoost + Isolation Forest, .joblib) is delivered.

Replace with the real module by dropping `ai_modules/risk.py`.
"""

LEVELS = [(75, "Emergency"), (50, "High Risk"), (25, "Attention"), (0, "Normal")]
# +1: higher is worse, -1: lower is worse (personal wearable metrics only)
HARMFUL_SIGN = {"hr": 1, "hrv": -1, "spo2": -1, "resp_rate": 1, "temp": 1,
                "sleep_hours": -1, "sleep_quality": -1, "activity": -1}

RECOMMENDATIONS = {
    "sleep_hours": "Increase recovery period and reduce training load today",
    "sleep_quality": "Improve sleep conditions (light, noise, schedule) and re-check tomorrow",
    "hr": "Schedule rest and monitor heart rate every hour",
    "hrv": "Reduce workload; low HRV indicates stress or poor recovery",
    "resp_rate": "Re-measure breathing rate at rest and check cabin air quality",
    "spo2": "Check oxygen supply and suit seal; start continuous SpO2 monitoring",
    "temp": "Check for fever or infection and notify the flight surgeon",
    "activity": "Follow the exercise countermeasure plan to protect muscle and bone",
    "fatigue_risk": "Avoid EVA and high-risk tasks today; plan extra rest",
    "fatigue_indicator": "Avoid EVA and high-risk tasks today; plan extra rest",
    "co2_pct": "Check CO2 scrubbers / life support immediately",
    "o2_pct": "Check O2 supply / life support immediately",
    "cabin_pressure_kpa": "Check cabin and suit pressure immediately",
    "suit_temp_c": "Check suit thermal control",
}


def _num(v: dict, key: str, default: float = 0.0) -> float:
    value = v.get(key)
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def level_for(score: float) -> str:
    for threshold, name in LEVELS:
        if score >= threshold:
            return name
    return "Normal"


def _contributions(v: dict) -> dict[str, tuple[float, float]]:
    """feature -> (risk points, change_pct shown to the user)."""
    d = lambda k: _num(v, f"{k}_dev_pct")  # noqa: E731
    spo2, temp = _num(v, "spo2", 97), _num(v, "temp", 36.7)
    co2, o2 = _num(v, "co2_pct", 0.04), _num(v, "o2_pct", 20.9)
    pressure, suit_temp = _num(v, "cabin_pressure_kpa", 101.3), _num(v, "suit_temp_c", 22)
    fatigue = _num(v, "fatigue_risk")

    # Tolerances absorb normal daily rhythm in hourly data (HR is higher at noon than
    # the daily median; activity is near zero at night), calibrated on AI 1's demo data.
    return {
        "hr": (max(0, d("hr") - 8) * 0.9, d("hr")),
        "hrv": (max(0, -d("hrv") - 12) * 0.6, d("hrv")),
        "spo2": (max(0, 96 - spo2) * 8, d("spo2")),
        "temp": (max(0, temp - 37.2) * 30, round(temp - 36.7, 2)),
        "sleep_hours": (max(0, -d("sleep_hours") - 8) * 1.1, d("sleep_hours")),
        "sleep_quality": (max(0, -d("sleep_quality") - 15) * 0.3, d("sleep_quality")),
        "resp_rate": (max(0, d("resp_rate") - 15) * 0.5, d("resp_rate")),
        # one hourly activity value is weak evidence (sleeping astronauts don't move): capped
        "activity": (min(4.0, max(0, -d("activity") - 30) * 0.1), d("activity")),
        "fatigue_risk": (max(0, fatigue - 0.45) * 30, round(fatigue * 100, 1)),
        "co2_pct": (max(0, co2 - 0.5) * 60, round((co2 - 0.04) / 0.04 * 100, 1)),
        "o2_pct": (max(0, 19.5 - o2) * 20, round((o2 - 20.9) / 20.9 * 100, 1)),
        "cabin_pressure_kpa": (max(0, abs(pressure - 101.3) - 5) * 4,
                               round((pressure - 101.3) / 101.3 * 100, 1)),
        "suit_temp_c": (max(0, abs(suit_temp - 22) - 5) * 3, round((suit_temp - 22) / 22 * 100, 1)),
    }


def predict_risk(vector: dict) -> dict:
    """{risk_score 0-100, level, top_factors[3], recommendation}. Never raises on missing keys."""
    contrib = _contributions(vector or {})
    score = round(min(100.0, sum(points for points, _ in contrib.values())))
    level = level_for(score)

    # Rank by risk points; ties (e.g. all zero when Normal) by how far a personal metric
    # moved in its HARMFUL direction, so "activity +50% at noon" or suit-sensor noise is
    # never shown as a reason
    def harmful_drift(feature: str, pct: float) -> float:
        return max(0.0, HARMFUL_SIGN[feature] * pct) if feature in HARMFUL_SIGN else -1.0

    ranked = sorted(contrib.items(), reverse=True,
                    key=lambda kv: (kv[1][0], harmful_drift(kv[0], kv[1][1])))
    top = [{"feature": f, "change_pct": round(pct, 1)} for f, (_, pct) in ranked[:3]]

    if level == "Normal":
        recommendation = "All metrics within personal baseline. Keep current routine"
    else:
        recommendation = RECOMMENDATIONS.get(ranked[0][0], "Monitor closely")
        if level == "Emergency":
            recommendation = "EMERGENCY: contact the Ground Control flight surgeon now. " + recommendation

    return {"risk_score": score, "level": level, "top_factors": top,
            "recommendation": recommendation}
