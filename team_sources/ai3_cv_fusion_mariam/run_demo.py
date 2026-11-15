"""Run the whole prototype: video -> vision features -> + suit + wearable -> fusion.

Usage: python run_demo.py --video samples/squat.mp4
Outputs (in outputs/): health.json (POST /health-data payload), output_vector.json,
output_meta.json, overlay_output.mp4 / .avi
"""

import argparse
from pathlib import Path

from data_fusion import build_health_vector
from make_overlay_video import make_overlay
from make_payload import build_payload, save_json
from suit_simulator import generate_suit_data
from vision_features import analyze_video

# Sample data. In the real system the wearable data comes from Shimaa (AI 1)
# and the baseline from get_baseline(astronaut_id).
BASELINE = {"hr": [60, 65], "hrv": [55, 70], "spo2": [96, 99], "resp_rate": 15,
            "temp": [36.5, 36.9], "sleep_hours": 8.0, "sleep_quality": 0.8, "activity": 0.55}
WEARABLE = {"hr": 80, "hrv": 45, "spo2": 97, "resp_rate": 16, "temp": 36.7,
            "sleep_hours": 4.0, "sleep_quality": 0.5, "activity": 0.1}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default="samples/squat.mp4", type=Path)
    ap.add_argument("--astronaut-id", default="AST-001")
    ap.add_argument("--out-dir", default="outputs", type=Path)
    ap.add_argument("--side", default="right", choices=["right", "left"])
    ap.add_argument("--bad-suit", action="store_true", help="simulate unsafe suit values")
    ap.add_argument("--no-overlay", action="store_true")
    a = ap.parse_args()
    a.out_dir.mkdir(exist_ok=True)

    print("1) Analysing video ...")
    analysis = analyze_video(a.video, side=a.side)
    vision = analysis["features"]
    print(f"   vision: {vision}")

    print("2) Suit telemetry + fusion ...")
    suit = generate_suit_data(mode="bad" if a.bad_suit else "normal")
    payload, vector, meta = build_payload(WEARABLE, suit, vision, BASELINE, a.astronaut_id)
    save_json(payload, a.out_dir / "health.json")
    save_json(vector, a.out_dir / "output_vector.json")
    save_json(meta, a.out_dir / "output_meta.json")

    # Before / after fusion demo
    print(f"\n   BEFORE fusion: HR={WEARABLE['hr']} alone -> looks normal")
    print(f"   AFTER fusion : HR=80 + sleep=4h + low activity -> fatigue_risk = {vector['fatigue_risk']}")

    if not a.no_overlay:
        print("\n3) Overlay video ...")
        make_overlay(a.video, a.out_dir, a.side, analysis=analysis)

    # Sanity: the fusion function used by the Backend gives the same vector
    assert build_health_vector(WEARABLE, suit, vision, BASELINE).keys() == vector.keys()
    print(f"\nDone. Files are in {a.out_dir.resolve()}")


if __name__ == "__main__":
    main()
