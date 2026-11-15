"""Task 11: explanation sentences (English + Arabic) for the top harmful deviations."""
from pathlib import Path

import pandas as pd
import pytest

from astroguardian_digital_twin import explain_deviation

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def ahmed(pipeline):
    return pipeline.profiles["AST-001"]


def test_brief_example_ahmed(ahmed):
    """Brief: 'Ahmed's HR is 60-65, today 72 and sleep 4.9 - not normal for him'."""
    out = explain_deviation({"hr": 72, "sleep_hours": 4.9}, ahmed)
    metrics = [r["metric"] for r in out["reasons"]]
    assert set(metrics) == {"hr", "sleep_hours"}
    sleep = next(r for r in out["reasons"] if r["metric"] == "sleep_hours")
    assert sleep["text"]["en"].startswith("Sleep is 29% below your normal")
    assert sleep["text"]["ar"].startswith("النوم أقل من معدلك الطبيعي بنسبة 29%")
    assert out["recommendation"]["en"] and out["recommendation"]["ar"]


def test_normal_reading_has_no_reasons(ahmed):
    centers = {m: d["center"] for m, d in ahmed["baseline_detail"].items()}
    out = explain_deviation({k: centers[k] for k in ("hr", "hrv", "spo2", "temp", "sleep_hours")}, ahmed)
    assert out["reasons"] == []
    assert out["summary"]["en"].startswith("All measured values are within")


def test_healthy_direction_is_never_a_reason(ahmed):
    c = {m: d["center"] for m, d in ahmed["baseline_detail"].items()}
    out = explain_deviation({"hrv": c["hrv"] * 1.4, "sleep_hours": c["sleep_hours"] + 1.5,
                             "spo2": 99.5, "hr": c["hr"] * 0.85}, ahmed)
    assert out["reasons"] == []


def test_units_temp_in_degrees_spo2_in_points(ahmed):
    out = explain_deviation({"temp": 37.8, "spo2": 93.0}, ahmed)
    texts = {r["metric"]: r["text"]["en"] for r in out["reasons"]}
    assert "°C above your normal" in texts["temp"] and "%" not in texts["temp"].split("(")[0]
    assert "points below your normal" in texts["spo2"]


def test_omar_last_day_reasons_are_his_emergency_signs():
    from astroguardian_digital_twin import get_baseline
    df = pd.read_csv(ROOT / "data/demo/omar_emergency.csv")
    row = df[(df.mission_day == 60) & df.timestamp.str.contains("T12:")].iloc[0]
    wear = {k: float(row[k]) for k in ("hr", "hrv", "spo2", "resp_rate", "temp", "sleep_hours",
                                       "sleep_quality", "activity")}
    out = explain_deviation(wear, get_baseline("AST-003"))
    assert len(out["reasons"]) == 3
    # every sign is extreme (> 5 SD), so clinical priority leads: low oxygen and fever first
    assert [r["metric"] for r in out["reasons"]][:2] == ["spo2", "temp"]
    assert all(r["sigmas"] >= 1 for r in out["reasons"])


def test_top_n(ahmed):
    out = explain_deviation({"hr": 90, "hrv": 30, "sleep_hours": 4, "spo2": 92, "temp": 38.2}, ahmed, top_n=2)
    assert len(out["reasons"]) == 2
    capped = [min(r["sigmas"], 5.0) for r in out["reasons"]]
    assert capped == sorted(capped, reverse=True)
