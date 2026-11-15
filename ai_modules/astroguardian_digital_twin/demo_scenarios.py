"""Demo scenarios (Ahmed / Sara / Omar): artifact writer + pattern checks.

The checks below verify the DIRECTION and size of the deliberately injected synthetic changes.
They are scenario-design checks, not model predictions: classification into risk levels belongs
to AI Member 2's component.

CLI:  python -m astroguardian_digital_twin.demo_scenarios --output-root . --seed 42
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from .baseline import load_config
from .data_cleaning import CANONICAL_COLUMNS
from .data_generator import SEED
from .profiles import PipelineResult, run_pipeline, save_profiles

DEMO_SCENARIOS = {
    "ahmed": ("AST-001", "ahmed_normal.csv", "normal"),
    "sara": ("AST-002", "sara_attention.csv", "attention"),
    "omar": ("AST-003", "omar_emergency.csv", "emergency"),
}


def _to_csv(df: pd.DataFrame, path: Path) -> None:
    out = df.copy()
    out["timestamp"] = out["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    # "\n" so the files are byte-identical on Windows, macOS and Linux
    out.to_csv(path, index=False, float_format="%.4f", lineterminator="\n")


def daily_table(features: pd.DataFrame, astronaut_id: str) -> pd.DataFrame:
    """Mean percent deviation per mission day (post-calibration rows only)."""
    g = features[(features["astronaut_id"] == astronaut_id) & features["hr_pct_dev"].notna()]
    cols = [c for c in g.columns if c.endswith("_pct_dev")] + ["temp_delta_c"]
    return g.groupby("mission_day")[cols].mean()


def _block_mean(daily: pd.DataFrame, col: str, d0: int, d1: int) -> float:
    return float(daily.loc[d0:d1, col].mean())


def evaluate_demo_patterns(res: PipelineResult) -> dict[str, Any]:
    """Evidence + pass/fail flags for the three required demo patterns."""
    f, prof = res.features, res.profiles
    ev: dict[str, Any] = {}
    ids = [v[0] for v in DEMO_SCENARIOS.values()]
    centers = {a: prof[a]["baseline_detail"]["hr"]["center"] for a in ids}
    ev["hr_baseline_centers"] = centers
    ev["distinct_baselines"] = bool(len({round(c, 1) for c in centers.values()}) == 3
                                    and prof["AST-001"]["baseline"] != prof["AST-002"]["baseline"])

    # Ahmed: broadly inside his own pattern
    da = daily_table(f, "AST-001")
    hr_a = f[(f.astronaut_id == "AST-001") & (f.mission_day > 14)]
    d = prof["AST-001"]["baseline_detail"]["hr"]
    within = float(np.mean(np.abs(hr_a["hr"] - d["center"]) <= 3 * d["robust_sigma"]))
    ev["ahmed"] = {"mean_abs_daily_hr_dev_pct": float(da["hr_pct_dev"].abs().mean()),
                   "mean_abs_daily_sleep_dev_pct": float(da["sleep_hours_pct_dev"].abs().mean()),
                   "fraction_hr_within_3_sigma": within}
    ev["ahmed_stable"] = bool(ev["ahmed"]["mean_abs_daily_hr_dev_pct"] < 3
                              and ev["ahmed"]["mean_abs_daily_sleep_dev_pct"] < 5 and within > 0.95)

    # Sara: progressive change from day 40
    ds = daily_table(f, "AST-002")
    blocks = [(15, 39), (41, 47), (48, 54), (55, 60)]   # pre-onset, then three post-onset blocks
    sleep_b = [_block_mean(ds, "sleep_hours_pct_dev", *b) for b in blocks]
    hr_b = [_block_mean(ds, "hr_pct_dev", *b) for b in blocks]
    act_b = [_block_mean(ds, "activity_pct_dev", *b) for b in blocks]
    ev["sara"] = {"blocks_days": blocks, "sleep_pct_dev_by_block": sleep_b,
                  "hr_pct_dev_by_block": hr_b, "activity_pct_dev_by_block": act_b}
    def _rising(b):   # progressive increase: blocks 2..4 strictly increasing, last well above pre-onset
        return bool(b[1] < b[2] < b[3] and b[0] < b[2])

    def _falling(b):
        return _rising([-x for x in b])
    ev["sara_progressive"] = bool(_falling(sleep_b) and _rising(hr_b) and _falling(act_b)
                                  and sleep_b[-1] < -8 and hr_b[-1] > 4 and act_b[-1] < -8)

    # Omar: final five days
    do = daily_table(f, "AST-003")
    om = f[f.astronaut_id == "AST-003"]
    last = om[om.mission_day >= 56]
    last_day = om[om.mission_day == 60]
    pre = do.loc[15:55]
    ev["omar"] = {
        "last5_mean_pct_dev": {k: float(do.loc[56:60, f"{k}_pct_dev"].mean())
                               for k in ("hr", "hrv", "spo2", "sleep_hours")},
        "last5_mean_temp_delta_c": float(do.loc[56:60, "temp_delta_c"].mean()),
        "day60_mean": {k: float(last_day[k].mean()) for k in ("hr", "hrv", "spo2", "temp", "sleep_hours")},
        "pre_event_mean_abs_hr_dev_pct": float(pre["hr_pct_dev"].abs().mean()),
    }
    o = ev["omar"]
    ev["omar_emergency_pattern"] = bool(
        o["last5_mean_pct_dev"]["hr"] > 15 and o["last5_mean_pct_dev"]["hrv"] < -25
        and o["last5_mean_pct_dev"]["spo2"] < -2 and o["last5_mean_pct_dev"]["sleep_hours"] < -25
        and o["last5_mean_temp_delta_c"] > 0.6 and o["day60_mean"]["spo2"] < 94.5
        and o["day60_mean"]["temp"] > 37.4 and o["day60_mean"]["sleep_hours"] < 4.6
        and o["pre_event_mean_abs_hr_dev_pct"] < 3)
    ev["all_passed"] = bool(ev["distinct_baselines"] and ev["ahmed_stable"]
                            and ev["sara_progressive"] and ev["omar_emergency_pattern"])
    return ev


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_demo_artifacts(output_root: str | Path = ".", seed: int = SEED,
                         result: Optional[PipelineResult] = None) -> dict[str, Any]:
    """Write raw/processed/demo CSVs, profile JSONs and the demo report. Returns a manifest."""
    root = Path(output_root)
    res = result or run_pipeline(seed=seed)
    for sub in ("data/raw", "data/processed", "data/demo", "outputs/profiles"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    raw_cols = [c for c in res.raw.columns]
    _to_csv(res.raw[raw_cols], root / "data/raw/synthetic_wearable_raw.csv")
    _to_csv(res.features, root / "data/processed/features_all_astronauts.csv")
    try:  # optional Parquet (needs pyarrow or fastparquet)
        res.features.to_parquet(root / "data/processed/features_all_astronauts.parquet", index=False)
    except (ImportError, ValueError):
        pass
    demo_files = {}
    for name, (aid, fname, _) in DEMO_SCENARIOS.items():
        sub = res.features[res.features["astronaut_id"] == aid]
        _to_csv(sub, root / "data/demo" / fname)
        demo_files[name] = fname
    save_profiles(res.profiles, root / "outputs/profiles")
    evidence = evaluate_demo_patterns(res)
    report = {"seed": seed, "synthetic": True, "cleaning_report": res.cleaning_report.to_dict(),
              "pattern_checks": evidence,
              "note": "Direction-of-change checks on synthetic scenarios; no risk score is computed here."}
    (root / "outputs/demo_report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n",
                                                  encoding="utf-8", newline="\n")
    return {"root": str(root), "demo_files": demo_files, "report": report}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Generate synthetic data, profiles and demo files.")
    ap.add_argument("--output-root", default=".", help="project root to write data/ and outputs/ into")
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args(argv)
    manifest = write_demo_artifacts(args.output_root, args.seed)
    checks = manifest["report"]["pattern_checks"]
    print(f"Wrote synthetic artifacts to {Path(args.output_root).resolve()}")
    for k in ("distinct_baselines", "ahmed_stable", "sara_progressive", "omar_emergency_pattern"):
        print(f"  {k}: {checks[k]}")
    return 0 if checks["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
