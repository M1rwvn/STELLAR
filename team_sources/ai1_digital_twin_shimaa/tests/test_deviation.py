import copy
import inspect
import typing
import json
import logging

import numpy as np
import pytest

from astroguardian_digital_twin import compute_deviation, compute_deviation_detailed, get_baseline


def make_baseline(**centers):
    centers = centers or {"hr": 60.0, "sleep_hours": 7.0, "spo2": 97.0, "temp": 36.7}
    return {"astronaut_id": "AST-T", "baseline": {},
            "baseline_detail": {m: {"center": c, "low": c - 1, "high": c + 1, "robust_sigma": 1.0}
                                for m, c in centers.items()}}


def test_signs_and_values():
    dev = compute_deviation({"hr": 66, "sleep_hours": 4.9, "spo2": 97}, make_baseline())
    assert dev["hr"] == pytest.approx(10.0)             # above baseline -> positive
    assert dev["sleep_hours"] == pytest.approx(-30.0)   # below baseline -> negative
    assert dev["spo2"] == 0.0


def test_compat_call_from_team_contract_on_real_baseline():
    baseline = get_baseline("AST-001")
    dev = compute_deviation({"hr": 72, "sleep_hours": 4.9}, baseline)
    assert set(dev) == {"hr", "sleep_hours"}
    c = baseline["baseline_detail"]
    assert dev["hr"] == pytest.approx((72 - c["hr"]["center"]) / c["hr"]["center"] * 100, abs=0.01)
    assert dev["sleep_hours"] == pytest.approx((4.9 - c["sleep_hours"]["center"]) / c["sleep_hours"]["center"] * 100, abs=0.01)
    assert dev["hr"] > 0 > dev["sleep_hours"]


def test_zero_baseline_is_skipped_not_divided():
    b = make_baseline(hr=0.0, sleep_hours=7.0)
    assert compute_deviation({"hr": 70, "sleep_hours": 7}, b) == {"sleep_hours": 0.0}
    det = compute_deviation_detailed({"hr": 70}, b)
    assert det["skipped"]["hr"] == "zero_baseline" and det["deviations_pct"] == {}


def test_missing_feature_is_not_invented():
    assert compute_deviation({"hr": 66}, make_baseline()) == {"hr": 10.0}
    det = compute_deviation_detailed({"hr": 66, "hrv": 50}, make_baseline())
    assert det["skipped"]["hrv"] == "no_baseline_for_metric"


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), "72", True, [1]])
def test_invalid_values_skipped_explicitly(bad, caplog):
    with caplog.at_level(logging.WARNING):
        dev = compute_deviation({"hr": bad, "sleep_hours": 7.7}, make_baseline())
    assert "hr" not in dev and dev["sleep_hours"] == pytest.approx(10.0)
    assert compute_deviation_detailed({"hr": bad, "sleep_hours": 7}, make_baseline())["skipped"]["hr"] == "invalid_or_missing_value"
    assert "skipped 'hr'" in caplog.text


def test_temp_excluded_from_percent_but_available_in_detail():
    b = make_baseline(temp=36.7, hr=60.0)
    assert "temp" not in compute_deviation({"temp": 37.8, "hr": 60}, b)
    det = compute_deviation_detailed({"temp": 37.8}, b)
    assert det["skipped"]["temp"].startswith("pct_excluded")
    assert det["metrics"]["temp"]["abs_deviation"] == pytest.approx(1.1)
    assert det["metrics"]["temp"]["pct_deviation"] is None
    assert det["metrics"]["temp"]["position"] == "above_interval"
    assert det["metrics"]["temp"]["scaled_deviation"] == pytest.approx(1.1)


def test_detail_fields_and_positions():
    b = make_baseline(hr=60.0)
    d = compute_deviation_detailed({"hr": 60.5}, b)["metrics"]["hr"]
    assert d["position"] == "within_interval" and d["interval"] == [59.0, 61.0] and d["center"] == 60.0
    assert compute_deviation_detailed({"hr": 50}, b)["metrics"]["hr"]["position"] == "below_interval"


def test_bad_input_types_raise():
    with pytest.raises(TypeError):
        compute_deviation("hr=70", make_baseline())
    with pytest.raises(TypeError):
        compute_deviation({"hr": 70}, "baseline")
    with pytest.raises(ValueError, match="no metrics"):
        compute_deviation({}, make_baseline())
    with pytest.raises(ValueError, match="no usable metrics"):
        compute_deviation({"hr": 70}, {"baseline": {}})


def test_astronaut_mismatch_never_silently_accepted():
    with pytest.raises(ValueError, match="does not match"):
        compute_deviation({"astronaut_id": "AST-002", "hr": 70}, get_baseline("AST-001"))
    assert compute_deviation({"astronaut_id": "AST-001", "hr": 70}, get_baseline("AST-001"))


def test_accepts_nested_wearable_payload():
    payload = {"astronaut_id": "AST-T", "timestamp": "2026-10-05T10:00:00Z",
               "wearable": {"hr": 66, "sleep_hours": 7}, "suit": {"o2_pct": 20.9}}
    assert compute_deviation(payload, make_baseline()) == {"hr": 10.0, "sleep_hours": 0.0}


def test_bare_agreed_baseline_dict_falls_back_to_interval_midpoint():
    bare = {"hr": [60, 65], "sleep_hours": 7.0}
    det = compute_deviation_detailed({"hr": 62.5, "sleep_hours": 7.7}, bare)
    assert det["metrics"]["hr"]["center_source"] == "interval_midpoint"
    assert det["deviations_pct"] == {"hr": 0.0, "sleep_hours": 10.0}


def test_inputs_not_mutated_and_output_json_serializable():
    reading, base = {"hr": 66, "temp": 37.0, "x": 1}, make_baseline()
    r0, b0 = copy.deepcopy(reading), copy.deepcopy(base)
    det = compute_deviation_detailed(reading, base)
    assert reading == r0 and base == b0
    json.dumps(det, allow_nan=False)
    assert det["skipped"]["x"] == "unsupported_metric"


def test_numpy_numbers_accepted():
    assert compute_deviation({"hr": np.float64(66), "sleep_hours": np.int64(7)}, make_baseline())["hr"] == 10.0


def test_signature_compatibility():
    sig = inspect.signature(compute_deviation)
    assert list(sig.parameters) == ["reading", "baseline"]
    hints = typing.get_type_hints(compute_deviation)
    assert hints["reading"] is dict and hints["baseline"] is dict and hints["return"] is dict


def test_vectorised_columns_equal_function(pipeline):
    f = pipeline.features
    prof = pipeline.profiles
    rows = f[(f["mission_day"] > 14)].sample(40, random_state=0)
    for _, r in rows.iterrows():
        dev = compute_deviation({m: r[m] for m in ("hr", "hrv", "spo2", "sleep_hours", "activity")},
                                prof[r["astronaut_id"]])
        for m, v in dev.items():
            assert r[f"{m}_pct_dev"] == pytest.approx(v, abs=0.011)
    assert f.loc[f["mission_day"] <= 14, "hr_pct_dev"].isna().all()     # no baseline yet -> NaN
