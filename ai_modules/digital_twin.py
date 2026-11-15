"""AI 1 - Digital Twin (Shimaa), plugged into the backend.

Source: Shimaa's `astroguardian_digital_twin` v1.1.0, copied unmodified into
`ai_modules/astroguardian_digital_twin/`. Profiles were built by her pipeline
(seed 42, calibration days 1-14) and live in `ai_modules/profiles/all_profiles.json`.

v1.1 adds `online_features` (training-identical history features at runtime) and
`explain_deviation` (top reasons as English + Arabic sentences).

To update after Shimaa changes something: copy her `src/astroguardian_digital_twin/*.py`,
`outputs/profiles/all_profiles.json` and `data/demo/*.csv` over these, then run `python -m pytest`.
"""
import os
from pathlib import Path

# Her get_baseline() reads profiles from this folder (it rebuilds them only if missing)
os.environ.setdefault("ASTROGUARDIAN_PROFILE_DIR", str(Path(__file__).resolve().with_name("profiles")))

from ai_modules.astroguardian_digital_twin import (  # noqa: E402
    UnknownAstronautError,
    compute_deviation,
    compute_deviation_detailed,
    explain_deviation,
    get_baseline,
    online_features,
)

__all__ = ["get_baseline", "compute_deviation", "compute_deviation_detailed", "UnknownAstronautError",
           "online_features", "explain_deviation"]
