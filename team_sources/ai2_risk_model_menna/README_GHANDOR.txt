AstroGuardian - predict_risk (Menna)  v1.1.0   (see CHANGELOG.md)

FILES (keep in ONE folder): physio_model.py, physio_risk.py, physio_model.joblib
  example_call.py   -> run it to see the output
  test_robustness.py, test_v11.py -> checks (python test_robustness.py ; python -m pytest test_v11.py)
  features_all_astronauts.csv -> only needed to retrain

SETUP:  pip install numpy pandas scikit-learn==1.9.1 joblib   (matplotlib + pytest only to retrain / test)
RUN:    python example_call.py      (works from ANY folder since v1.1)

USAGE:
  from physio_model import predict_risk
  predict_risk({"hr_pct_dev_s": 10.5, "sleep_hours_pct_dev_s": -22, ..., "hr_roll24h_std": 3.1, "sleep_debt_7d": 9.4})

INPUT : deviations from the astronaut baseline (Shimaa). Give the 24 h rolling means as <name>_s
        (what the model was trained on); plain <name> is used only when <name>_s is missing.
        names: hr_pct_dev, hrv_pct_dev, spo2_pct_dev, resp_rate_pct_dev, temp_delta_c,
               sleep_hours_pct_dev, stress_score_pct_dev, activity_pct_dev  (+ hr_roll24h_std, sleep_debt_7d)
        Missing/None/bad values are OK. A missing/broken MODEL raises (never a silent "Normal").
OUTPUT: {risk_score, level, top_factors:[{feature, change_pct}], recommendation, anomaly_score}

RETRAIN: python physio_model.py   (~25 s, deterministic, seed 42)
NOTE: data is synthetic and labels are weak; do not present numbers as clinical accuracy.
