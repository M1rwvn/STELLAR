# Data dictionary (all data SYNTHETIC)

## Canonical external schema (names/units agreed with the team - unchanged)
| Column | Unit | Frequency | Notes |
|---|---|---|---|
| astronaut_id | text | - | `AST-001` ... `AST-010` |
| timestamp | ISO-8601 UTC (`...Z`) | hourly | mission start 2026-08-25T00:00:00Z (day 1) |
| hr | bpm | hourly | |
| hrv | ms | hourly | |
| spo2 | percentage points | hourly | |
| resp_rate | breaths/min | hourly | |
| temp | degC | hourly | |
| sleep_hours | hours/day | daily, repeated on 24 rows | |
| sleep_quality | 0-1 | daily, repeated | |
| activity | 0-1 | hourly | |
| stress_score | 0-100 | derived, hourly | internal indicator, see formula below; NaN for first ~14 h (warm-up) |
| exercise_score | 0-100 | daily, repeated | synthetic training-plan adherence |

The backend wearable payload contains only the 8 raw fields (hr ... activity). `stress_score` and `exercise_score`
are internal/derived and are not sent by the replay script.

## Internal columns (documented extensions; not part of the agreed external schema)
`mission_day` (1-based), `scenario` (generator ground-truth label - do not use as a feature), `is_synthetic` (True),
`was_imputed`, `is_calibration` (mission_day <= 14), rolling features, `sleep_debt_7d`, `sleep_hours_roll7d_mean`,
and `<metric>_pct_dev` / `temp_delta_c`.

## Feature formulas (all causal: current + past only)
* `<f>_roll24h_mean`, `<f>_roll168h_mean` for f in hr, hrv, spo2, resp_rate, temp, activity: mean over the astronaut's
  rows in (t-W, t]; needs >= 6 rows. `hr_roll24h_std`: sample std over the same window.
* `sleep_debt_7d` = sum over the last 7 mission days (incl. today) of max(0, 8.0 - sleep_hours).
  The 8.0 h need is an **engineering assumption** (configurable `sleep_need_hours`).
* `sleep_hours_roll7d_mean`: mean of the last 7 daily sleep values.
* `stress_score` = clip(25 + 12.5 * (z_hr + z_hrv)/2, 0, 100), z_hr = (hr_6h - mu_hr)/sd_hr,
  z_hrv = (mu_hrv - hrv_6h)/sd_hrv. hr_6h/hrv_6h are trailing 6 h means; mu/sd are expanding mean/std of the
  astronaut's own calibration-period (days 1-14) values available so far, frozen after day 14.
* `<metric>_pct_dev` = (value - baseline_center)/|baseline_center| * 100, NaN on calibration days (the baseline is
  not final yet). `temp_delta_c` = temp - baseline center (degC).

## Runtime features (v1.1): `online_features(history, profile)`
Returns, for the newest reading, the training columns above (rolling means, `hr_roll24h_std`, `sleep_debt_7d`,
`sleep_hours_roll7d_mean`, `stress_score`, `<metric>_pct_dev`, `temp_delta_c`) from the last 7 days of readings,
with the same windows and formulas. The stress reference (mean/scale of the 6 h HR/HRV means over the calibration
rows) is frozen in `profile["online_reference"]`. Equality with the training table is tested
(`tests/test_online.py`). Values that need more history than available are `null`; `exercise_score` is `null`
at runtime (not in the wearable payload).

**Naming note:** AI 3's brief names deviation columns `<metric>_dev_pct`; this table uses `<metric>_pct_dev`. The
backend sends both, with identical values, until the team picks one.

## Synthetic assumptions
Signal = personal base + 24 h sinusoid (HR/activity/resp peak 15:00, temp peak 17:00, HRV opposite to HR) + daily
offset + AR(1) hourly noise (phi = 0.6) + scenario effect x severity. Noise is scaled per astronaut (Ahmed 0.85,
Sara 1.3, Omar 1.0, others 0.8-1.3). Values are clipped to plausibility bounds (`DEFAULT_VALID_RANGES`), which are
not medical limits.

| Scenario (astronaut) | Severity profile | Effect at severity 1 |
|---|---|---|
| normal (Ahmed) | 0 | none |
| attention (Sara) | 0 until day 40, linear to 1 on day 60 | sleep -1.5 h, hr +8, hrv -10, activity -0.17, quality -0.18 |
| emergency (Omar) | 0 until day 55; 0.35 -> 1.0 over days 56-60 | hr +28, spo2 -4.5, sleep -2.9 h, temp +1.0, hrv -28 |
| stable x4, mild_sleep_drift, transient_fever (days 31-33), slow_hr_rise (AST-004..010) | see `severity()` | small |
