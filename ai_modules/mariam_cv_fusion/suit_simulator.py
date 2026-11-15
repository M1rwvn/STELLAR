"""Suit Telemetry Simulator: fake but realistic spacesuit/cabin readings."""

import random


def generate_suit_data(timestamp=None, mode="normal", seed=None):
    """Return {cabin_pressure_kpa, suit_temp_c, o2_pct, co2_pct}.

    mode="normal": values near nominal with small noise.
    mode="bad":    pressure drop, high temp, low O2, high CO2.
    `timestamp` is accepted for API compatibility but not returned
    (the timestamp lives in the JSON payload).
    """
    rng = random.Random(seed)
    if mode == "bad":
        return {
            "cabin_pressure_kpa": round(rng.uniform(85, 95), 2),
            "suit_temp_c": round(rng.uniform(32, 40), 2),
            "o2_pct": round(rng.uniform(16, 18), 2),
            "co2_pct": round(rng.uniform(1.0, 3.0), 3),
        }
    return {
        "cabin_pressure_kpa": round(rng.gauss(101.3, 0.15), 2),
        "suit_temp_c": round(rng.gauss(22.0, 0.25), 2),
        "o2_pct": round(rng.gauss(20.9, 0.04), 2),
        "co2_pct": round(max(0.0, rng.gauss(0.04, 0.005)), 3),
    }


if __name__ == "__main__":
    print(generate_suit_data(seed=1))
    print(generate_suit_data(mode="bad", seed=1))
