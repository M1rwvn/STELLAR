AstroGuardian - Risk Model (Menna)

1) pip install numpy pandas scikit-learn matplotlib joblib
2) python physio_model.py        -> trains, evaluates, saves physio_model.joblib + report + plots, prints demo
3) python test_robustness.py     -> 16 missing/extreme/bad input tests (should print ALL PASSED)

Use in code:
   from physio_model import predict_risk
   predict_risk({"hr_pct_dev": 10, "sleep_hours_pct_dev": -22, "stress_score_pct_dev": 90})
   -> {risk_score, level, top_factors:[{feature, change_pct}], recommendation, anomaly_score}

Files must stay in the same folder.
