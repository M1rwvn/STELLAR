"""AI 2 - Risk prediction (Menna), plugged into the backend.

Source: Menna's v1.1.0 (`physio_model.py`, `physio_risk.py`, `physio_model.joblib`), copied with code unchanged (comments translated to English)
into `ai_modules/menna_risk/`. Hybrid model: Random Forest (4 levels) + Isolation Forest + NEWS points,
trained on the 24 h rolling means of Shimaa's deviation features.

What this connector adds around her code:
  * the model is loaded with an allow-list (only numpy / scikit-learn objects may be created), so a
    replaced or tampered .joblib file cannot run code on the server;
  * single-reading predictions run on one thread (same results, no per-call thread start-up);
  * the backend pipeline puts the 24 h means (`<feature>_s`) in the vector, which her `predict_risk`
    prefers - the inputs she trained on.

To update after Menna retrains: copy her three files over `ai_modules/menna_risk/` and run `python -m pytest`.
"""
import sys
from pathlib import Path

import joblib.numpy_pickle as _jnp

MODEL_DIR = Path(__file__).resolve().with_name("menna_risk")
MODEL_FILE = MODEL_DIR / "physio_model.joblib"

_ALLOWED_PREFIXES = ("numpy", "sklearn.", "scipy.", "joblib.numpy_pickle")
_ALLOWED_BUILTINS = {("builtins", n) for n in ("dict", "list", "tuple", "set", "frozenset", "slice",
                                                "float", "int", "str", "bytes", "bytearray", "complex",
                                                "object")} | {("copyreg", "_reconstructor"),
                                                              ("collections", "OrderedDict")}


class _AllowListUnpickler(_jnp.NumpyUnpickler):
    def find_class(self, module, name):
        if (module, name) in _ALLOWED_BUILTINS or module.startswith(_ALLOWED_PREFIXES):
            return super().find_class(module, name)
        raise RuntimeError(f"Refusing to load {MODEL_FILE.name}: it asks for {module}.{name}")


def _safe_load(path: Path):
    original = _jnp.NumpyUnpickler
    _jnp.NumpyUnpickler = _AllowListUnpickler       # joblib.load uses this class internally
    try:
        return _jnp.load(path)
    finally:
        _jnp.NumpyUnpickler = original


if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))
import physio_model as _menna  # noqa: E402  (her module; imports physio_risk next to it)

_model = _safe_load(MODEL_FILE)
for _part in ("rf", "iso"):
    if hasattr(_model.get(_part), "n_jobs"):
        _model[_part].n_jobs = 1                       # one reading at a time: no thread pool per call
_menna._M = _model

MODEL_VERSION = "1.1.0"


def predict_risk(vector: dict) -> dict:
    """Menna's predict_risk; extra key `anomaly_score` (0-1) is kept for logging."""
    return _menna.predict_risk(vector)
