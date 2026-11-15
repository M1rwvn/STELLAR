# AstroGuardian - Computer Vision + Data Fusion (AI 3)

Hackathon prototype using SIMULATED data. This module:
1. Analyses a recorded squat video with MediaPipe Pose (skeleton, knee/back angles, reps).
2. Turns the movement into 3 vision features between 0 and 1.
3. Simulates spacesuit telemetry.
4. Fuses Wearable + Suit + Vision into one Unified Health Vector.

## Setup (Windows, Python 3.11)
    pip install -r requirements.txt

## Run
    python test_fusion.py                          # all tests must pass
    python run_demo.py --video samples/squat.mp4   # full pipeline -> outputs/
    python make_overlay_video.py --video samples/squat.mp4

`run_demo.py` writes to `outputs/`: `health.json` (POST /health-data payload),
`output_vector.json` (full vector for the AI model), `output_meta.json`
(which values were estimated), `overlay_output.mp4` (+ `.avi`).

## Files
| File | What it does |
|---|---|
| `schema.py` | Fixed column list (`CORE_COLUMNS`). Order and names must never change. |
| `vision_features.py` | Pose analysis. `extract_vision_features(video)` returns the 3 features + rep_count. |
| `suit_simulator.py` | `generate_suit_data(mode="normal"/"bad", seed=None)`. |
| `data_fusion.py` | `build_health_vector(wearable, suit, vision, baseline)` + `fatigue_rule` + placeholder `compute_deviation`. |
| `make_payload.py` | Builds the `POST /health-data` JSON. |
| `make_overlay_video.py` | Saves the demo video with skeleton and numbers. |
| `run_demo.py` | Runs everything end to end. |
| `test_fusion.py` | 13 tests (missing data, extreme values, fixed columns...). |

## Backend usage (Ghandor)
    from data_fusion import build_health_vector
    vector = build_health_vector(wearable, suit, vision, baseline)

Always returns the same 24 keys in the same order (`schema.CORE_COLUMNS`), never raises.
Missing values use: last known value -> baseline (midpoint if a range) -> safe default
(vision default is 0.5). Estimated fields are reported by `build_health_vector_with_meta`.

## Core columns (v1.0, 24)
8 wearable, 4 suit, 3 vision, 8 `<metric>_dev_pct`, `fatigue_risk`.

## Vision features
- `posture_score`: less back lean from vertical = higher.
- `movement_quality`: consistent depth and duration across reps = higher.
- `fatigue_indicator`: later reps slower / shallower than early reps = higher.
With fewer than 2 complete reps (or no pose) all three return a neutral 0.5.

## Notes
- `compute_deviation` is a placeholder; replace it with Shimaa's version (same signature).
- Emotion/Reaction features are NOT part of this version (not in the agreed contract).
- All values are simulated / heuristic estimates, not a medical diagnosis.
