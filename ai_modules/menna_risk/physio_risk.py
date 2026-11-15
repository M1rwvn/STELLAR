"""
STELLAR - Physiological Risk (on Shimaa's data) + combination with the suit risk.

The idea:
  * Shimaa's data has no risk labels and only one emergency astronaut (Omar) -> we cannot train a
    4-level Random Forest and evaluate it properly. So we use a NEWS-inspired approach (mission plan):
      1) Transparent points from each metric's deviation from the astronaut's personal baseline.
      2) Isolation Forest trained on normal behaviour (independent anomaly detection).
  * Evaluation = a sanity check on the scenarios (Ahmed stable / Sara declining / Omar emergency), not real accuracy.

Run:  python physio_risk.py  (put features_all_astronauts.csv in the same folder or pass its path)
"""
import sys
import json
import numpy as np
import pandas as pd

CSV = sys.argv[1] if len(sys.argv) > 1 else "features_all_astronauts.csv"
LEVELS = ["Normal", "Attention", "High Risk", "Emergency"]
DEV = ["hr_pct_dev", "hrv_pct_dev", "spo2_pct_dev", "resp_rate_pct_dev", "temp_delta_c",
       "sleep_hours_pct_dev", "stress_score_pct_dev", "activity_pct_dev"]

# (feature, risk direction, point thresholds 1/2/3)  -- approximate thresholds, not medically validated
RULES = {
    "hr_pct_dev":          (+1, (10, 20, 30)),
    "hrv_pct_dev":         (-1, (10, 20, 30)),
    "spo2_pct_dev":        (-1, (1, 2, 3)),
    "resp_rate_pct_dev":   (+1, (10, 20, 30)),
    "temp_delta_c":        (+1, (0.4, 0.8, 1.2)),
    "sleep_hours_pct_dev": (-1, (15, 30, 45)),
    # v1.1: max 2 points (was 3). Shimaa's stress_score is computed from HR and HRV, which are already
    # scored above, so a third stress point let one derived signal dominate: Sara (expected yellow)
    # reached High Risk on day 60 only because of it. Keeping the 30 % / 60 % points preserves the
    # early warning (Sara yellow from day 42). Compared with removing or capping at 1 point, this
    # keeps emergency sensitivity (LOAO: 87 % vs 88 % in v1.0) - see CHANGELOG.md.
    "stress_score_pct_dev": (+1, (30, 60, float("inf"))),
}
MAX_POINTS = 12.0   # 12 points or more -> NEWS score = 100


def news_points(dev: dict):
    """dev: dict of feature name -> deviation value. Missing values are ignored (no crash)."""
    pts, contrib = 0, []
    for f, (sign, th) in RULES.items():
        v = dev.get(f)
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(v):
            continue
        s = sign * v
        p = int(s >= th[0]) + int(s >= th[1]) + int(s >= th[2])
        if p:
            pts += p
            contrib.append((f, p, round(v, 2)))
    return pts, sorted(contrib, key=lambda x: -x[1])


def to_level(score):
    return LEVELS[int(np.digitize(score, [25, 50, 75]))]


def physio_risk(dev: dict, anomaly01: float = 0.0):
    pts, contrib = news_points(dev)
    news = 100.0 * min(pts, MAX_POINTS) / MAX_POINTS
    score = float(np.clip(0.85 * news + 0.15 * 100 * anomaly01, 0, 100))
    return {"risk_score": round(score), "level": to_level(score),
            "news_points": pts, "top_factors": [{"feature": f, "points": p, "value": v} for f, p, v in contrib[:3]]}


def smooth(df, window=24):
    """24 h moving average per astronaut (reduces hourly noise)."""
    out = df.copy()
    for c in DEV:
        out[c + "_s"] = out.groupby("astronaut_id")[c].transform(lambda s: s.rolling(window, min_periods=6).mean())
    return out


def main():
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.ensemble import IsolationForest
    from sklearn.metrics import roc_auc_score
    df = pd.read_csv(CSV, parse_dates=["timestamp"]).sort_values(["astronaut_id", "timestamp"])
    df = df[~df["is_calibration"]].copy()        # first 14 days = calibration (no deviation)
    df = smooth(df)
    S = [c + "_s" for c in DEV]
    df = df.dropna(subset=S)

    # Isolation Forest on normal behaviour: the stable astronauts + the early period (days 15-30) for everyone
    normal_mask = df["scenario"].isin(["normal", "stable"]) | (df["mission_day"] <= 30)
    iso = IsolationForest(n_estimators=200, random_state=42, n_jobs=-1).fit(df.loc[normal_mask, S])
    raw = -iso.score_samples(df[S])
    lo, hi = np.percentile(raw[normal_mask.values], 50), np.percentile(raw, 99.5)
    df["anom01"] = np.clip((raw - lo) / (hi - lo + 1e-9), 0, 1)

    scores, levels = [], []
    for _, r in df.iterrows():
        res = physio_risk({c: r[c + "_s"] for c in DEV}, r["anom01"])
        scores.append(res["risk_score"]); levels.append(res["level"])
    df["risk_score"], df["level"] = scores, levels

    # ---- sanity check on the scenarios (weak labels from the scenario definition + day, not from the features) ----
    def phase_label(r):
        if r["scenario"] == "emergency":
            return int(r["mission_day"] >= 56)           # last 5 days
        if r["scenario"] == "attention":
            return int(r["mission_day"] >= 48)           # the most severe blocks
        return 0
    df["weak_label"] = df.apply(phase_label, axis=1)

    rep = {"note": "Sanity check only: simulated data + weak labels from the scenario; not real accuracy.",
           "mean_score_by_scenario": df.groupby("scenario")["risk_score"].mean().round(1).to_dict(),
           "level_share_by_scenario": (df.groupby("scenario")["level"].value_counts(normalize=True)
                                       .unstack(fill_value=0).round(3).to_dict("index"))}
    sub = df[df["scenario"].isin(["emergency", "stable", "normal"])]
    rep["AUC_omar_emergency_days_vs_stable"] = round(float(
        roc_auc_score(sub["weak_label"], sub["risk_score"])), 3)
    sub2 = df[df["scenario"].isin(["attention", "stable", "normal"])]
    rep["AUC_sara_late_days_vs_stable"] = round(float(
        roc_auc_score(sub2["weak_label"], sub2["risk_score"])), 3)
    stable = df[df["scenario"].isin(["stable", "normal"])]
    rep["false_alert_rate_stable_astronauts(score>=50)"] = round(float((stable["risk_score"] >= 50).mean()), 4)
    rep["limitations"] = [
        "Shimaa's data has no real risk labels; the weak labels are built from the scenario definition.",
        "Only one emergency astronaut (Omar) -> recall per level cannot be evaluated reliably.",
        "The NEWS thresholds are approximate and not medically validated, and the 12-point scale was chosen by hand.",
        "This is a monitoring indicator, not a medical diagnosis.",
    ]
    json.dump(rep, open("physio_report.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(json.dumps(rep, indent=2, ensure_ascii=False))

    fig, ax = plt.subplots(figsize=(9, 4))
    for a, name in [("AST-001", "Ahmed (normal)"), ("AST-002", "Sara (attention)"), ("AST-003", "Omar (emergency)")]:
        g = df[df["astronaut_id"] == a]
        ax.plot(g["mission_day"], g["risk_score"], label=name, lw=1)
    for y in (25, 50, 75):
        ax.axhline(y, ls="--", lw=.6, color="gray")
    ax.set_xlabel("mission day"); ax.set_ylabel("physio risk score"); ax.legend()
    ax.set_title("Physiological risk over mission (data: Shimaa, synthetic)")
    fig.tight_layout(); fig.savefig("physio_risk_over_time.png", dpi=130)


if __name__ == "__main__":
    main()
