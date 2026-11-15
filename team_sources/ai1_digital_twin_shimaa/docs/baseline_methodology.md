# Baseline methodology

1. **Calibration window** = mission days 1-14 per astronaut. Rows after day 14 are filtered out *before* any
   statistic is computed (tests tamper with later data and verify the baseline is unchanged). Start/end timestamps
   and sample counts are stored in `profile["calibration"]`.
2. **Central value** = median (robust to outliers).
3. **Reference interval** (per-feature configurable in `config/baseline_config.json`):
   `median_mad` (default since v1.1, k = 2): median +/- k*1.4826*MAD; `iqr` (v1.0 default): [Q1, Q3];
   `mean_std`: mean +/- k*std. The center stays the median in all cases. Intervals are clamped to the plausibility
   bounds of the feature (e.g. a stress score cannot go below 0).
   *Why v1.1 changed the default:* Q1-Q3 contains only 50 % of a person's normal readings by definition, so a healthy
   astronaut looked "out of range" half the time (Ahmed: 47 % of SpO2 readings). median +/- 2 robust SD covers
   >= 91 % of every astronaut's calibration readings (worst metric of 10 astronauts) and flags 3 % of Ahmed's
   healthy readings. Centers - and therefore all % deviations - are unchanged. `robust_sigma` (IQR/1.349, 1.4826*MAD or std) is stored for scaling.
4. **Daily features** (sleep_hours, sleep_quality, exercise_score) use one value per day (14 samples), not 336 copies.
5. **Safety**: constant data -> `status="constant"`, low = high = center; fewer than `min_hourly_samples` (168) hourly
   or `min_daily_samples` (7) daily values -> `status="insufficient_data"` with null center/interval; no values ->
   `no_data`. Downstream code must check `status` before using a number.
6. **Deviation**: `(value - center)/|center| * 100`; positive = above baseline. Zero/missing baselines are skipped.
   Temperature is excluded from percentages (interval scale) - use `abs_deviation` / `scaled_deviation`.
7. **Interval vs. center**: the agreed profile `baseline` shows intervals for hr/hrv/spo2/temp and *center values*
   for sleep_hours/activity. The full distinction (center, low, high, sigma) is in `baseline_detail`.
8. The baseline is a *personal monitoring reference*, not a medical threshold. It is frozen after calibration (no
   rolling update) - see `limitations.md`. Scikit-learn is intentionally not used: medians and quantiles need no model.

`recovery_score` (engineering assumption): 100 * (0.4*sleep_quality + 0.3*min(sleep_hours/8,1) +
0.3*clip((hrv-20)/60,0,1)) using calibration medians.
