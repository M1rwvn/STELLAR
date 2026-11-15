"""AI integration layer: the only place the backend touches the AI team's code.

The backend always calls these four functions (signatures agreed day 1):

    get_baseline(astronaut_id) -> dict                                    # AI 1 Shimaa
    compute_deviation(reading, baseline) -> dict                          # AI 1 Shimaa
    build_health_vector(wearable, suit, vision, baseline) -> dict          # AI 3 Mariam
    predict_risk(vector) -> dict                                          # AI 2 Menna

Optional AI 1 extras (v1.1), used when the module provides them:

    history_features(history, baseline) -> dict   # training-identical rolling/sleep/stress features
    explain(reading, baseline) -> dict | None     # top reasons as plain-English sentences

Each one is taken from the team's real module in `ai_modules/` when it exists
(AI_MODE=auto|real), otherwise from `app/ai/stubs/`. If a real module raises
at runtime, the stub answers instead and the error is logged, so a bug in one
model never takes the demo down.
"""
import importlib
import logging
from types import ModuleType

from app.ai.stubs import digital_twin as stub_twin
from app.ai.stubs import fusion as stub_fusion
from app.ai.stubs import risk as stub_risk
from app.config import get_settings

log = logging.getLogger("stellar.ai")

_VALID_LEVELS = {"Normal", "Attention", "High Risk", "Emergency"}


def _load(module_name: str, stub: ModuleType, attrs: list[str]) -> tuple[ModuleType, str]:
    mode = get_settings().ai_mode.lower()
    if mode == "stub":
        return stub, "stub"
    try:
        module = importlib.import_module(f"ai_modules.{module_name}")
        missing = [a for a in attrs if not hasattr(module, a)]
        if missing:
            raise AttributeError(f"ai_modules.{module_name} is missing {missing}")
        log.info("AI: using real module ai_modules.%s", module_name)
        return module, "real"
    except ModuleNotFoundError as exc:
        if mode == "real":
            raise
        if exc.name not in (f"ai_modules.{module_name}", "ai_modules"):
            # The module exists but one of its own imports is missing
            log.warning("AI: ai_modules.%s failed to import (%s) - using stub", module_name, exc)
        return stub, "stub"
    except Exception as exc:  # noqa: BLE001 - never let a broken model kill startup
        if mode == "real":
            raise
        log.warning("AI: ai_modules.%s failed to load (%s) - using stub", module_name, exc)
        return stub, "stub"


_twin, _twin_src = _load("digital_twin", stub_twin, ["get_baseline", "compute_deviation"])
_fusion, _fusion_src = _load("fusion", stub_fusion, ["build_health_vector"])
_risk, _risk_src = _load("risk", stub_risk, ["predict_risk"])


def ai_status() -> dict:
    return {"digital_twin": _twin_src, "fusion": _fusion_src, "risk": _risk_src}


def _safe(real_fn, stub_fn, name: str, *args):
    if real_fn is stub_fn:
        return stub_fn(*args)
    try:
        return real_fn(*args)
    except Exception:  # noqa: BLE001
        log.exception("AI: %s raised - falling back to stub", name)
        return stub_fn(*args)


def get_baseline(astronaut_id: str) -> dict:
    result = _safe(_twin.get_baseline, stub_twin.get_baseline, "get_baseline", astronaut_id)
    # Accept either the full profile or just the baseline dict
    if "baseline" not in result:
        result = {"astronaut_id": astronaut_id, "baseline": result}
    return result


def compute_deviation(reading: dict, baseline: dict) -> dict:
    return _safe(_twin.compute_deviation, stub_twin.compute_deviation, "compute_deviation",
                 reading, baseline)


def build_health_vector(wearable: dict, suit: dict, vision: dict, baseline: dict) -> dict:
    return _safe(_fusion.build_health_vector, stub_fusion.build_health_vector,
                 "build_health_vector", wearable, suit, vision, baseline)


def predict_risk(vector: dict) -> dict:
    result = _safe(_risk.predict_risk, stub_risk.predict_risk, "predict_risk", vector)
    return _normalize_risk(result)


_BANDS = {"Normal": (0, 24), "Attention": (25, 49), "High Risk": (50, 74), "Emergency": (75, 100)}


def _normalize_risk(result: dict) -> dict:
    """Make sure whatever the model returns matches the contract."""
    score = int(round(max(0.0, min(100.0, float(result.get("risk_score", 0))))))
    level = result.get("level")
    if level not in _VALID_LEVELS:
        level = stub_risk.level_for(score)
    else:
        # The model decides the level on the exact score (49.9 -> Attention). Keep the shown whole
        # number inside that level's band, so the screen never says "50 - Attention".
        lo, hi = _BANDS[level]
        score = max(lo, min(hi, score))
    factors = []
    for f in (result.get("top_factors") or [])[:3]:
        if isinstance(f, dict) and "feature" in f:
            factors.append({"feature": str(f["feature"]),
                            "change_pct": round(float(f.get("change_pct", 0) or 0), 1)})
    return {"risk_score": score, "level": level, "top_factors": factors,
            "recommendation": str(result.get("recommendation") or "")}


def history_features(history: list[dict], baseline: dict) -> dict:
    """AI 1's runtime features for the newest reading in `history` (last 7 days).

    Same names and formulas as the training table (`features_all_astronauts.csv`), so a
    model trained on that file sees identical inputs at runtime. Empty dict if AI 1 does
    not provide `online_features` or the profile lacks its reference (pre-1.1 profiles).
    """
    fn = getattr(_twin, "online_features", None)
    if fn is None or not baseline.get("online_reference"):
        return {}
    try:
        return fn(history, baseline)
    except Exception:  # noqa: BLE001
        log.exception("AI: online_features raised - continuing without history features")
        return {}


def explain(reading: dict, baseline: dict) -> dict | None:
    """AI 1's explanation sentences for one reading, or None (the API shows the English text)."""
    fn = getattr(_twin, "explain_deviation", None)
    if fn is None:
        return None
    try:
        return fn(reading, baseline)
    except Exception:  # noqa: BLE001
        log.exception("AI: explain_deviation raised - no explanation for this reading")
        return None
