"""Save the demo overlay video: skeleton + angles + reps + the 3 vision features.

The numbers come from vision_features.analyze_video, so they are identical
to the ones in health.json.
Usage: python make_overlay_video.py --video samples/squat.mp4
"""

import argparse
from pathlib import Path

import cv2
import numpy as np

from vision_features import analyze_video

CONNECTIONS = [(11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (11, 23), (12, 24),
               (23, 24), (23, 25), (25, 27), (24, 26), (26, 28)]
OUT_WIDTH = 960  # smaller files, easier to upload and share


def draw_panel(img, lines, footer):
    overlay = img.copy()
    cv2.rectangle(overlay, (10, 10), (370, 20 + 28 * len(lines)), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, img, 0.45, 0, img)
    for i, text in enumerate(lines):
        cv2.putText(img, text, (20, 38 + i * 28), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (255, 255, 255), 2)
    cv2.putText(img, footer, (10, img.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX,
                0.45, (200, 200, 200), 1)


def final_frame(size):
    w, h = size
    img = np.full((h, w, 3), 20, dtype=np.uint8)
    cv2.putText(img, "Why fusion matters", (40, int(h * .2)), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 3)
    cv2.putText(img, "Before fusion:  HR=80 -> Normal", (40, int(h * .42)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (80, 220, 80), 2)
    cv2.putText(img, "After fusion:", (40, int(h * .58)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.putText(img, "HR=80 + Sleep=4h + Low activity", (70, int(h * .67)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.putText(img, "-> Fatigue Risk = HIGH", (70, int(h * .78)), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (60, 60, 255), 3)
    return img


def make_overlay(video, out_dir="outputs", side="right", analysis=None):
    out_dir = Path(out_dir)
    out_dir.mkdir(exist_ok=True)
    res = analysis or analyze_video(video, side=side)
    frames, fps, (w, h) = res["frames"], res["fps"], res["size"]
    if not frames:
        print("No frames to write (video missing or unreadable).")
        return None
    scale = OUT_WIDTH / w if w > OUT_WIDTH else 1.0
    size = (int(w * scale), int(h * scale))
    mp4 = out_dir / "overlay_output.mp4"
    avi = out_dir / "overlay_output.avi"
    writers = [cv2.VideoWriter(str(mp4), cv2.VideoWriter_fourcc(*"mp4v"), fps, size),
               cv2.VideoWriter(str(avi), cv2.VideoWriter_fourcc(*"MJPG"), fps, size)]
    writers = [wr for wr in writers if wr.isOpened()]
    feat = res["features"]

    cap = cv2.VideoCapture(str(video))
    for i, info in enumerate(frames):
        ok, img = cap.read()
        if not ok:
            break
        img = cv2.resize(img, size)
        pts = info["pts"]
        if pts:
            sp = {k: (int(p[0] * scale), int(p[1] * scale)) for k, p in pts.items() if p}
            for a, b in CONNECTIONS:
                if a in sp and b in sp:
                    cv2.line(img, sp[a], sp[b], (0, 255, 0), 2)
            for p in sp.values():
                cv2.circle(img, p, 4, (0, 180, 255), -1)
        knee = f"{info['knee']:.0f} deg" if info["knee"] is not None else "--"
        back = f"{info['back']:.0f} deg" if info["back"] is not None else "--"
        lines = [f"Reps: {info['reps']}", f"Knee: {knee}   Back: {back}",
                 f"posture_score: {feat['posture_score']:.2f}",
                 f"movement_quality: {feat['movement_quality']:.2f}",
                 f"fatigue_indicator: {feat['fatigue_indicator']:.2f}"]
        draw_panel(img, lines, "AstroGuardian | simulated data | heuristic estimate")
        for wr in writers:
            wr.write(img)
        if i % 50 == 0:
            print(f"  overlay progress: frame {i}/{len(frames)}")
    cap.release()
    end = final_frame(size)
    for _ in range(int(fps * 3)):
        for wr in writers:
            wr.write(end)
    for wr in writers:
        wr.release()
    print(f"Saved: {mp4}\nSaved: {avi}")
    return mp4


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default="samples/squat.mp4")
    ap.add_argument("--out-dir", default="outputs")
    ap.add_argument("--side", default="right", choices=["right", "left"])
    a = ap.parse_args()
    make_overlay(a.video, a.out_dir, a.side)
