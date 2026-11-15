# Interface contract and open questions

## Public functions (exact signatures)
```python
get_baseline(astronaut_id: str) -> dict
compute_deviation(reading: dict, baseline: dict) -> dict
```
* `get_baseline` returns the profile (below). Unknown IDs raise `UnknownAstronautError` (subclass of `KeyError`) -
  map to HTTP 404. IDs are case-sensitive; nothing is substituted. Non-str raises `TypeError`.
  Profiles are read from `outputs/profiles/all_profiles.json` (or `$ASTROGUARDIAN_PROFILE_DIR`); if absent they are
  rebuilt deterministically (seed 42) in memory.
* `compute_deviation({"hr": 72, "sleep_hours": 4.9}, baseline)` -> flat `{"hr": <pct>, "sleep_hours": <pct>}`
  (values depend on the baseline; not hard-coded). Accepts the baseline from `get_baseline` and also a nested
  `{"wearable": {...}}` reading. If `astronaut_id` is present in both and differs, it raises `ValueError`.
* `compute_deviation_detailed(reading, baseline)` (extra, optional) adds center, interval, `abs_deviation`,
  `scaled_deviation`, `position` (within/below/above interval) and a `skipped` map with reasons.

## Profile JSON (v1.0.0)
```json
{"astronaut_id": "AST-001", "name": "Ahmed",
 "baseline": {"hr": [60.3, 64.2], "hrv": [58.2, 64.4], "spo2": [97.2, 97.7],
              "sleep_hours": 6.9, "temp": [36.59, 36.78], "activity": 0.527},
 "recovery_score": 78,
 "baseline_detail": {"hr": {"center": 62.4, "low": 60.3, "high": 64.225, "robust_sigma": 2.91,
                            "interval_method": "iqr", "n_samples": 336, "unit": "bpm", "status": "ok"}, "...": {}},
 "calibration": {"start": "...", "end": "...", "n_rows": 336, "complete": true},
 "schema_version": "1.0.0", "synthetic": true, "data_label": "SYNTHETIC DATA ..."}
```
(Numbers are illustrative; real values are in `outputs/profiles/`.) The agreed `baseline` keys are unchanged.
`mission_day` and `status` of `GET /astronaut-profile/{id}` are computed by the backend, not by this module.

## Replay -> `POST /health-data`
`python -m astroguardian_digital_twin.replay --scenario omar` prints one JSON per line:
`{"astronaut_id", "timestamp" (UTC, Z), "wearable": {hr, hrv, spo2, resp_rate, temp, sleep_hours, sleep_quality, activity}}`.
`suit`/`vision` belong to other owners and are omitted (or sent as `{}` with `--include-empty-sections`).
Local by default; HTTP only with `--post-url` (+ optional `ASTROGUARDIAN_TOKEN` bearer token).

## Added in v1.1 (optional, additive - agreed signatures unchanged)
```python
online_features(history: list[dict], profile: dict) -> dict   # training-identical history features
explain_deviation(reading: dict, baseline: dict, top_n: int = 3) -> dict   # reasons in English + Arabic
```
* `online_features`: `history` = the astronaut's readings of the last 7 days incl. the newest (flat rows or
  POST /health-data payloads, any order). Returns the training columns for the newest reading; `None` where history is
  too short. Needs `profile["online_reference"]` (profiles schema 1.1.0). The backend calls it on every reading and
  stores the result in the reading's vector, so Menna's model gets the same inputs it was trained on.
* `explain_deviation`: `{"reasons": [{"metric", "change_pct", "abs_change", "sigmas", "text": {"en", "ar"}}],
  "summary": {"en", "ar"}, "recommendation": {"en", "ar"}}`. Only harmful-direction changes >= 1 personal SD; SpO2 in
  points, temperature in degC. The backend shows it in `GET /risk-score` (`explanation`) and in alert messages.
* Profile key `online_reference` (new); `schema_version` "1.1.0"; intervals now median +/- 2 robust SD.

## Answers from the backend (Ghandor) to the open questions below
1. `baseline_detail` / `calibration` / `online_reference`: accepted and stored; `/astronaut-profile` exposes `baseline`
   and `recovery_score` only. 2. `recovery_score` top-level (integer): agreed. 3. Flat `compute_deviation`: agreed.
4. No % for `temp`: agreed (the risk stub uses absolute temperature; `temp_delta_c` is in the vector).
5-6. Interval method / median: agreed; v1.1 default is median +/- 2 robust SD (see baseline_methodology.md).
7. `stress_score` / `exercise_score`: now come from `online_features` at runtime. 8. `scenario` = label: agreed.
9. Mission start 2026-08-25: agreed. 10. Timeline: met.
Open for the team: deviation column naming `<m>_pct_dev` (this module) vs `<m>_dev_pct` (AI 3 brief) - the
backend currently sends both.

## Proposed contract changes / open questions (need a message in the team group + Ghandor's approval)
1. **`baseline_detail` and `calibration`** are NEW optional keys. Agreed keys are untouched. Ask Ghandor whether the
   backend model tolerates extra fields.
2. **`recovery_score` location**: the PDF example puts it *inside* `baseline`, the task text puts it at top level,
   endpoint 3 has none. Implemented at **top level** (keeps `baseline` exactly as agreed). Confirm.
3. **`compute_deviation` return shape**: flat `{metric: pct}` as in the PDF example. Richer data is in the separate
   `compute_deviation_detailed`, so the agreed signature/shape is not changed.
4. **`temp` has no percent deviation** (degC percent is not meaningful). If Menna's model needs it, use
   `temp_delta_c`/`abs_deviation`. Confirm with AI 2.
5. **Baseline interval method**: PDF allows Q1-Q3 or mean +/- 1.5 std; default is Q1-Q3 (configurable).
6. **Center = median**, whereas the PDF formula says "mean"; the task text asks for a robust median.
7. `stress_score`/`exercise_score` are internal derived features and are not in the wearable payload.
8. `scenario` in CSVs is a ground-truth label (leakage if used as a feature).
9. Mission start 2026-08-25 is an assumption (makes 2026-10-05 = day 42, as in the endpoint-3 example).
10. Task-file timeline (preliminary data day 9, final day 12; contract schema day 5) - confirm that these files satisfy AI 2/AI 3.
