"""Replay script: streams the demo scenarios to POST /health-data like live sensors.

Standard library only, so it runs on any demo machine with Python 3.10+.

Every hourly reading is sent (like a real wearable), so the backend's 24 h / 7-day history
features match the training data. --every-hours / --daily only choose which lines are SHOWN;
alerts are always shown. --warmup-days first sends the week before --start-day silently.

Examples
    python scripts/replay.py --start-day 45 --every-hours 6 --interval 0.3   # demo, ~1.5 minutes
    python scripts/replay.py --start-day 50 --daily --interval 1             # 1 line per day
    python scripts/replay.py --astronauts AST-003 --start-day 54
    python scripts/replay.py --warmup-days 0                                 # everything, no warm-up
    python scripts/replay.py --url https://<deployed-host> --now

Input files: data/scenarios/*.csv - Shimaa's (AI 1) demo data, hourly, seed 42:
ethan_normal.csv, emily_attention.csv, ryan_emergency.csv. Only the columns
astronaut_id, timestamp, mission_day and the wearable fields are sent.
*.jsonl files with contract payloads are accepted too.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEARABLE = ["hr", "hrv", "spo2", "resp_rate", "temp", "sleep_hours", "sleep_quality", "activity"]
SUIT = ["cabin_pressure_kpa", "suit_temp_c", "o2_pct", "co2_pct"]
VISION = ["posture_score", "movement_quality", "fatigue_indicator"]

COLORS = {"Normal": "\033[92m", "Attention": "\033[93m", "High Risk": "\033[38;5;208m",
          "Emergency": "\033[91m"}
RESET = "\033[0m"


def load_rows(paths: list[str]) -> list[dict]:
    rows = []
    for path in paths:
        if path.endswith(".jsonl"):
            with open(path, encoding="utf-8") as f:
                rows += [json.loads(line) for line in f if line.strip()]
        elif path.endswith(".json"):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                rows += data if isinstance(data, list) else [data]
        elif path.endswith(".csv"):
            with open(path, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    num = lambda k: float(r[k]) if r.get(k) not in (None, "") else None  # noqa: E731
                    rows.append({
                        "astronaut_id": r["astronaut_id"],
                        "timestamp": r["timestamp"],
                        "mission_day": int(float(r["mission_day"])) if r.get("mission_day") else None,
                        "wearable": {k: num(k) for k in WEARABLE},
                        "suit": {k: num(k) for k in SUIT},
                        "vision": {k: num(k) for k in VISION},
                    })
    rows.sort(key=lambda r: (r["timestamp"], r["astronaut_id"]))
    return rows


def request(url: str, body: dict, token: str | None = None, retries: int = 30) -> dict:
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            raise SystemExit(f"HTTP {e.code} from {url}: {detail}")
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            print(f"  server not reachable ({e}); retry {attempt + 1}/{retries} ...")
            time.sleep(2)
    raise SystemExit(f"Gave up: {url} is not reachable")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default=os.getenv("API_URL", "http://127.0.0.1:8000"))
    p.add_argument("--username", default=os.getenv("REPLAY_USER", "device"))
    p.add_argument("--password", default=os.getenv("SEED_PASSWORD", "astro123"))
    p.add_argument("--files", nargs="*", help="scenario files (default: data/scenarios/*)")
    p.add_argument("--astronauts", help="comma-separated ids, e.g. AST-002,AST-003")
    p.add_argument("--start-day", type=int, default=1)
    p.add_argument("--end-day", type=int, default=10_000)
    p.add_argument("--daily", action="store_true",
                   help="show one line per day (noon); all hourly readings are still sent")
    p.add_argument("--every-hours", type=int, default=1,
                   help="show one line every N hours (6 = 00, 06, 12, 18); all hours are still sent")
    p.add_argument("--sparse", action="store_true",
                   help="send ONLY the shown readings (faster, but 24 h / 7-day features stay empty)")
    p.add_argument("--warmup-days", type=int, default=7,
                   help="first send this many days before --start-day silently, so 7-day features "
                        "are complete from the first shown reading (0 = off)")
    p.add_argument("--interval", type=float, default=0.3, help="seconds to wait after each SHOWN reading")
    p.add_argument("--now", action="store_true",
                   help="shift timestamps so the last reading is 'now' (for live dashboards)")
    p.add_argument("--no-suit-vision", action="store_true",
                   help="send wearable data only (no simulated suit telemetry / camera checks)")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    if os.name == "nt":
        os.system("")  # enable ANSI colours in the Windows terminal

    files = args.files or sorted(glob.glob(str(ROOT / "data" / "scenarios" / "*.jsonl"))
                                 + glob.glob(str(ROOT / "data" / "scenarios" / "*.csv")))
    if not files:
        raise SystemExit("No scenario files in data/scenarios/ (copy Shimaa's data/demo/*.csv there)")
    rows = load_rows(files)
    if not args.no_suit_vision:
        sys.path.insert(0, str(ROOT))
        from ai_modules import demo_sensors   # AI 3: suit every hour + daily camera check
        demo_sensors.enrich(rows)
    if args.astronauts:
        wanted = set(args.astronauts.split(","))
        rows = [r for r in rows if r["astronaut_id"] in wanted]

    def day(r: dict) -> int:
        return r.get("mission_day") or 0

    first_day = max(1, args.start_day - max(0, args.warmup_days))
    warmup = [r for r in rows if first_day <= day(r) < args.start_day]
    rows = [r for r in rows if args.start_day <= day(r) <= args.end_day or r.get("mission_day") is None]

    def shown(r: dict) -> bool:
        hour = int(r["timestamp"][11:13])
        return hour == 12 if args.daily else hour % max(1, args.every_hours) == 0

    if args.sparse:
        rows = [r for r in rows if shown(r)]
        warmup = [r for r in warmup if shown(r)]
    if not rows:
        raise SystemExit("Nothing to send with these filters")

    shift = timedelta(0)
    if args.now:
        last = datetime.fromisoformat(rows[-1]["timestamp"].replace("Z", "+00:00"))
        shift = datetime.now(timezone.utc) - last

    def body_of(row: dict) -> dict:
        body = dict(row)
        if shift:
            ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")) + shift
            body["timestamp"] = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        return body

    base = args.url.rstrip("/")
    token = request(f"{base}/login", {"username": args.username, "password": args.password})["access_token"]
    if warmup:
        print(f"Warm-up: sending {len(warmup)} readings of history (days {first_day}-{args.start_day - 1}) "
              "so 24 h / 7-day features are complete ...", flush=True)
        for row in warmup:
            request(f"{base}/health-data", body_of(row), token)
    n_shown = sum(1 for r in rows if shown(r))
    print(f"Replaying {len(rows)} readings ({n_shown} shown) from {len(files)} file(s) "
          f"to {base} as '{args.username}'")
    print()

    alerts = 0
    i = 0
    for row in rows:
        res = request(f"{base}/health-data", body_of(row), token)
        if res.get("alert"):
            alerts += 1
        if not shown(row) and not res.get("alert"):   # alerts are always shown
            continue
        if shown(row):
            i += 1
        counter = f"{i:4}/{n_shown}" if shown(row) else " " * (5 + len(str(n_shown)))
        if not args.quiet:
            color = COLORS.get(res["level"], "")
            factors = ", ".join(f"{f['feature']} {f['change_pct']:+.0f}%" for f in res["top_factors"][:2])
            line = (f"[{counter}] day {row.get('mission_day', '?'):>2} "
                    f"{row['timestamp'][11:16]} {row['astronaut_id']} "
                    f"{color}{res['risk_score']:>3} {res['level']:<9}{RESET} {factors}")
            if res.get("alert"):
                line += f"  {COLORS['Emergency']}ALERT #{res['alert']['id']} {res['alert']['severity']}{RESET}"
            print(line, flush=True)
        time.sleep(args.interval)

    print()
    print(f"Done: {len(rows) + len(warmup)} readings sent ({len(warmup)} warm-up), {alerts} alert(s) created.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nStopped.")
