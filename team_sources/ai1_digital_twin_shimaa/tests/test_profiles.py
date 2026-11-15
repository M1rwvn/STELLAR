import inspect
import json
import typing

import pytest

from astroguardian_digital_twin import UnknownAstronautError, get_baseline
from astroguardian_digital_twin.profiles import (PROFILE_DIR_ENV, clear_profile_cache, profile_to_json,
                                                 recovery_score, save_profiles)

AGREED = {"hr", "hrv", "spo2", "sleep_hours", "temp", "activity"}


def test_signature_compatibility():
    sig = inspect.signature(get_baseline)
    assert list(sig.parameters) == ["astronaut_id"]
    hints = typing.get_type_hints(get_baseline)
    assert hints["astronaut_id"] is str and hints["return"] is dict


def test_profile_shape_matches_agreed_contract():
    p = get_baseline("AST-001")
    assert p["astronaut_id"] == "AST-001" and p["name"] == "Ahmed"
    assert set(p["baseline"]) == AGREED                         # agreed keys, none renamed or removed
    for k in ("hr", "hrv", "spo2", "temp"):
        low, high = p["baseline"][k]
        assert low <= high
    assert isinstance(p["baseline"]["sleep_hours"], float) and isinstance(p["baseline"]["activity"], float)
    assert isinstance(p["recovery_score"], int) and 0 <= p["recovery_score"] <= 100
    assert p["synthetic"] is True and "SYNTHETIC" in p["data_label"]


def test_center_and_interval_are_distinct_fields():
    d = get_baseline("AST-002")["baseline_detail"]["hr"]
    assert d["low"] < d["center"] < d["high"] and d["interval_method"] == "median_mad" and d["status"] == "ok"
    p = get_baseline("AST-002")
    assert p["baseline"]["sleep_hours"] == p["baseline_detail"]["sleep_hours"]["center"]
    assert p["baseline"]["hr"] == [d["low"], d["high"]]


def test_profiles_are_distinct_per_astronaut():
    hr = {a: get_baseline(a)["baseline"]["hr"] for a in ("AST-001", "AST-002", "AST-003")}
    assert len({tuple(v) for v in hr.values()}) == 3


def test_unknown_astronaut_raises_clear_error():
    for bad in ("AST-999", "ast-001", "", "AST-001 "):
        with pytest.raises(UnknownAstronautError, match="Unknown astronaut_id"):
            get_baseline(bad)
    with pytest.raises(KeyError):                               # subclass of KeyError (backend -> 404)
        get_baseline("nobody")
    with pytest.raises(TypeError):
        get_baseline(1)


def test_returns_copy_not_shared_state():
    p = get_baseline("AST-001")
    p["baseline"]["hr"][0] = -1
    p["name"] = "Hacked"
    again = get_baseline("AST-001")
    assert again["baseline"]["hr"][0] != -1 and again["name"] == "Ahmed"


def test_all_ten_profiles_serialize_to_strict_json(pipeline):
    assert len(pipeline.profiles) == 10
    for aid, p in pipeline.profiles.items():
        text = profile_to_json(p)
        assert json.loads(text) == p                            # lossless round trip, no NaN


def test_profile_does_not_leak_scenario_label(pipeline):
    for p in pipeline.profiles.values():
        assert "scenario" not in json.dumps(p).lower()


def test_save_and_read_from_profile_dir(tmp_path, pipeline, monkeypatch):
    paths = save_profiles(pipeline.profiles, tmp_path)
    assert (tmp_path / "AST-001.json").exists() and (tmp_path / "all_profiles.json").exists() and len(paths) == 11
    custom = json.loads((tmp_path / "all_profiles.json").read_text())
    custom["AST-001"]["name"] = "FromCustomDir"
    (tmp_path / "all_profiles.json").write_text(json.dumps(custom))
    monkeypatch.setenv(PROFILE_DIR_ENV, str(tmp_path))
    clear_profile_cache()
    try:
        assert get_baseline("AST-001")["name"] == "FromCustomDir"
    finally:
        monkeypatch.delenv(PROFILE_DIR_ENV)
        clear_profile_cache()


def test_committed_profiles_match_fresh_pipeline(pipeline):
    from astroguardian_digital_twin.profiles import default_profile_dir
    f = default_profile_dir() / "AST-003.json"
    if f.exists():
        assert json.loads(f.read_text()) == pipeline.profiles["AST-003"]


def test_recovery_score_formula_and_missing_inputs():
    feats = {"sleep_quality": {"center": 0.8}, "sleep_hours": {"center": 8.0}, "hrv": {"center": 80.0}}
    assert recovery_score(feats) == round(100 * (0.4 * 0.8 + 0.3 + 0.3))
    feats["hrv"]["center"] = None
    assert recovery_score(feats) is None and recovery_score({}) is None


def test_endpoint3_profile_fields_available():
    """GET /astronaut-profile/{id} needs astronaut_id, name, baseline (mission_day/status come from the backend)."""
    p = get_baseline("AST-003")
    endpoint = {"astronaut_id": p["astronaut_id"], "name": p["name"], "baseline": p["baseline"]}
    json.dumps(endpoint, allow_nan=False)
    assert set(endpoint["baseline"]) == AGREED
