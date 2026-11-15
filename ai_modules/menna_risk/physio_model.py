"""
STELLAR - Anomaly Detection + Risk Prediction on Shimaa's data (main delivery).

Outputs: physio_model.joblib, physio_evaluation_report.json, physio_confusion_matrix.png,
          physio_risk_over_time.png, physio_feature_importance.png
and the function: predict_risk(vector: dict) -> {risk_score, level, top_factors, recommendation}

The model (Hybrid):
  1) Isolation Forest on normal behaviour (anomaly)
  2) Random Forest with 4 levels (Normal/Attention/High Risk/Emergency) on the body's deviations from the astronaut's baseline
  3) Transparent NEWS-inspired points (physio_risk.py)
  risk_score = 0.5 * RF_score + 0.5 * NEWS/anomaly_score

!! The labels are weak: set from the scenario definition + the day (WEAK_LABELS table below), not by an expert.
!! Shimaa's data has only one emergency astronaut (Omar), so there is no reliable evaluation of Emergency.

Run: python physio_model.py [path to features_all_astronauts.csv]
"""
import sys
import json
from pathlib import Path
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import classification_report, confusion_matrix, f1_score, recall_score

import physio_risk as pr

SEED = 42
HERE = Path(__file__).resolve().parent
CSV = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].endswith(".csv") else str(HERE / "features_all_astronauts.csv")
LEVELS = pr.LEVELS
CENTERS = np.array([12.5, 37.5, 62.5, 87.5])
DEV = pr.DEV
S = [c + "_s" for c in DEV]
EXTRA = ["hr_roll24h_std", "sleep_debt_7d"]
FEATURES = S + EXTRA + ["news_points"]
MODEL_PATH = str(HERE / "physio_model.joblib")   # v1.1: next to this file, works from any folder
# Feature names used in the API contract
NAME = {"hr_pct_dev": "hr", "hrv_pct_dev": "hrv", "spo2_pct_dev": "spo2", "resp_rate_pct_dev": "resp_rate",
        "temp_delta_c": "temp", "sleep_hours_pct_dev": "sleep_hours", "stress_score_pct_dev": "stress_score",
        "activity_pct_dev": "activity"}
TEMP_BASE = 36.7

RECOMMENDATIONS = {
    "Normal": "Physiological signs are within the astronaut's personal baseline. Continue the planned activity.",
    "Attention": "Mild deviation from personal baseline. Monitor the trend, check sleep/stress and consider reducing workload.",
    "High Risk": "Significant deviation from baseline. Reduce activity, review vitals manually and notify the flight surgeon.",
    "Emergency": "Critical deviation (vitals/sleep/stress). Stop activity, alert Ground Control and the medical team immediately.",
}


def weak_level(scenario, day):
    """Weak labels from the scenario definition (not from the feature values). Approximate."""
    if scenario == "emergency":
        return 3 if day >= 56 else 0
    if scenario == "attention":          # Sara: gradual decline
        return 1 if day >= 41 else 0     # contract: Sara = yellow (Attention) only
    if scenario == "slow_hr_rise":       # Tarek
        return 1 if day >= 45 else 0
    if scenario == "transient_fever":    # Youssef
        return 1 if 30 <= day <= 34 else 0
    return 0                             # normal / stable / mild_sleep_drift


def load():
    df = pd.read_csv(CSV, parse_dates=["timestamp"]).sort_values(["astronaut_id", "timestamp"])
    df = df[~df["is_calibration"]].copy()
    df = pr.smooth(df).dropna(subset=S).copy()
    df["y"] = [weak_level(s, d) for s, d in zip(df["scenario"], df["mission_day"])]
    df["news_points"] = [pr.news_points({c: r[c + "_s"] for c in DEV})[0] for _, r in df.iterrows()]
    return df.reset_index(drop=True)


# ----------------------------------------------------------------------------
def mask_missing(X, frac, rng):
    X = X.copy()
    X[rng.random(X.shape) < frac] = np.nan
    return X


def fit(train):
    rng = np.random.default_rng(SEED)
    imp = SimpleImputer(strategy="median")
    X = imp.fit_transform(train[FEATURES])
    y = train["y"].to_numpy()
    Xa = np.vstack([X, imp.transform(pd.DataFrame(mask_missing(train[FEATURES].to_numpy(float), 0.15, rng),
                                                  columns=FEATURES))])
    ya = np.concatenate([y, y])
    rf = RandomForestClassifier(n_estimators=200, min_samples_leaf=3, class_weight="balanced_subsample",
                                random_state=SEED, n_jobs=-1).fit(Xa, ya)
    Xn = X[y == 0][:, :len(S)]
    iso = IsolationForest(n_estimators=200, random_state=SEED, n_jobs=-1).fit(Xn)
    raw = -iso.score_samples(X[:, :len(S)])
    lo, hi = np.percentile(raw[y == 0], 50), np.percentile(raw, 99.5)
    med = train[S].median()
    mad = (train[S] - med).abs().median().replace(0, 1e-3)
    return dict(imputer=imp, rf=rf, iso=iso, lo=lo, hi=hi, features=FEATURES,
                baseline_median=med.to_dict(), baseline_mad=mad.to_dict(),
                feature_importance=dict(zip(FEATURES, rf.feature_importances_)))


def score(model, df):
    X = model["imputer"].transform(df[FEATURES])
    proba_raw = model["rf"].predict_proba(X)
    proba = np.zeros((len(df), 4))
    for i, c in enumerate(model["rf"].classes_):
        proba[:, int(c)] = proba_raw[:, i]
    rf_score = proba @ CENTERS
    raw = -model["iso"].score_samples(X[:, :len(S)])
    an = np.clip((raw - model["lo"]) / (model["hi"] - model["lo"] + 1e-9), 0, 1)
    news = 100.0 * np.minimum(df["news_points"].to_numpy(), pr.MAX_POINTS) / pr.MAX_POINTS
    news_score = 0.85 * news + 0.15 * 100 * an
    hybrid = np.clip(0.5 * rf_score + 0.5 * news_score, 0, 100)
    return rf_score, hybrid


def anomaly01(model, df):
    """anomaly_score from 0 to 1 (Isolation Forest). 0 = normal, 1 = very anomalous."""
    X = model["imputer"].transform(df[FEATURES])
    raw = -model["iso"].score_samples(X[:, :len(S)])
    return np.clip((raw - model["lo"]) / (model["hi"] - model["lo"] + 1e-9), 0, 1)


def lv(s):
    return np.digitize(s, [25, 50, 75])


def report(y, pred, name):
    labels = [0, 1, 2, 3]
    out = {
        "macro_f1": round(float(f1_score(y, pred, labels=labels, average="macro", zero_division=0)), 3),
        "per_level_recall": {LEVELS[i]: (round(float(r), 3) if (np.asarray(y) == i).any() else None)
                             for i, r in enumerate(recall_score(y, pred, labels=labels, average=None, zero_division=0))},
        "support": {LEVELS[i]: int((np.asarray(y) == i).sum()) for i in labels},
        "confusion_matrix": confusion_matrix(y, pred, labels=labels).tolist(),
    }
    print(f"\n===== {name} =====")
    print(classification_report(y, pred, labels=labels, target_names=LEVELS, zero_division=0))
    print("Confusion:\n", np.array(out["confusion_matrix"]))
    return out


def time_split(df, a=0.70, b=0.85):
    parts = {"train": [], "val": [], "test": []}
    for _, g in df.groupby("astronaut_id", sort=False):
        g = g.sort_values("timestamp")
        i, j = int(len(g) * a), int(len(g) * b)
        parts["train"].append(g.iloc[:i]); parts["val"].append(g.iloc[i:j]); parts["test"].append(g.iloc[j:])
    return {k: pd.concat(v) for k, v in parts.items()}


# ----------------------------------------------------------------------------
# predict_risk (the function the team calls)
# ----------------------------------------------------------------------------
_M = None


def load_model(path=MODEL_PATH):
    global _M
    _M = joblib.load(path)
    return _M


def _num(x):
    try:
        v = float(x)
        return v if np.isfinite(v) else np.nan
    except (TypeError, ValueError):
        return np.nan


def predict_risk(vector: dict) -> dict:
    """
    vector: the body's deviations from the astronaut's baseline (24 h moving average preferred), e.g.:
      {"hr_pct_dev": 8.0, "hrv_pct_dev": -12.0, "spo2_pct_dev": -0.3, "resp_rate_pct_dev": 4,
       "temp_delta_c": 0.1, "sleep_hours_pct_dev": -20, "stress_score_pct_dev": 60, "activity_pct_dev": -10}
    Accepts names ending in _s, missing/invalid/None values, and an empty dict. Never crashes.
    """
    global _M
    if _M is None:
        load_model()   # v1.1: a missing/broken model raises instead of returning "Normal"
    v = vector if isinstance(vector, dict) else {}

    def _pick(c):
        # v1.1: the model was trained on the 24 h rolling mean (<c>_s): prefer it, fall back to the
        # instantaneous value only when the average is missing (e.g. the first hours of data)
        s = _num(v.get(c + "_s"))
        return s if np.isfinite(s) else _num(v.get(c))

    dev = {c: _pick(c) for c in DEV}
    pts, contrib = pr.news_points(dev)
    row = {c + "_s": dev[c] for c in DEV}
    row["hr_roll24h_std"] = _num(v.get("hr_roll24h_std"))
    row["sleep_debt_7d"] = _num(v.get("sleep_debt_7d"))
    row["news_points"] = pts
    df = pd.DataFrame([row])[FEATURES]
    _, hy = score(_M, df)
    sc = float(hy[0])
    level = LEVELS[int(lv(sc))]
    # Top factors in the agreed shape: [{"feature": "hr", "change_pct": 12}]
    cand = []
    pts_map = {f: p for f, p, _ in contrib}
    for c in DEV:
        x = dev[c]
        if not np.isfinite(x):
            continue
        z = abs(x - _M["baseline_median"][c + "_s"]) / _M["baseline_mad"][c + "_s"]
        w = pts_map.get(c, 0) * 10 + _M["feature_importance"][c + "_s"] * min(z, 50)
        cand.append((c, w, x))
    cand.sort(key=lambda t: -t[1])
    top = []
    for c, w, x in cand[:3]:
        if w <= 0.05 and top:
            break
        name = NAME[c]
        pct = x / TEMP_BASE * 100 if c == "temp_delta_c" else x
        item = {"feature": name, "change_pct": round(float(pct), 1)}
        if c == "temp_delta_c":
            item["change_c"] = round(float(x), 2)
        top.append(item)
    if level == "Normal":
        top = [t for t in top if abs(t["change_pct"]) >= 5][:3]
    return {"risk_score": int(round(sc)), "level": level, "top_factors": top,
            "recommendation": RECOMMENDATIONS[level],
            "anomaly_score": round(float(anomaly01(_M, df)[0]), 3)}


# ----------------------------------------------------------------------------
def main():
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    df = load()
    print("rows:", len(df), "| weak-label share:\n", df["y"].value_counts(normalize=True).sort_index().round(4))

    rep = {"data": CSV, "rows": int(len(df)),
           "label_shares": df["y"].value_counts(normalize=True).sort_index().round(4).to_dict()}

    # (1) Time-based split
    sp = time_split(df)
    m = fit(sp["train"])
    for name in ("val", "test"):
        rf_s, hy_s = score(m, sp[name])
        y = sp[name]["y"].to_numpy()
        rep[f"time_split_{name}_RF_only"] = report(y, lv(rf_s), f"{name.upper()} (RF only)")
        rep[f"time_split_{name}_hybrid"] = report(y, lv(hy_s), f"{name.upper()} (Hybrid)")

    # (2) Leave-one-astronaut-out
    ys, rfp, hyp = [], [], []
    for a in df["astronaut_id"].unique():
        tr, te = df[df["astronaut_id"] != a], df[df["astronaut_id"] == a]
        ma = fit(tr)
        r, h = score(ma, te)
        ys.append(te["y"].to_numpy()); rfp.append(lv(r)); hyp.append(lv(h))
    ys, rfp, hyp = map(np.concatenate, (ys, rfp, hyp))
    rep["leave_one_astronaut_out_RF_only"] = report(ys, rfp, "LOAO (RF only)")
    rep["leave_one_astronaut_out_hybrid"] = report(ys, hyp, "LOAO (Hybrid)")

    # (3) Final model on all the data + save
    final = fit(df)
    joblib.dump(final, MODEL_PATH)
    load_model()

    # Plots
    cm = np.array(rep["leave_one_astronaut_out_hybrid"]["confusion_matrix"])
    fig, ax = plt.subplots(figsize=(5, 4.5))
    ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(4)); ax.set_yticks(range(4))
    ax.set_xticklabels(LEVELS, rotation=30, ha="right"); ax.set_yticklabels(LEVELS)
    for i in range(4):
        for j in range(4):
            ax.text(j, i, cm[i, j], ha="center", va="center")
    ax.set_xlabel("predicted"); ax.set_ylabel("weak label"); ax.set_title("Hybrid, leave-one-astronaut-out")
    fig.tight_layout(); fig.savefig(HERE / "physio_confusion_matrix.png", dpi=130); plt.close(fig)

    _, hy_all = score(final, df)
    df["risk"] = hy_all
    fig, axs = plt.subplots(3, 1, figsize=(9, 7), sharex=True)
    for ax, (a, nm) in zip(axs, [("AST-001", "Ahmed (normal)"), ("AST-002", "Sara (attention)"), ("AST-003", "Omar (emergency)")]):
        g = df[df["astronaut_id"] == a]
        ax.plot(g["mission_day"] + g["timestamp"].dt.hour / 24, g["risk"], lw=.8)
        for y_, c in [(25, "#e6b800"), (50, "#e67e22"), (75, "#c0392b")]:
            ax.axhline(y_, ls="--", lw=.6, color=c)
        ax.set_ylabel(nm); ax.set_ylim(0, 100)
    axs[-1].set_xlabel("mission day")
    fig.suptitle("Risk score over time (Shimaa data, synthetic)")
    fig.tight_layout(); fig.savefig(HERE / "physio_risk_over_time.png", dpi=130); plt.close(fig)

    imp = pd.Series(final["feature_importance"]).sort_values()
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.barh(imp.index, imp.values, color="#2c7fb8"); ax.set_title("RF feature importance")
    fig.tight_layout(); fig.savefig(HERE / "physio_feature_importance.png", dpi=130); plt.close(fig)

    rep["weak_label_rules"] = {
        "Omar (emergency)": "day>=56 -> Emergency, else Normal",
        "Sara (attention)": "day>=41 -> Attention (yellow, per the mission contract), else Normal",
        "Tarek (slow_hr_rise)": "day>=45 -> Attention", "Youssef (transient_fever)": "day 30-34 -> Attention",
        "others": "Normal"}
    rep["limitations"] = [
        "Simulated (synthetic) data from Shimaa, with no real labels: the labels are weak, built from the scenario definition and the day (approximate).",
        "Only one emergency astronaut (Omar), and all emergency days are in the last 5 days: in the time split they all fall in the test set, so the model never sees them in training; the same happens when Omar is left out in leave-one-out.",
        "There are no real High Risk examples in Shimaa's data (Sara is only yellow per the contract, and Omar goes straight to emergency), so the High Risk level comes from the NEWS points only.",
        "The hybrid relies on the NEWS points to cover cases the RF has not seen; their thresholds are approximate and not medically validated.",
        "These numbers show that the code works and the trend makes sense, not real clinical performance. This is a monitoring indicator, not a diagnosis.",
        "Days 1-14 (calibration) are not evaluated because they have no deviation.",
    ]
    with open(HERE / "physio_evaluation_report.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rep, fh, indent=2, ensure_ascii=False)

    print("\n===== predict_risk demo =====")
    demos = {
        "Ahmed (normal)": {"hr_pct_dev": 0.3, "hrv_pct_dev": 1.0, "spo2_pct_dev": 0.0, "resp_rate_pct_dev": 0.5,
                           "temp_delta_c": 0.0, "sleep_hours_pct_dev": -2, "stress_score_pct_dev": 3, "activity_pct_dev": 2},
        "Sara (late)": {"hr_pct_dev": 10.5, "hrv_pct_dev": -17.3, "spo2_pct_dev": -0.2, "resp_rate_pct_dev": 6,
                        "temp_delta_c": 0.1, "sleep_hours_pct_dev": -22, "stress_score_pct_dev": 92, "activity_pct_dev": -23},
        "Omar (emergency)": {"hr_pct_dev": 28.6, "hrv_pct_dev": -35.4, "spo2_pct_dev": -3.2, "resp_rate_pct_dev": 25,
                             "temp_delta_c": 0.66, "sleep_hours_pct_dev": -34.8, "stress_score_pct_dev": 150, "activity_pct_dev": -30},
        "Missing values": {"hr_pct_dev": 30, "hrv_pct_dev": None, "spo2_pct_dev": "bad"},
        "Empty": {},
    }
    for k, v in demos.items():
        print(k, "->", json.dumps(predict_risk(v), ensure_ascii=False))
    print("\nsaved:", MODEL_PATH, "+ report + 3 plots")


if __name__ == "__main__":
    main()
