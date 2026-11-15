"""Demo sensors for the suit and the camera, on the same timestamps as the Digital Twin data.

The scenario CSVs (AI 1) contain only wearable readings. For the live demo the replay script adds:
  * suit telemetry every hour, from Mariam's `generate_suit_data` (seeded, so every run is identical);
  * one camera check per day (exercise session at 10:00 UTC), carried forward until the next one.
    The simulated camera sees what a tired body shows: when the last 24 h had less sleep and lower HRV
    than the astronaut's first 14 days, fatigue goes up and movement / posture get worse.
In the real system the camera values come from Mariam's `extract_vision_features(video)`
(MediaPipe Pose); see team_sources/ai3_cv_fusion_mariam for her video pipeline and overlay video.
"""
from __future__ import annotations

import hashlib
import random
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().with_name("mariam_cv_fusion")))
from suit_simulator import generate_suit_data  # noqa: E402  (Mariam, AI 3)

SESSION_HOUR = 10
CALIBRATION_DAYS = 14


def _seed(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def _clamp(x: float, hi: float = 1.0) -> float:
    return max(0.0, min(hi, x))


def _camera(astronaut_id: str, ts: str, sleep_def: float, hrv_drop: float) -> dict:
    r = random.Random(_seed("vision", astronaut_id, ts[:10]))
    fatigue = _clamp(0.15 + 0.55 * sleep_def + 0.35 * hrv_drop + r.gauss(0, 0.03), 0.95)
    return {
        "fatigue_indicator": round(fatigue, 3),
        "movement_quality": round(_clamp(0.88 - 0.35 * fatigue + r.gauss(0, 0.02)), 3),
        "posture_score": round(_clamp(0.86 - 0.20 * fatigue + r.gauss(0, 0.02)), 3),
    }


def enrich(rows: list[dict]) -> list[dict]:
    """Fill empty `suit` / `vision` blocks of replay rows in place. Rows must be sorted by time."""
    by_astro: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_astro[r["astronaut_id"]].append(r)

    for aid, items in by_astro.items():
        calib = [r["wearable"] for r in items if (r.get("mission_day") or 0) <= CALIBRATION_DAYS]
        base_sleep = median([w["sleep_hours"] for w in calib if w.get("sleep_hours")] or [7.0])
        base_hrv = median([w["hrv"] for w in calib if w.get("hrv")] or [60.0])
        window: list[dict] = []
        current = None
        for r in items:
            w = r["wearable"]
            window = (window + [w])[-24:]
            if not any(v is not None for v in (r.get("suit") or {}).values()):
                r["suit"] = generate_suit_data(mode="normal", seed=_seed("suit", aid, r["timestamp"][:13]))
            if int(r["timestamp"][11:13]) == SESSION_HOUR:
                sleep = [x["sleep_hours"] for x in window if x.get("sleep_hours") is not None]
                hrv = [x["hrv"] for x in window if x.get("hrv") is not None]
                sleep_def = _clamp((base_sleep - sum(sleep) / len(sleep)) / base_sleep / 0.4) if sleep else 0.0
                hrv_drop = _clamp((base_hrv - sum(hrv) / len(hrv)) / base_hrv / 0.4) if hrv else 0.0
                current = _camera(aid, r["timestamp"], sleep_def, hrv_drop)
            if current and not any(v is not None for v in (r.get("vision") or {}).values()):
                r["vision"] = dict(current)
    return rows
