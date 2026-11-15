"""Astronaut profiles, JSON serialization and the public ``get_baseline`` function.

Profile schema v1.0.0 (extends the agreed contract; agreed keys are NOT renamed):

    {
      "astronaut_id": "AST-001", "name": "Ahmed",
      "baseline": {"hr": [low, high], "hrv": [low, high], "spo2": [low, high],
                   "sleep_hours": center, "temp": [low, high], "activity": center},   # agreed shape
      "recovery_score": 78,                       # see recovery_score() - engineering assumption
      "baseline_detail": {feature: {"center", "low", "high", "robust_sigma", "interval_method",
                                    "n_samples", "unit", "status", ...}},               # PROPOSED extension
      "calibration": {...}, "schema_version": "1.0.0", "synthetic": true, "data_label": "..."
    }
"""
from __future__ import annotations

import copy
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

import pandas as pd

from .baseline import BASELINE_FEATURES, build_baselines, load_config
from .data_cleaning import clean_wearable_data, CleaningReport
from .data_generator import MISSION_START, SEED, generate_dataset, get_astronaut_specs
from .deviation import add_deviation_columns
from .feature_engineering import DEFAULT_FE_CONFIG, engineer_features
from .online import compute_online_reference

SCHEMA_VERSION = "1.1.0"
DATA_LABEL = ("SYNTHETIC DATA - fictional astronaut. Baseline is a monitoring reference, "
              "not a medical reference interval or diagnosis.")
AGREED_INTERVAL_FEATURES = ("hr", "hrv", "spo2", "temp")
AGREED_SCALAR_FEATURES = ("sleep_hours", "activity")
PROFILE_DIR_ENV = "ASTROGUARDIAN_PROFILE_DIR"


class UnknownAstronautError(KeyError):
    """Raised by get_baseline for an astronaut ID that has no profile (never substituted)."""

    def __str__(self) -> str:  # KeyError would otherwise show a repr with extra quotes
        return str(self.args[0]) if self.args else "unknown astronaut"


def _r(x: Optional[float], nd: int = 3) -> Optional[float]:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return None
    return round(float(x), nd)


def recovery_score(features: Mapping[str, Mapping]) -> Optional[int]:
    """Engineering-assumption recovery indicator (0-100) from CALIBRATION medians:

        100 * (0.4*sleep_quality + 0.3*min(sleep_hours/8, 1) + 0.3*clip((hrv-20)/60, 0, 1))

    Not a validated measure.  Returns None if any input center is unavailable.
    """
    try:
        sq, sh, hrv = (features[k]["center"] for k in ("sleep_quality", "sleep_hours", "hrv"))
    except KeyError:
        return None
    if sq is None or sh is None or hrv is None:
        return None
    score = 0.4 * min(max(sq, 0), 1) + 0.3 * min(sh / 8.0, 1) + 0.3 * min(max((hrv - 20) / 60, 0), 1)
    return int(round(100 * score))


def build_profile(astronaut_id: str, name: str, baseline_result: Mapping,
                  online_reference: Optional[Mapping] = None) -> dict:
    """Assemble the JSON-serializable profile dict from a baseline result."""
    feats = baseline_result["features"]
    agreed: dict[str, Any] = {}
    for f in ("hr", "hrv", "spo2"):
        agreed[f] = _interval_pair(feats[f])
    agreed["sleep_hours"] = _r(feats["sleep_hours"]["center"])
    agreed["temp"] = _interval_pair(feats["temp"])
    agreed["activity"] = _r(feats["activity"]["center"])
    detail = {}
    for f in BASELINE_FEATURES:
        d = feats[f]
        detail[f] = {"center": _r(d["center"]), "low": _r(d["low"]), "high": _r(d["high"]),
                     "robust_sigma": _r(d["robust_sigma"], 4), "interval_method": d["interval_method"],
                     "n_samples": d["n_samples"], "min_samples_required": d["min_samples_required"],
                     "unit": d["unit"], "status": d["status"]}
    return {"astronaut_id": astronaut_id, "name": name, "baseline": agreed,
            "recovery_score": recovery_score(feats), "baseline_detail": detail,
            "calibration": dict(baseline_result["calibration"]),
            **({"online_reference": dict(online_reference)} if online_reference else {}),
            "schema_version": SCHEMA_VERSION, "synthetic": True, "data_label": DATA_LABEL}


def _interval_pair(d: Mapping) -> Optional[list]:
    if d["low"] is None or d["high"] is None:
        return None
    return [_r(d["low"]), _r(d["high"])]


@dataclass
class PipelineResult:
    raw: pd.DataFrame
    clean: pd.DataFrame
    features: pd.DataFrame          # includes *_pct_dev columns
    baselines: dict
    profiles: dict
    cleaning_report: CleaningReport
    config: dict


def run_pipeline(seed: int = SEED, n_days: int = 60, config: Optional[Mapping] = None,
                 raw: Optional[pd.DataFrame] = None) -> PipelineResult:
    """generate -> clean -> features -> baselines -> profiles -> deviation columns."""
    cfg = config if config is not None else load_config()
    specs = get_astronaut_specs(seed)
    raw_df = raw if raw is not None else generate_dataset(seed=seed, n_days=n_days, specs=specs)
    days = cfg["baseline"]["calibration_days"]
    clean, report = clean_wearable_data(raw_df, cfg["cleaning"], mission_start=MISSION_START)
    feats = engineer_features(clean, cfg["feature_engineering"], calibration_days=days)
    baselines = build_baselines(feats, cfg)
    names = {s.astronaut_id: s.name for s in specs}
    fe_cfg = {**DEFAULT_FE_CONFIG, **cfg["feature_engineering"]}
    refs = compute_online_reference(feats, fe_cfg, days, MISSION_START)
    profiles = {aid: build_profile(aid, names.get(aid, aid), b, refs.get(aid))
                for aid, b in baselines.items()}
    feats = add_deviation_columns(feats, profiles, days)
    return PipelineResult(raw_df, clean, feats, baselines, profiles, report, dict(cfg))


def profile_to_json(profile: Mapping, indent: int = 2) -> str:
    """Strict JSON (NaN/Infinity are rejected)."""
    return json.dumps(profile, indent=indent, allow_nan=False, ensure_ascii=False)


def save_profiles(profiles: Mapping[str, Mapping], out_dir: str | Path) -> list[Path]:
    """Write one ``<id>.json`` per astronaut plus ``all_profiles.json``."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for aid, p in profiles.items():
        path = out / f"{aid}.json"
        path.write_text(profile_to_json(p) + "\n", encoding="utf-8", newline="\n")
        paths.append(path)
    allp = out / "all_profiles.json"
    allp.write_text(profile_to_json(dict(profiles)) + "\n", encoding="utf-8", newline="\n")
    return paths + [allp]


_CACHE: dict[str, dict] = {}


def clear_profile_cache() -> None:
    _CACHE.clear()


def default_profile_dir() -> Path:
    env = os.environ.get(PROFILE_DIR_ENV)
    return Path(env) if env else Path(__file__).resolve().parents[2] / "outputs" / "profiles"


def _load_profiles() -> dict[str, dict]:
    directory = default_profile_dir()
    key = str(directory)
    if key not in _CACHE:
        allp = directory / "all_profiles.json"
        if allp.exists():
            with open(allp, encoding="utf-8") as fh:
                _CACHE[key] = json.load(fh)
        else:  # no saved profiles: rebuild deterministically (seed 42) in memory
            _CACHE[key] = run_pipeline().profiles
    return _CACHE[key]


def get_baseline(astronaut_id: str) -> dict:
    """Return the agreed astronaut profile and personal baseline."""
    if not isinstance(astronaut_id, str):
        raise TypeError(f"astronaut_id must be a str, got {type(astronaut_id).__name__}")
    profiles = _load_profiles()
    if astronaut_id not in profiles:
        raise UnknownAstronautError(
            f"Unknown astronaut_id {astronaut_id!r}. Known IDs: {sorted(profiles)}")
    return copy.deepcopy(profiles[astronaut_id])
