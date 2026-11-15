"""Tests for the Core fusion. Run: python test_fusion.py (no pytest needed)."""

import json
import random

from data_fusion import (build_health_vector, build_health_vector_with_meta,
                         compute_deviation, fatigue_rule, reset_cache)
from make_payload import build_payload
from schema import CORE_COLUMNS
from suit_simulator import generate_suit_data
from vision_features import extract_vision_features, features_from_reps

BASELINE = {"hr": [60, 65], "hrv": [55, 70], "spo2": [96, 99], "resp_rate": 15,
            "temp": [36.5, 36.9], "sleep_hours": 8.0, "sleep_quality": 0.8, "activity": 0.55}
WEARABLE = {"hr": 72, "hrv": 48, "spo2": 97, "resp_rate": 16, "temp": 36.7,
            "sleep_hours": 6.5, "sleep_quality": 0.72, "activity": 0.40}
SUIT = {"cabin_pressure_kpa": 101.3, "suit_temp_c": 22.1, "o2_pct": 20.9, "co2_pct": 0.04}
VISION = {"posture_score": 0.8, "movement_quality": 0.7, "fatigue_indicator": 0.3}


def check(vector):
    assert list(vector.keys()) == CORE_COLUMNS, "column order/names changed!"


def test_normal():
    reset_cache()
    v = build_health_vector(WEARABLE, SUIT, VISION, BASELINE)
    check(v)
    assert v["fatigue_risk"] == "Low"


def test_missing_wearable():
    reset_cache()
    v = build_health_vector({}, SUIT, VISION, BASELINE)
    check(v)
    assert v["hr"] == 62.5          # midpoint of [60, 65]
    _, meta = build_health_vector_with_meta({}, SUIT, VISION, BASELINE)
    assert "wearable.hr" in meta["estimated_fields"]


def test_missing_suit_and_vision():
    reset_cache()
    check(build_health_vector(WEARABLE, {}, VISION, BASELINE))
    reset_cache()  # no last-known value -> neutral default
    v = build_health_vector(WEARABLE, SUIT, {}, BASELINE)
    check(v)
    assert v["posture_score"] == 0.5  # neutral, not 0.0


def test_all_none():
    reset_cache()
    check(build_health_vector(None, None, None, None))
    check(build_health_vector(None, None, None, {}))


def test_last_known_value():
    reset_cache()
    build_health_vector(WEARABLE, SUIT, VISION, BASELINE)
    v = build_health_vector({"hr": None}, SUIT, VISION, BASELINE)
    assert v["hr"] == 72  # last known real value, not baseline


def test_extreme_values():
    reset_cache()
    v = build_health_vector({"hr": 220, "sleep_hours": 0, "activity": 0},
                            {"cabin_pressure_kpa": 1, "suit_temp_c": 100, "o2_pct": 1, "co2_pct": 99},
                            {"posture_score": 0, "movement_quality": 0, "fatigue_indicator": 1}, BASELINE)
    check(v)
    assert v["fatigue_risk"] == "High"
    check(build_health_vector({"hr": float("nan"), "hrv": "abc"}, SUIT, VISION, BASELINE))


def test_bad_suit_mode():
    reset_cache()
    suit = generate_suit_data(mode="bad", seed=1)
    assert suit["co2_pct"] >= 1.0 and suit["o2_pct"] < 19
    check(build_health_vector(WEARABLE, suit, VISION, BASELINE))
    assert generate_suit_data(seed=3) == generate_suit_data(seed=3)


def test_fatigue_example():
    reset_cache()
    v = build_health_vector({"hr": 80, "sleep_hours": 4, "activity": 0.1}, SUIT,
                            {"movement_quality": 0.2}, BASELINE)
    check(v)
    assert v["fatigue_risk"] == "High"
    # normal HR + 4h sleep + low activity is still High (vision normal)
    assert fatigue_rule({"hr_dev_pct": 0, "sleep_hours": 4, "activity": 0.1,
                         "movement_quality": 0.9, "fatigue_indicator": 0.1}) == "High"
    # one weak signal alone is NOT High
    assert fatigue_rule({"sleep_hours": 4, "activity": 0.6}) != "High"


def test_deviation_sign_and_range():
    d = compute_deviation({"sleep_hours": 5.6, "hr": 72}, BASELINE)
    assert d["sleep_hours"] == -30.0
    assert d["hr"] == 15.2          # 72 vs midpoint 62.5
    assert d["hrv"] is None


def test_payload_contract():
    reset_cache()
    payload, vector, _ = build_payload(WEARABLE, SUIT, VISION, BASELINE)
    assert list(payload.keys()) == ["astronaut_id", "timestamp", "wearable", "suit", "vision"]
    assert len(payload["wearable"]) == 8 and len(payload["suit"]) == 4 and len(payload["vision"]) == 3
    assert payload["astronaut_id"] == "AST-001"
    json.dumps(payload)
    check(vector)


def test_vision_logic():
    # synthetic reps: later reps slower and shallower -> high fatigue
    tired = [{"depth": 90, "duration": 2.0, "back_dev": 20},
             {"depth": 88, "duration": 2.1, "back_dev": 20},
             {"depth": 60, "duration": 3.4, "back_dev": 30},
             {"depth": 55, "duration": 3.6, "back_dev": 30}]
    fresh = [{"depth": 90, "duration": 2.0, "back_dev": 20}] * 4
    t, f = features_from_reps(tired), features_from_reps(fresh)
    assert t["fatigue_indicator"] > 0.7 and f["fatigue_indicator"] == 0.0
    assert f["movement_quality"] > t["movement_quality"]
    for x in (t, f):
        assert all(0 <= x[k] <= 1 for k in ("posture_score", "movement_quality", "fatigue_indicator"))
    assert features_from_reps(fresh[:1])["fatigue_indicator"] == 0.5   # < 2 reps -> neutral


def test_vision_never_crashes():
    r = extract_vision_features("does_not_exist.mp4")
    assert r["posture_score"] == r["movement_quality"] == r["fatigue_indicator"] == 0.5


def test_random_inputs_keep_columns():
    reset_cache()
    rng = random.Random(0)
    junk = [None, "x", -5, 1e9, [], {}, float("inf"), True]
    for _ in range(200):
        pick = lambda keys: {k: rng.choice(junk + [rng.random() * 100]) for k in keys if rng.random() < .6}
        check(build_health_vector(pick(WEARABLE), pick(SUIT), pick(VISION), rng.choice([BASELINE, None, {}])))


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"PASS  {name}")
    print(f"\nAll {len(tests)} tests passed.")
