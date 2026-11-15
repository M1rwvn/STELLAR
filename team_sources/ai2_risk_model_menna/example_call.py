from physio_model import predict_risk

# Attention example (Sara, late mission)
print(predict_risk({
    "hr_pct_dev": 10.5, "hrv_pct_dev": -17.3, "spo2_pct_dev": -0.2, "resp_rate_pct_dev": 6,
    "temp_delta_c": 0.1, "sleep_hours_pct_dev": -22, "stress_score_pct_dev": 92, "activity_pct_dev": -23,
}))

# Emergency example (Omar)
print(predict_risk({
    "hr_pct_dev": 28.6, "hrv_pct_dev": -35.4, "spo2_pct_dev": -3.2, "resp_rate_pct_dev": 25,
    "temp_delta_c": 0.66, "sleep_hours_pct_dev": -34.8, "stress_score_pct_dev": 150, "activity_pct_dev": -30,
}))

# Missing / bad values never crash
print(predict_risk({"hr_pct_dev": 30, "hrv_pct_dev": None, "spo2_pct_dev": "bad"}))
print(predict_risk({}))
