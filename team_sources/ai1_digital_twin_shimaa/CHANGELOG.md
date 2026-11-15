# Changelog

## 1.1.0 - integration review with the backend (2026-10-28)
Reviewed by the Backend Lead against the AI 1 brief and the running backend. All 98 v1.0 tests still pass;
124 tests in total. The synthetic data (raw, features, demo CSVs) is **byte-for-byte the same content** as v1.0.

### Added
- `online.py` - `online_features(history, profile)`: the training table's history features (rolling means,
  sleep debt, stress score, % deviations) for one live reading, from the last 7 days. Without it a model trained on
  `features_all_astronauts.csv` would receive 25 of its 35 input columns empty at runtime (train/serve skew).
  `tests/test_online.py` proves equality with the training table for all 10 astronauts (~180 hours each).
- `explain.py` - `explain_deviation(reading, baseline)`: task 11 (explanation text). Top harmful deviations as
  sentences in English and Arabic + a recommendation, with the right unit per metric (points for SpO2, degC for
  temperature). Beyond 5 personal SD, clinical priority orders the reasons (SpO2, temperature, heart rate first).
- Profile key `online_reference` (frozen calibration statistics used by `online_features`).
- Notebook sections 9-11: four presentation charts (saved to `outputs/figures/`), runtime parity, explanations.
  The notebook is now executed and committed with its outputs.
- `docs/research_summary.md` section 3b: the topics left PENDING in v1.0 (hazards, bone, SANS, body temperature,
  HRV rhythm, radiation, isolation) with retrieved sources; secondary sources are marked.
- Replay: `--username/--password` (logs in to the backend), `--verbose`, error messages include the backend reply.

### Changed
- Default normal range: Q1-Q3 -> median +/- 2 robust SD (`median_mad`, k = 2). Q1-Q3 holds only half of a person's
  normal readings, so the app would show a healthy astronaut "out of range" half the time (Ahmed SpO2: 47 %).
  Now >= 91 % coverage for every astronaut and metric; Ahmed: 3 % flagged. Centers (medians) are unchanged.
- Intervals are clamped to the plausibility range of each feature (no negative stress score).
- CSV and JSON outputs use LF line endings, so files are byte-identical on Windows, macOS and Linux
  (v1.0 files differed between operating systems only by line endings). `.gitattributes` added.

### Open for the team
- Deviation column names: `<m>_pct_dev` (this module) vs `<m>_dev_pct` (AI 3 brief).
- Omar's emergency ramps from day 56 to day 60; the brief describes the full values for the last five days.
