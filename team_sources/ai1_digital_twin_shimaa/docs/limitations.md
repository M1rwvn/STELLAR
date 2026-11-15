# Limitations (read before presenting)

* **All data are synthetic** (fictional astronauts, fixed seed 42). Nothing here is medically validated and
  nothing establishes real-world diagnostic accuracy. The method *is applicable* to real data, but that has not
  been tested.
* **Scenario design values** (base levels, circadian amplitudes, noise, deterioration sizes) were chosen by us.
  They are not reference intervals. Real data will be messier (motion artifacts, sensor dropout, drift).
* **The scenarios are easy by construction**: Omar's final-five-day changes are large; Sara's change is smooth.
  Detection of these patterns says little about performance on subtle or mixed real-world cases.
* **A personal baseline is only as good as the calibration window.** Days 1-14 may not be "healthy" in reality
  (adaptation to spaceflight, jet-lag-like circadian shifts). The baseline is frozen after day 14 (no rolling
  update), so slow long-term drift of the true normal is not modelled.
* **Pooled-hour baseline.** The baseline pools all hours of day, so the normal circadian swing (about +/-3 bpm in
  the synthetic data, ~+/-5 %) appears as deviation of single hourly readings. Daily means remove most of it.
  An hour-of-day baseline is a possible extension.
* **Percent deviation is not available for temperature** (degC is an interval scale); use `abs_deviation`.
  Percent changes of SpO2 look small (a drop from 97.5 to 93 is about -4.6 %) - the *interval position* and
  `scaled_deviation` in `compute_deviation_detailed` are more informative for such bounded signals.
* **Derived indicators are engineering assumptions**: `stress_score`, `sleep_debt_7d` (assumed 8 h need) and
  `recovery_score` (formula in `profiles.py`) are not validated clinical measures.
* **Daily sleep values** are repeated on all 24 hourly rows and treated as known from 00:00 of that day (simplification).
* **Monitoring indicators, not diagnoses.** Deviation outputs must not be shown as medical conclusions.
  Risk classification belongs to AI Member 2's component.
* **Omar's onset is a ramp, not a step.** The task file describes the last five days with HR 95+, SpO2 93, sleep 4 h,
  temp 37.8. The generator reaches those values on day 60, starting at 35 % on day 56. This makes an early warning
  visible (day 56) but differs from the literal wording; the team should confirm it.
* **Runtime features need history.** `online_features` equals the training features only when the backend has the
  last 7 days of hourly readings; with less history the rolling values are `null` (never guessed).
* The `scenario` column in the CSV files is the **ground-truth label** of the generator. Do not use it as a model
  feature (leakage); use it only to evaluate.
