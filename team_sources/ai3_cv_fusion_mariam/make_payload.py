"""Build the POST /health-data JSON (contract, Appendix 2)."""

import json
from datetime import datetime, timezone

from data_fusion import build_health_vector_with_meta
from schema import WEARABLE_KEYS, SUIT_KEYS, VISION_KEYS


def build_payload(wearable, suit, vision, baseline, astronaut_id="AST-001", timestamp=None):
    """Return (payload, vector, meta).

    payload: exactly astronaut_id, timestamp, wearable (8), suit (4), vision (3).
    vector:  full Core vector (for Menna). meta: which values were estimated.
    """
    vector, meta = build_health_vector_with_meta(wearable, suit, vision, baseline)
    ts = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "astronaut_id": astronaut_id,
        "timestamp": ts,
        "wearable": {k: vector[k] for k in WEARABLE_KEYS},
        "suit": {k: vector[k] for k in SUIT_KEYS},
        "vision": {k: vector[k] for k in VISION_KEYS},
    }
    return payload, vector, meta


def save_json(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
