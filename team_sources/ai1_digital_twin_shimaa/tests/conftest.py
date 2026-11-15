import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from astroguardian_digital_twin.profiles import run_pipeline  # noqa: E402


@pytest.fixture(scope="session")
def pipeline():
    """Full seed-42 pipeline, computed once per test session."""
    return run_pipeline(seed=42)


def make_frame(n=10, aid="A", start="2026-08-25T00:00:00Z", **overrides):
    """Small clean hourly frame for unit tests."""
    ts = pd.date_range(start, periods=n, freq="h", tz="UTC")
    d = {"astronaut_id": aid, "timestamp": ts, "hr": 60.0 + np.arange(n), "hrv": 60.0, "spo2": 97.0,
         "resp_rate": 15.0, "temp": 36.7, "sleep_hours": 7.0, "sleep_quality": 0.8, "activity": 0.5}
    d.update(overrides)
    return pd.DataFrame(d)
