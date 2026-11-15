# ai_modules/ — the AI team's real models

The team's own files use working names for the demo astronauts: Ahmed = Ethan Cole (AST-001),
Sara = Emily Carter (AST-002), Omar = Ryan Mitchell (AST-003). The app shows the new names.

The backend calls exactly these functions (Annex 2 of the briefs). Until a module
exists here, the backend uses the stubs in `app/ai/stubs/`, which follow the same
signatures and output shapes. **No backend change is needed to switch.**

| File | Owner | Must define | Status |
|---|---|---|---|
| `ai_modules/digital_twin.py` | Shimaa (AI 1) | `get_baseline(astronaut_id: str) -> dict`, `compute_deviation(reading: dict, baseline: dict) -> dict` | **live** |
| `ai_modules/fusion.py` | Mariam (AI 3) | `build_health_vector(wearable: dict, suit: dict, vision: dict, baseline: dict) -> dict` | **live** (Core v1.0) |
| `ai_modules/risk.py` | Menna (AI 2) | `predict_risk(vector: dict) -> dict` | **live** (v1.1.0) |

Each file is picked up on its own.

## Shimaa's Digital Twin (live, v1.1.0)

- `digital_twin.py` is a small connector; her package is in `astroguardian_digital_twin/`,
  copied unmodified from her repo (`src/astroguardian_digital_twin/`, tag `v1.1.0`).
- v1.1 adds `online_features` (the backend calls it on every reading with the last 7 days, so
  the model vector has the training table's history columns) and `explain_deviation`
  (plain-English reasons, shown in `/risk-score` and in alerts).
- Her profiles are in `profiles/all_profiles.json` (seed 42, calibration days 1–14).
- Her demo data is in `../data/scenarios/` (her `data/demo/*.csv`).
- To update: copy her new `src/astroguardian_digital_twin/*.py`, `outputs/profiles/all_profiles.json`
  and `data/demo/*.csv` over these, then run `python -m pytest`.
- `get_baseline` returns the full profile, including `baseline_detail` (median, normal range =
  median ± 2 robust SD, robust sigma per metric) and `online_reference`. **Pass the full profile on to `compute_deviation`**: it then
  uses the precise medians and also covers `resp_rate` and `sleep_quality`.
- `compute_deviation` gives no percentage for `temp` (a % of °C is meaningless). Use the
  absolute temperature, or `compute_deviation_detailed(...)["metrics"]["temp"]["abs_deviation"]`.

## Mariam's Computer Vision + Data Fusion (live, Core v1.0)

- `fusion.py` is the connector; her files are in `mariam_cv_fusion/` (`schema.py`, `data_fusion.py`,
  `suit_simulator.py`, her README), copied unmodified from `astroguardian-cv-fusion`.
- Her video analysis (`vision_features.py`, MediaPipe Pose on a squat video -> posture_score,
  movement_quality, fatigue_indicator) runs on the device with the camera and is not needed by the server;
  her full repo, sample video and overlay video are in the project's `team_sources/`.
- The connector replaces her placeholder `compute_deviation` with AI 1's real one, gives her the personal
  medians as baseline, keeps her last-known-value memory per astronaut, and adds `environment_flags`
  (cabin values outside safe limits) and `imputed`.
- `demo_sensors.py` adds suit telemetry every hour (her `generate_suit_data`, seeded) and a daily camera
  check to the Digital Twin's wearable data, so the full Wearable + Suit + Vision flow runs in the demo.
- `/risk-score` returns the fused values in `fusion` (vitals, suit, vision, fatigue level, flags).

## Menna's risk model (live, v1.1.0)

- `risk.py` is the connector; her files are in `menna_risk/` (`physio_model.py`, `physio_risk.py`,
  `physio_model.joblib`), copied from her v1.1.0 with code unchanged (comments translated to English).
- The model file is loaded with an **allow-list**: only numpy / scikit-learn / joblib objects can be
  created, so a tampered `.joblib` is refused before anything runs (`tests/test_integration_ai2.py`).
- Her model is trained on **24 h rolling means** of the deviations (`<k>_s`). The pipeline adds them to the
  vector from the stored readings (`add_24h_means`), and they equal her training feature
  (checked through the API). Before 6 readings exist, her code falls back to the current value.
- Predictions run on one thread (same results; no thread pool per reading); < 1 s per reading with history.
- If her model raises, that reading is scored by the stub and the error is logged - never a silent Normal.
- To update after a retrain: copy her three files over `menna_risk/` and run `python -m pytest`.

## For Menna (risk model): what the vector contains at runtime
The vector passed to `predict_risk` (and stored per reading) has AI 3's fusion columns **plus**
AI 1's history features with the training names: `hr_roll24h_mean` … `activity_roll168h_mean`,
`hr_roll24h_std`, `sleep_debt_7d`, `sleep_hours_roll7d_mean`, `stress_score`, `<m>_pct_dev`,
`temp_delta_c`. Train on those names from `data/processed/features_all_astronauts.csv` and they
will be there live (`None` only when history is shorter than the window — handle missing values).
`exercise_score` is not available at runtime (not in the wearable payload): don't use it.

## Rules that keep the integration painless

1. **Same output shapes as the contract.**
   - `get_baseline` → `{"astronaut_id", "name", "baseline": {"hr": [60, 65], ...}, "recovery_score", ...}`
     (returning just the inner `baseline` dict also works).
   - `compute_deviation` → `{"hr": 14.4, "sleep_hours": -30.0}` (% per metric).
   - `build_health_vector` → flat dict with fixed column names + optional `"imputed": [...]`.
     `baseline` is the full profile from `get_baseline`; read the inner ranges with
     `baseline.get("baseline", baseline)`, and medians from `baseline["baseline_detail"]`.
   - `predict_risk` → `{"risk_score": 0-100, "level": "Normal|Attention|High Risk|Emergency", "top_factors": [{"feature", "change_pct"}], "recommendation": str}`.
2. **One reading at a time.** The backend calls you once per `POST /health-data`.
   Readings are **hourly**: at night activity is near zero and HR is lower — that is
   normal rhythm, not risk.
3. **Never crash on a missing value** (sensor dropped out) or an extreme one.
4. **Load models once**, at import time, with a path relative to the file:
   ```python
   from pathlib import Path
   import joblib
   MODEL = joblib.load(Path(__file__).with_name("risk_model.joblib"))
   ```
   Put `.joblib` / `.csv` files next to your module in this folder.
5. Fusion should call AI 1 through the backend so the real one is used:
   `from app.ai import compute_deviation`.
6. Add any new libraries (scikit-learn, xgboost, joblib...) to `requirements.txt`
   with a pinned version, in the same PR. The team runs Python 3.11 – 3.14, so pick a
   version that has wheels for all of them (recent releases do; old pins often don't).
7. Don't train on the `scenario` column of Shimaa's CSVs: it is the answer (data leakage).

## Safety net

If your function raises at runtime, the backend logs the error and answers with
the stub for that request, so the demo keeps running. `GET /health` shows which
modules are live: `{"ai": {"digital_twin": "real", "fusion": "stub", "risk": "stub"}}`.
Set `AI_MODE=real` to make a broken module fail loudly instead (good while testing).

## Check your module before the PR

```bash
.venv\Scripts\python -m pytest tests/test_ai_contract.py -v
```
These tests run against whatever is installed (real or stub) and check the shapes,
missing values, and the demo expectation on Shimaa's data: Ethan = Normal,
Emily = Attention, Ryan = Emergency on every hour of the last day, and all three
Normal during calibration (days 1–14).
