"""Missing / extreme / invalid readings on predict_risk: there must be no crash and always the agreed shape."""
import numpy as np
from physio_model import predict_risk

BIG = 1e12
cases = {
    "empty": {}, "none": None, "list": [1, 2], "string": "abc", "int": 5,
    "all None": {"hr_pct_dev": None, "hrv_pct_dev": None},
    "bad strings": {"hr_pct_dev": "bad", "spo2_pct_dev": "", "temp_delta_c": "NaN"},
    "nan/inf": {"hr_pct_dev": float("nan"), "hrv_pct_dev": float("inf"), "spo2_pct_dev": -float("inf")},
    "huge +": {c: BIG for c in ["hr_pct_dev", "hrv_pct_dev", "spo2_pct_dev", "resp_rate_pct_dev", "temp_delta_c",
                                 "sleep_hours_pct_dev", "stress_score_pct_dev", "activity_pct_dev"]},
    "huge -": {c: -BIG for c in ["hr_pct_dev", "hrv_pct_dev", "spo2_pct_dev", "resp_rate_pct_dev", "temp_delta_c",
                                  "sleep_hours_pct_dev", "stress_score_pct_dev", "activity_pct_dev"]},
    "numpy types": {"hr_pct_dev": np.float32(12), "hrv_pct_dev": np.int64(-20)},
    "bool": {"hr_pct_dev": True},
    "nested junk": {"hr_pct_dev": [1, 2], "hrv_pct_dev": {"a": 1}},
    "unknown keys": {"foo": 1, "bar": "x"},
    "_s suffix": {"hr_pct_dev_s": 25, "hrv_pct_dev_s": -25},
    "one value": {"hr_pct_dev": 30},
}
bad = 0
for k, v in cases.items():
    r = predict_risk(v)
    ok = (set(["risk_score", "level", "top_factors", "recommendation"]) <= set(r)
          and isinstance(r["risk_score"], int) and 0 <= r["risk_score"] <= 100
          and r["level"] in ["Normal", "Attention", "High Risk", "Emergency"] and "error" not in r)
    bad += (not ok)
    print(f"{'OK ' if ok else 'FAIL'} {k:14s} -> {r['risk_score']:3d} {r['level']:10s} anomaly={r.get('anomaly_score')} {('ERR: '+r['error']) if 'error' in r else ''}")
print("\nALL PASSED" if bad == 0 else f"\n{bad} FAILED")
