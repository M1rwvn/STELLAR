# Changelog — STELLAR risk model (Menna)

## 1.1.0 (English) — 2026-11-15
Comments, docstrings and report notes translated from Arabic to English for the public repository.
No code change: the syntax tree with all text blanked is identical, and the tests give the same results.

## 1.1.0 — integration review with the backend (2026-11-14)
Reviewed by the Backend Lead against the AI 2 brief, Shimaa's data and the running backend.
v1.0 is fully reproducible: retraining the v1.0 code gave the same predictions on all 10,990 rows
(max difference 1e-14) and the same evaluation report as `training_log_v1.0.txt`.

### Fixed (integration / safety)
- **Silent "Normal" on failure.** v1.0 wrapped `predict_risk` in `except Exception` and returned
  `{"risk_score": 12, "level": "Normal", ...}` with the error hidden in an `error` key. Called from another
  folder (as the backend does) the model file was not found and **Omar's emergency came back as Normal 12**.
  Now a missing/broken model raises; bad *inputs* are still handled without errors (all 16 robustness
  cases still pass).
- **Model path** is now next to `physio_model.py` (was relative to the caller's current folder).
- **Training/runtime mismatch.** The model is trained on 24 h rolling means of the deviations (`<c>_s`),
  but `predict_risk` preferred the instantaneous `<c>` when both were given. It now prefers `<c>_s` and
  falls back to `<c>`. Measured on Shimaa's data, instantaneous inputs gave Ahmed 30 false-alarm hours
  and Sara 9 Emergency hours; 24 h averages give Ahmed 0 and Sara 0.
- **No import side effects.** matplotlib and the stdout re-encoding now load only when training
  (`python physio_model.py`), not when the backend imports `predict_risk`.

### Changed (model, retrained)
- NEWS points for `stress_score_pct_dev`: **max 2 points** (was 3; thresholds 30 % / 60 %).
  Shimaa's stress score is computed from HR and HRV, which NEWS already scores, so a third stress point let
  one derived signal dominate: Sara (expected yellow) reached High Risk on 13 hours of day 60 only because
  of it. Options compared (leave-one-astronaut-out on Shimaa's data):

  | Option | False alarms | Attention found | Emergency rows → High/Emerg | Sara High hours (d50-60) | Sara yellow from |
  |---|---|---|---|---|---|
  | v1.0: stress up to 3 pts | 8 | 52 % | 88 % | 13 | day 42 |
  | **v1.1: max 2 pts (30/60 %)** | 8 | **53 %** | **87 %** | **0** | **day 42** |
  | max 2 pts (60/100 %) | 0 | 41 % | 87 % | 1 | day 48 |
  | max 1 pt | 0 | 38 % | 82 % | 0 | — |
  | stress removed | 0 | 37 % | 79 % | 0 | — |

  The chosen option keeps the early warning and the emergency sensitivity, and fixes Sara.

### Added
- `test_v11.py` (pytest): works from any folder, broken model is loud, no import side effects, prefers 24 h
  averages, and the Definition of Done on Shimaa's data every hour — Ahmed always green, Sara never orange
  and yellow every hour of days 50-60 (from day 42), Omar red every hour of days 57-60 and green until day 54.
- `training_log_v1.0.txt` / `training_log_v1.1.txt`.

### Still open (honest limitations, unchanged)
- Only one emergency astronaut: leave-one-astronaut-out Emergency recall is 0 % (an unseen astronaut's
  emergency is recognised as High Risk 87 % of the time, never as Emergency). More synthetic emergency
  cases from AI 1 would allow a real evaluation.
- The Random Forest has no High Risk class (no such labels); High Risk comes from the NEWS part only.
- Sara's highest score on day 60 is 49.9 (limit 50): correct but with a small margin.
- In-sample demo numbers are optimistic; labels are weak (scenario + day).
- `top_factors` (seen in the live run): `stress_score` is often the first reason with large numbers
  ("+272 %") because its % deviation is taken from a small index (~25). For a Normal reading it can also list
  a healthy-direction change ("stress_score -12 %"). Suggestion: rank by harmful direction only and show
  stress after HR/HRV. The backend shows Shimaa's explanation sentences in the app, so users are not affected.
