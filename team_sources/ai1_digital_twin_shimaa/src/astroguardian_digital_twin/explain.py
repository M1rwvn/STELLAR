"""Explanation text (task 11): the top reasons a reading differs from the PERSONAL baseline.

    explain_deviation({"hr": 72, "sleep_hours": 4.9}, get_baseline("AST-001"))
    -> {"reasons": [{"metric": "sleep_hours", "change_pct": -29.0,
                     "text": {"en": "Sleep is 29% below your normal (4.9 h vs 6.9 h)",
                              "ar": "النوم أقل من معدلك الطبيعي بنسبة 29% (4.9 ساعة بدل 6.9)"}}, ...],
        "summary": {...}, "recommendation": {...}}

Ranking: how many personal standard deviations (``scaled_deviation``) a metric moved in its
HARMFUL direction (HR up, HRV down, SpO2 down, sleep down, ...), capped at SIGMA_CAP. Beyond
the cap every change is extreme, so clinical priority decides (SpO2, temperature, heart rate
first). Moves in the healthy direction are never reported as a reason. Units follow the metric: % for most, percentage points for SpO2,
degC for temperature (a % of degC is meaningless).

These are monitoring indicators, not diagnoses; the risk level belongs to AI Member 2.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from .deviation import compute_deviation_detailed

# +1: higher is worse, -1: lower is worse
HARMFUL_DIRECTION = {"hr": 1, "hrv": -1, "spo2": -1, "resp_rate": 1, "temp": 1, "sleep_hours": -1,
                     "sleep_quality": -1, "activity": -1, "stress_score": 1, "exercise_score": -1}

MIN_SIGMAS = 1.0      # report a metric once it is >= 1 personal (robust) SD away, harmful side
MIN_PCT = 5.0         # ... and at least 5 % (or 1 point SpO2 / 0.3 degC) so tiny moves stay quiet
SIGMA_CAP = 5.0       # beyond 5 personal SD every change is extreme: order by CLINICAL_PRIORITY
CLINICAL_PRIORITY = ["spo2", "temp", "hr", "resp_rate", "hrv", "sleep_hours", "sleep_quality",
                     "stress_score", "activity", "exercise_score"]

LABELS = {
    "hr": ("Heart rate", "معدل ضربات القلب", "bpm", "نبضة/دقيقة"),
    "hrv": ("Heart-rate variability (HRV)", "تقلب نبضات القلب (HRV)", "ms", "مللي ثانية"),
    "spo2": ("Blood oxygen (SpO2)", "نسبة الأكسجين في الدم", "%", "%"),
    "resp_rate": ("Breathing rate", "معدل التنفس", "breaths/min", "نفس/دقيقة"),
    "temp": ("Body temperature", "درجة حرارة الجسم", "°C", "°م"),
    "sleep_hours": ("Sleep", "النوم", "h", "ساعة"),
    "sleep_quality": ("Sleep quality", "جودة النوم", "", ""),
    "activity": ("Activity", "النشاط", "", ""),
    "stress_score": ("Stress indicator", "مؤشر الإجهاد", "", ""),
    "exercise_score": ("Exercise-plan adherence", "الالتزام بخطة التمارين", "", ""),
}

RECOMMENDATIONS = {
    "sleep_hours": ("Increase recovery time and reduce training load today",
                    "زوّد وقت الراحة وقلّل حمل التمرين النهارده"),
    "sleep_quality": ("Improve sleep conditions (light, noise, schedule) tonight",
                      "حسّن ظروف النوم الليلة (الإضاءة، الضوضاء، المواعيد)"),
    "hr": ("Rest and re-check heart rate within the hour", "ارتاح واتابع النبض تاني خلال ساعة"),
    "hrv": ("Lower the workload; low HRV signals stress or poor recovery",
            "قلّل حمل الشغل؛ انخفاض الـ HRV معناه إجهاد أو تعافي ضعيف"),
    "spo2": ("Check oxygen supply and re-measure SpO2 at rest", "اتأكد من إمداد الأكسجين وقيس النسبة تاني وإنت مرتاح"),
    "resp_rate": ("Re-measure breathing rate at rest and check cabin air", "قيس معدل التنفس وإنت مرتاح واتأكد من هوا الكابينة"),
    "temp": ("Check for fever and inform the flight surgeon", "اتأكد من وجود حرارة وبلّغ طبيب المهمة"),
    "activity": ("Follow the exercise countermeasure plan", "التزم بخطة التمارين المضادة لانعدام الجاذبية"),
    "stress_score": ("Plan a recovery break", "خد فترة راحة للتعافي"),
    "exercise_score": ("Get back to the training plan", "ارجع لخطة التمرين"),
}
ALL_NORMAL = ("All measured values are within your personal normal pattern",
              "كل القياسات في حدود النمط الطبيعي بتاعك")
KEEP_ROUTINE = ("Keep your current routine", "كمّل على روتينك الحالي")


def _fmt(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".") if abs(x) < 100 else f"{x:.0f}"


def _sentence(metric: str, info: Mapping[str, Any]) -> dict[str, str]:
    en_name, ar_name, en_unit, ar_unit = LABELS[metric]
    value, center = info["value"], info["center"]
    above = value > center
    en_dir, ar_dir = ("above", "أعلى") if above else ("below", "أقل")
    if metric == "temp":
        diff = abs(value - center)
        return {"en": f"{en_name} is {_fmt(diff)} °C {en_dir} your normal ({_fmt(value)} vs {_fmt(center)} °C)",
                "ar": f"{ar_name} {ar_dir} من معدلك الطبيعي بـ {_fmt(diff)} درجة ({_fmt(value)} بدل {_fmt(center)})"}
    if metric == "spo2":
        diff = abs(value - center)
        return {"en": f"{en_name} is {_fmt(diff)} points {en_dir} your normal ({_fmt(value)}% vs {_fmt(center)}%)",
                "ar": f"{ar_name} {ar_dir} من معدلك الطبيعي بـ {_fmt(diff)} نقطة ({_fmt(value)}% بدل {_fmt(center)}%)"}
    pct = abs(info["pct_deviation"])
    en_u = f" {en_unit}" if en_unit else ""
    ar_u = f" {ar_unit}" if ar_unit else ""
    return {"en": f"{en_name} is {pct:.0f}% {en_dir} your normal ({_fmt(value)}{en_u} vs {_fmt(center)}{en_u})",
            "ar": f"{ar_name} {ar_dir} من معدلك الطبيعي بنسبة {pct:.0f}% ({_fmt(value)}{ar_u} بدل {_fmt(center)})"}


def _harmful_sigmas(metric: str, info: Mapping[str, Any]) -> Optional[float]:
    sign = HARMFUL_DIRECTION.get(metric)
    if sign is None or info.get("scaled_deviation") is None:
        return None
    return sign * info["scaled_deviation"]


def _big_enough(metric: str, info: Mapping[str, Any]) -> bool:
    if metric == "temp":
        return abs(info["abs_deviation"]) >= 0.3
    if metric == "spo2":
        return abs(info["abs_deviation"]) >= 1.0
    pct = info.get("pct_deviation")
    return pct is not None and abs(pct) >= MIN_PCT


def explain_deviation(reading: dict, baseline: dict, top_n: int = 3) -> dict:
    """Top ``top_n`` harmful deviations as sentences (English + Arabic) + one recommendation."""
    detailed = compute_deviation_detailed(reading, baseline)
    candidates = []
    for metric, info in detailed["metrics"].items():
        sig = _harmful_sigmas(metric, info)
        if sig is not None and sig >= MIN_SIGMAS and _big_enough(metric, info) and metric in LABELS:
            candidates.append((sig, metric, info))
    candidates.sort(key=lambda c: (-min(c[0], SIGMA_CAP), CLINICAL_PRIORITY.index(c[1])))

    reasons = []
    for sig, metric, info in candidates[:top_n]:
        reasons.append({
            "metric": metric,
            "change_pct": info["pct_deviation"],            # None for temp (see abs_change)
            "abs_change": info["abs_deviation"],
            "sigmas": round(sig, 2),
            "text": _sentence(metric, info),
        })
    if reasons:
        top = reasons[0]["metric"]
        summary = {"en": "; ".join(r["text"]["en"] for r in reasons),
                   "ar": "؛ ".join(r["text"]["ar"] for r in reasons)}
        rec_en, rec_ar = RECOMMENDATIONS[top]
    else:
        summary = {"en": ALL_NORMAL[0], "ar": ALL_NORMAL[1]}
        rec_en, rec_ar = KEEP_ROUTINE
    return {"astronaut_id": detailed["astronaut_id"], "reasons": reasons, "summary": summary,
            "recommendation": {"en": rec_en, "ar": rec_ar},
            "note": "Monitoring indicator relative to a personal baseline, not a diagnosis."}
