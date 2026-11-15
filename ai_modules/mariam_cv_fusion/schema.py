"""Fixed column schema for the Unified Health Vector (Core v1.0).

The ORDER and NAMES here must never change: Menna's model trains on them.
"""

WEARABLE_KEYS = ["hr", "hrv", "spo2", "resp_rate", "temp",
                 "sleep_hours", "sleep_quality", "activity"]
SUIT_KEYS = ["cabin_pressure_kpa", "suit_temp_c", "o2_pct", "co2_pct"]
VISION_KEYS = ["posture_score", "movement_quality", "fatigue_indicator"]
DEVIATION_KEYS = [f"{k}_dev_pct" for k in WEARABLE_KEYS]

CORE_COLUMNS = (WEARABLE_KEYS + SUIT_KEYS + VISION_KEYS
                + DEVIATION_KEYS + ["fatigue_risk"])
FINAL_COLUMNS = CORE_COLUMNS  # alias used by the Backend / tests
CORE_VERSION = "1.0"

# Safe defaults used only if a value is missing AND there is no baseline.
WEARABLE_DEFAULTS = {"hr": 65.0, "hrv": 55.0, "spo2": 98.0, "resp_rate": 15.0,
                     "temp": 36.7, "sleep_hours": 7.0, "sleep_quality": 0.7,
                     "activity": 0.5}
SUIT_DEFAULTS = {"cabin_pressure_kpa": 101.3, "suit_temp_c": 22.0,
                 "o2_pct": 20.9, "co2_pct": 0.04}
VISION_DEFAULT = 0.5  # neutral, NOT 0.0 (0.0 would mean "worst posture")
