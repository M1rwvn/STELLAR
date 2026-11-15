"""Synthetic wearable data generator.

*** EVERYTHING GENERATED HERE IS SYNTHETIC (fictional astronauts). ***
Base values, circadian amplitudes, noise levels and scenario effects are
SCENARIO DESIGN VALUES chosen for the hackathon.  They are not medical
reference values and make no claim of clinical realism or validity.

Signal model per hourly feature f:

    value = base_f + circadian_f(hour) + day_offset_f(day) + AR1_noise_f + effect_f * severity(t)

* circadian: sinusoid with a 24 h period (peak hour per feature, see CIRCADIAN)
* day_offset: slow day-to-day variation (normal, one draw per day)
* AR1 noise: hourly noise with autocorrelation PHI (not white noise)
* severity(t) in [0, 1]: scenario ramp (0 during calibration days 1-14 for all scenarios)
* sleep_hours / sleep_quality / exercise_score are DAILY values; the same value is
  repeated on all 24 hourly rows of that mission day (documented simplification:
  the daily summary is treated as available from 00:00 of that day).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from .data_cleaning import DEFAULT_VALID_RANGES

SEED = 42
N_DAYS = 60
MISSION_START = "2026-08-25T00:00:00Z"   # day 1; 2026-10-05 is then mission day 42
PHI = 0.6                                  # AR(1) coefficient of hourly noise

HOURLY_FEATURES = ["hr", "hrv", "spo2", "resp_rate", "temp", "activity"]
DAILY_FEATURES = ["sleep_hours", "sleep_quality", "exercise_score"]

# (amplitude, peak_hour): design values only.
CIRCADIAN = {
    "hr": (3.0, 15), "hrv": (-4.0, 15), "spo2": (0.10, 15), "resp_rate": (0.6, 15),
    "temp": (0.15, 17), "activity": (0.28, 15),
}
# hourly innovation sd and day-offset sd
HOURLY_SD = {"hr": 1.2, "hrv": 3.0, "spo2": 0.35, "resp_rate": 0.5, "temp": 0.07, "activity": 0.06}
DAY_SD = {"hr": 0.8, "hrv": 2.0, "spo2": 0.15, "resp_rate": 0.25, "temp": 0.05, "activity": 0.03}
DAILY_SD = {"sleep_hours": 0.30, "sleep_quality": 0.04, "exercise_score": 3.0}

# Effect added at severity = 1 (design values).
SCENARIO_EFFECTS: dict[str, dict[str, float]] = {
    "normal": {}, "stable": {},
    "attention": {"hr": 8.0, "hrv": -10.0, "spo2": -0.4, "resp_rate": 1.0, "temp": 0.1,
                  "activity": -0.17, "sleep_hours": -1.5, "sleep_quality": -0.18,
                  "exercise_score": -22.0},
    "emergency": {"hr": 28.0, "hrv": -28.0, "spo2": -4.5, "resp_rate": 5.0, "temp": 1.0,
                  "activity": -0.30, "sleep_hours": -2.9, "sleep_quality": -0.35,
                  "exercise_score": -40.0},
    "mild_sleep_drift": {"hr": 3.0, "hrv": -4.0, "activity": -0.07, "sleep_hours": -0.9,
                         "sleep_quality": -0.10},
    "transient_fever": {"hr": 9.0, "hrv": -8.0, "spo2": -0.5, "resp_rate": 2.0, "temp": 0.9,
                        "activity": -0.15},
    "slow_hr_rise": {"hr": 6.0, "hrv": -6.0, "resp_rate": 0.8},
}


@dataclass
class AstronautSpec:
    """Fictional astronaut: identity, scenario label and personal base values."""

    astronaut_id: str
    name: str
    scenario: str
    base: dict = field(default_factory=dict)
    noise_scale: float = 1.0


def severity(scenario: str, t_days: np.ndarray) -> np.ndarray:
    """Scenario severity in [0, 1] at fractional mission time ``t_days`` (day 1 starts at 0)."""
    t = np.asarray(t_days, dtype=float)
    if scenario == "attention":           # Sara: gradual from day 40 (t=39) to day 60
        return np.clip((t - 39.0) / 21.0, 0.0, 1.0)
    if scenario == "emergency":           # Omar: final five days (t >= 55), clear onset
        return np.where(t >= 55.0, 0.35 + 0.65 * np.clip((t - 55.0) / 5.0, 0.0, 1.0), 0.0)
    if scenario == "mild_sleep_drift":
        return 0.5 * np.clip((t - 30.0) / 30.0, 0.0, 1.0)
    if scenario == "transient_fever":     # 3-day bump starting on day 31
        return np.where((t >= 30.0) & (t < 33.0), np.sin(np.pi * (t - 30.0) / 3.0), 0.0)
    if scenario == "slow_hr_rise":
        return 0.6 * np.clip((t - 20.0) / 40.0, 0.0, 1.0)
    return np.zeros_like(t)


_DEMO_BASES = {
    "AST-001": ("Ahmed", "normal", 0.85, dict(hr=62.5, hrv=62.0, spo2=97.5, resp_rate=14.5, temp=36.70,
                sleep_hours=7.0, sleep_quality=0.80, activity=0.55, exercise_score=82.0)),
    "AST-002": ("Sara", "attention", 1.30, dict(hr=66.0, hrv=58.0, spo2=97.2, resp_rate=15.0, temp=36.65,
                sleep_hours=7.0, sleep_quality=0.76, activity=0.50, exercise_score=80.0)),
    "AST-003": ("Omar", "emergency", 1.00, dict(hr=68.0, hrv=55.0, spo2=97.5, resp_rate=15.5, temp=36.80,
                sleep_hours=6.9, sleep_quality=0.72, activity=0.60, exercise_score=85.0)),
}
_EXTRA_NAMES = ["Layla", "Karim", "Nour", "Youssef", "Dina", "Tarek", "Hana"]
_EXTRA_SCENARIOS = ["stable", "mild_sleep_drift", "stable", "transient_fever", "stable",
                    "slow_hr_rise", "stable"]


def get_astronaut_specs(seed: int = SEED) -> list[AstronautSpec]:
    """3 demo astronauts (fixed values) + 7 seeded, varied fictional astronauts."""
    specs = [AstronautSpec(aid, name, scen, dict(base), ns)
             for aid, (name, scen, ns, base) in _DEMO_BASES.items()]
    rng = np.random.default_rng([seed, 9999])
    for i, (name, scen) in enumerate(zip(_EXTRA_NAMES, _EXTRA_SCENARIOS), start=4):
        base = dict(
            hr=round(float(rng.uniform(54, 74)), 1), hrv=round(float(rng.uniform(42, 78)), 1),
            spo2=round(float(rng.uniform(96.5, 98.5)), 1), resp_rate=round(float(rng.uniform(12.5, 17)), 1),
            temp=round(float(rng.uniform(36.4, 36.9)), 2), sleep_hours=round(float(rng.uniform(6.5, 7.6)), 1),
            sleep_quality=round(float(rng.uniform(0.65, 0.88)), 2),
            activity=round(float(rng.uniform(0.40, 0.65)), 2),
            exercise_score=round(float(rng.uniform(72, 88)), 1))
        specs.append(AstronautSpec(f"AST-{i:03d}", name, scen, base, round(float(rng.uniform(0.8, 1.3)), 2)))
    return specs


def _ar1(rng: np.random.Generator, n: int, sd: float, phi: float = PHI) -> np.ndarray:
    """Stationary AR(1) series with innovation sd ``sd``."""
    x = np.empty(n)
    x[0] = rng.normal(0, sd / np.sqrt(1 - phi ** 2))
    eps = rng.normal(0, sd, n)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + eps[i]
    return x


def _generate_one(spec: AstronautSpec, rng: np.random.Generator, n_days: int, start: pd.Timestamp) -> pd.DataFrame:
    n = n_days * 24
    hour = np.tile(np.arange(24), n_days)
    day_idx = np.repeat(np.arange(n_days), 24)
    t_hours = np.arange(n) / 24.0                        # fractional days at the start of each hour
    sev_h = severity(spec.scenario, t_hours + 0.5 / 24)  # severity at the middle of each hour
    sev_d = severity(spec.scenario, np.arange(1, n_days + 1, dtype=float))  # end of each day
    effects = SCENARIO_EFFECTS[spec.scenario]
    ns = spec.noise_scale
    cols: dict[str, np.ndarray] = {}

    for f in HOURLY_FEATURES:
        amp, peak = CIRCADIAN[f]
        circ = amp * np.sin(2 * np.pi * (hour - peak + 6) / 24)
        day_off = rng.normal(0, DAY_SD[f] * ns, n_days)[day_idx]
        noise = _ar1(rng, n, HOURLY_SD[f] * ns)
        cols[f] = spec.base[f] + circ + day_off + noise + effects.get(f, 0.0) * sev_h
    for f in DAILY_FEATURES:
        daily = spec.base[f] + rng.normal(0, DAILY_SD[f] * ns, n_days) + effects.get(f, 0.0) * sev_d
        cols[f] = daily[day_idx]

    for f, arr in cols.items():                          # bound to plausible synthetic range
        lo, hi = DEFAULT_VALID_RANGES[f]
        cols[f] = np.clip(arr, lo, hi)

    ts = pd.date_range(start, periods=n, freq="h")
    df = pd.DataFrame({"astronaut_id": spec.astronaut_id, "timestamp": ts,
                       "mission_day": day_idx + 1})
    for f in ["hr", "hrv", "spo2", "resp_rate"]:
        df[f] = np.round(cols[f], 1)
    df["temp"] = np.round(cols["temp"], 2)
    df["sleep_hours"] = np.round(cols["sleep_hours"], 2)
    df["sleep_quality"] = np.round(cols["sleep_quality"], 3)
    df["activity"] = np.round(cols["activity"], 3)
    df["exercise_score"] = np.round(cols["exercise_score"], 1)
    df["scenario"] = spec.scenario
    df["is_synthetic"] = True
    return df


def generate_dataset(seed: int = SEED, n_days: int = N_DAYS, mission_start: str = MISSION_START,
                     specs: Optional[list[AstronautSpec]] = None) -> pd.DataFrame:
    """Generate the full synthetic dataset (10 astronauts x ``n_days`` x 24 hourly rows).

    Deterministic: the same ``seed`` always returns identical data.  Each astronaut
    gets an independent random stream ``default_rng([seed, index])``, so adding or
    removing an astronaut does not change the others.
    """
    if n_days < 1:
        raise ValueError("n_days must be >= 1")
    specs = specs if specs is not None else get_astronaut_specs(seed)
    start = pd.Timestamp(mission_start)
    start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
    frames = [_generate_one(s, np.random.default_rng([seed, i]), n_days, start)
              for i, s in enumerate(specs)]
    return pd.concat(frames, ignore_index=True)


def inject_faults(df: pd.DataFrame, seed: int = SEED, missing_rate: float = 0.02,
                  duplicate_rate: float = 0.005, invalid_rate: float = 0.002) -> tuple[pd.DataFrame, dict]:
    """Return a corrupted copy of ``df`` (for demonstrating/testing the cleaning pipeline)."""
    rng = np.random.default_rng([seed, 31337])
    out = df.copy()
    cols = ["hr", "hrv", "spo2", "resp_rate", "temp", "activity"]
    miss = rng.random((len(out), len(cols))) < missing_rate
    for j, c in enumerate(cols):
        out.loc[miss[:, j], c] = np.nan
    bad_rows = np.flatnonzero(rng.random(len(out)) < invalid_rate)
    out.loc[out.index[bad_rows], "hr"] = rng.choice([-5.0, 999.0], size=len(bad_rows))
    dups = out.loc[rng.random(len(out)) < duplicate_rate]
    out = pd.concat([out, dups], ignore_index=True)
    counts = {"missing_cells_injected": int(miss.sum()), "invalid_hr_injected": int(len(bad_rows)),
              "duplicates_injected": int(len(dups))}
    return out, counts
