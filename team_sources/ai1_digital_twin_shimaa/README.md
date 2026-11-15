# AstroGuardian - Digital Twin module (AI Member 1)

Personal-baseline health monitoring for **synthetic** astronaut wearable data. All data are fictional and
synthetic; nothing here is medically validated and deviations are *monitoring indicators, not diagnoses*.

What it does: generates 10 astronauts x 60 days of hourly data (seed 42) -> cleans/validates -> causal features ->
per-astronaut baseline from mission days 1-14 (median + reference interval) -> profile JSON ->
`get_baseline()` / `compute_deviation()` -> demo datasets (Ahmed, Sara, Omar) + replay script.
It does **not** include suit sensors, vision, backend, security, app, dashboard or the risk model.

## Setup (Python 3.11+)
```bash
cd astroguardian_digital_twin
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt                       # numpy, pandas, pytest
pip install -e .                                      # optional: makes the package importable everywhere
export PYTHONPATH=src                                 # alternative to `pip install -e .` (Windows: set PYTHONPATH=src)
```
Optional: `pip install pyarrow` (also writes a Parquet features file), `pip install jupyter nbformat` (notebook).

## Run
```bash
python -m astroguardian_digital_twin.demo_scenarios --output-root .   # data/raw, data/processed, data/demo, outputs/profiles, outputs/demo_report.json
python -m pytest -q                                                   # run all tests
python -m astroguardian_digital_twin.replay --scenario omar --start-day 56 --limit 5   # local replay (no network)
python -m astroguardian_digital_twin.replay --scenario all --output replay.jsonl
python -m astroguardian_digital_twin.replay --scenario sara --post-url http://127.0.0.1:8000/health-data --username device --password astro123 --verbose  # OPTIONAL HTTP
jupyter notebook notebooks/digital_twin_analysis.ipynb
```

## Use from Python
```python
from astroguardian_digital_twin import get_baseline, compute_deviation, compute_deviation_detailed
baseline = get_baseline("AST-001")                       # raises UnknownAstronautError for unknown IDs
compute_deviation({"hr": 72, "sleep_hours": 4.9}, baseline)   # {"hr": +x.x, "sleep_hours": -y.y}  (% vs personal baseline)
compute_deviation_detailed({"hr": 72, "temp": 37.5}, baseline)  # + interval position, abs/scaled deviation, skipped reasons
```

## New in v1.1 (see CHANGELOG.md)
```python
from astroguardian_digital_twin import online_features, explain_deviation
online_features(last_7_days_of_readings, get_baseline("AST-003"))   # same columns as the training table
explain_deviation({"hr": 72, "sleep_hours": 4.9}, get_baseline("AST-001"))["reasons"][0]["text"]
# {'en': 'Sleep is 29% below your normal (4.9 h vs 6.9 h)', 'ar': 'النوم أقل من معدلك الطبيعي بنسبة 29% (4.9 ساعة بدل 6.9)'}
```
Replay over HTTP now logs in by itself: `--post-url http://127.0.0.1:8000/health-data --username device --password ... --verbose`.
Presentation charts: `outputs/figures/*.png` (made by the notebook).

## Integration with the team
* **Ghandor (backend)**: `from astroguardian_digital_twin import get_baseline, compute_deviation`; map
  `UnknownAstronautError` to 404. Serve `GET /astronaut-profile/{id}` from `get_baseline` (+ `mission_day`, `status`
  computed by the backend). Set `ASTROGUARDIAN_PROFILE_DIR` if profiles live elsewhere. Review `docs/interface_contract.md` (open questions).
* **Menna (AI 2)**: use `data/processed/features_all_astronauts.csv` (all 10 astronauts) and `data/demo/*.csv`. Columns are in
  `docs/data_dictionary.md`. Do **not** use the `scenario` column as a feature. Use `compute_deviation_detailed` for richer inputs.
* **Mariam (AI 3)**: `compute_deviation(wearable, baseline)` fits `build_health_vector(wearable, suit, vision, baseline)`; field names are the canonical ones.
* **Replay**: emits `POST /health-data` payloads (wearable fields only) in chronological order.

## Layout
`src/astroguardian_digital_twin/` (data_generator, data_cleaning, feature_engineering, baseline, deviation, profiles,
demo_scenarios, replay) - `tests/` (pytest; also `test_replay.py`, added beyond the requested list) - `config/baseline_config.json` -
`docs/` - `data/` - `outputs/`. Config is read from `config/baseline_config.json` (defaults in `baseline.py`).
Scikit-learn is not used: medians/quantiles need no ML model.

## Reproducibility
Fixed seed 42 (`numpy.random.default_rng([seed, astronaut_index])`); tests check that the same seed yields identical
data and byte-identical demo files. Read `docs/limitations.md` before presenting.
