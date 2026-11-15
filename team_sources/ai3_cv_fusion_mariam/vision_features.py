"""Computer Vision: squat pose analysis -> 3 vision features (0..1).

Uses the MediaPipe Tasks API (PoseLandmarker, VIDEO mode).
`analyze_video` runs the detector ONCE and keeps everything we need, so the
overlay video and the JSON use exactly the same numbers.
"""

import math
from pathlib import Path

import cv2
import mediapipe as mp

DEFAULT_MODEL = Path(__file__).parent / "models" / "pose_landmarker_lite.task"
NEUTRAL = {"posture_score": 0.5, "movement_quality": 0.5,
           "fatigue_indicator": 0.5, "rep_count": 0}

# Landmark indices (shoulder, hip, knee, ankle) for each body side.
SIDES = {"right": (12, 24, 26, 28), "left": (11, 23, 25, 27)}

KNEE_DOWN_DEG = 105   # knee angle below this = squatting
KNEE_UP_DEG = 155     # back above this = standing again (rep finished)


def clip01(x):
    return max(0.0, min(1.0, float(x)))


def angle(a, b, c):
    """Angle ABC in degrees (b is the joint). Returns None if a point is missing."""
    if a is None or b is None or c is None:
        return None
    d = abs(math.degrees(math.atan2(c[1] - b[1], c[0] - b[0])
                         - math.atan2(a[1] - b[1], a[0] - b[0])))
    return 360 - d if d > 180 else d


def _point(lms, i, w, h):
    lm = lms[i]
    if lm.visibility is not None and lm.visibility < 0.5:
        return None
    return (lm.x * w, lm.y * h)


def features_from_reps(reps, rep_count=None):
    """Turn a list of reps into the 3 features.

    Each rep: {"depth": 180 - min_knee_angle, "duration": seconds,
               "back_dev": back deviation from vertical at the bottom (deg)}
    Fewer than 2 reps -> neutral 0.5 values.
    """
    if len(reps) < 2:
        return dict(NEUTRAL, rep_count=len(reps))

    depths = [r["depth"] for r in reps]
    durs = [r["duration"] for r in reps]
    mean = lambda xs: sum(xs) / len(xs)

    # posture_score: a squat leans forward naturally, so we allow up to ~60 deg.
    # 0 deg deviation -> 1.0, 60 deg or more -> 0.0.
    posture = clip01(1 - mean([r["back_dev"] for r in reps]) / 60.0)

    # movement_quality: consistency across reps. Coefficient of variation (std/mean)
    # of depth and duration; 0 variation -> 1.0, ~50% variation -> 0.0.
    def cv(xs):
        m = mean(xs)
        if m <= 0:
            return 1.0
        return math.sqrt(mean([(x - m) ** 2 for x in xs])) / m
    quality = clip01(1 - (cv(depths) + cv(durs)) / 2 / 0.5)

    # fatigue_indicator: compare early reps vs late reps.
    # 50% slower -> full slowdown score, 25% shallower -> full depth-loss score.
    half = max(1, len(reps) // 2)
    early_d, late_d = mean(depths[:half]), mean(depths[-half:])
    early_t, late_t = mean(durs[:half]), mean(durs[-half:])
    slowdown = max(0.0, late_t / max(early_t, 1e-6) - 1)
    depth_loss = max(0.0, 1 - late_d / max(early_d, 1e-6))
    fatigue = clip01(0.5 * min(1, slowdown / 0.5) + 0.5 * min(1, depth_loss / 0.25))

    return {"posture_score": round(posture, 3),
            "movement_quality": round(quality, 3),
            "fatigue_indicator": round(fatigue, 3),
            "rep_count": rep_count if rep_count is not None else len(reps)}


def analyze_video(video_path, model_path=None, side="right", max_seconds=60):
    """Run pose detection once. Returns a dict (never raises):

    {"features": {...4 keys...}, "frames": [per-frame info], "fps", "size", "ok"}
    Each frame info: {"pts": {index: (x, y)} or None, "knee", "back", "reps"}
    """
    result = {"features": dict(NEUTRAL), "frames": [], "fps": 30.0,
              "size": (0, 0), "ok": False}
    cap = None
    try:
        model_path = Path(model_path or DEFAULT_MODEL)
        if not Path(video_path).is_file() or not model_path.is_file():
            return result
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return result
        fps = cap.get(cv2.CAP_PROP_FPS)
        fps = fps if math.isfinite(fps) and fps > 0 else 30.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        result.update(fps=fps, size=(w, h))

        sh_i, hip_i, knee_i, ank_i = SIDES.get(side, SIDES["right"])
        options = mp.tasks.vision.PoseLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path.resolve())),
            running_mode=mp.tasks.vision.RunningMode.VIDEO, num_poses=1)

        reps, phase = [], "UP"
        cur = None  # current rep being tracked
        frame_i, prev_ts, pose_frames = 0, -1, 0
        max_frames = int(max_seconds * fps) if max_seconds else None

        with mp.tasks.vision.PoseLandmarker.create_from_options(options) as lm:
            while True:
                ok, frame = cap.read()
                if not ok or (max_frames and frame_i >= max_frames):
                    break
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                ts = max(prev_ts + 1, round(frame_i * 1000 / fps))
                prev_ts = ts
                det = lm.detect_for_video(img, ts)

                info = {"pts": None, "knee": None, "back": None, "reps": len(reps)}
                if det.pose_landmarks:
                    pose_frames += 1
                    lms = det.pose_landmarks[0]
                    info["pts"] = {i: _point(lms, i, w, h) for i in range(33)}
                    p = info["pts"]
                    knee = angle(p[hip_i], p[knee_i], p[ank_i])
                    back = None
                    if p[sh_i] and p[hip_i]:
                        # 0 deg = shoulder directly above hip (vertical back)
                        back = angle(p[sh_i], p[hip_i], (p[hip_i][0], p[hip_i][1] - 100))
                    info["knee"], info["back"] = knee, back

                    if knee is not None:
                        if phase == "UP" and knee < KNEE_DOWN_DEG:
                            phase = "DOWN"
                            cur = {"start": frame_i, "min_knee": knee,
                                   "back_dev": back if back is not None else 0.0}
                        elif phase == "DOWN":
                            if knee < cur["min_knee"]:
                                cur["min_knee"] = knee
                                if back is not None:
                                    cur["back_dev"] = back
                            if knee > KNEE_UP_DEG:
                                reps.append({"depth": 180 - cur["min_knee"],
                                             "duration": (frame_i - cur["start"]) / fps,
                                             "back_dev": cur["back_dev"]})
                                phase = "UP"
                    info["reps"] = len(reps)
                result["frames"].append(info)
                frame_i += 1

        if pose_frames > 0:
            result["features"] = features_from_reps(reps, rep_count=len(reps))
            result["ok"] = True
    except Exception as exc:  # never crash the demo
        print(f"[vision] warning: {exc}")
    finally:
        if cap is not None:
            cap.release()
    return result


def extract_vision_features(video_path, model_path=None, side="right"):
    """Main function: {"posture_score","movement_quality","fatigue_indicator","rep_count"}."""
    return analyze_video(video_path, model_path, side)["features"]


if __name__ == "__main__":
    import sys
    print(extract_vision_features(sys.argv[1] if len(sys.argv) > 1 else "samples/squat.mp4"))
