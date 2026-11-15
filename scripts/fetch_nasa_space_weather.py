"""Download the NASA space-weather data STELLAR replays during the mission, and save it in data/nasa/.

Sources (NASA, public):
  * NASA GSFC Space Physics Data Facility - OMNIWeb hourly data (OMNI2): Kp and Dst indices
      https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni/omni2_<year>.dat
  * NASA Space Weather Database Of Notifications, Knowledge, Information (DONKI), CCMC / NASA GSFC:
      solar energetic particle events (SEP) and geomagnetic storms (GST), through https://api.nasa.gov

The 60-day window 2024-08-25 .. 2024-10-23 (solar maximum) is the space weather of mission days 1-60.

Usage:
    python scripts/fetch_nasa_space_weather.py                    # download from NASA (needs internet)
    python scripts/fetch_nasa_space_weather.py --raw-dir <folder>  # use already downloaded raw files
The API key is NASA_API_KEY from the environment, or DEMO_KEY.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "nasa"
START, END = date(2024, 8, 25), date(2024, 10, 23)
OMNI_URL = "https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni/omni2_{year}.dat"
DONKI_URL = "https://api.nasa.gov/DONKI/{kind}?startDate={start}&endDate={end}&api_key={key}"


def _get(url: str, timeout: int = 300) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "stellar-space-apps-prototype"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_omni(lines, start: date = START, end: date = END) -> list[dict]:
    """Hourly Kp and Dst from OMNI2 rows (word 1 year, 2 day of year, 3 hour, 39 Kp*10, 41 Dst)."""
    out = []
    for line in lines:
        w = line.split()
        if len(w) < 41:
            continue
        ts = datetime(int(w[0]), 1, 1, tzinfo=timezone.utc) + timedelta(days=int(w[1]) - 1, hours=int(w[2]))
        if not (start <= ts.date() <= end):
            continue
        kp, dst = int(w[38]), int(w[40])
        out.append({"timestamp_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "kp": None if kp == 99 else round(kp / 10, 1),
                    "dst_nt": None if dst == 99999 else dst})
    return out


def trim_sep(events: list[dict]) -> list[dict]:
    return [{"sepID": e["sepID"], "eventTime": e["eventTime"],
             "instruments": [i["displayName"] for i in e.get("instruments") or []],
             "link": e.get("link")} for e in events]


def trim_gst(events: list[dict]) -> list[dict]:
    return [{"gstID": e["gstID"], "startTime": e["startTime"],
             "kpMax": max((k.get("kpIndex") or 0) for k in e.get("allKpIndex") or [{}]),
             "link": e.get("link")} for e in events]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--raw-dir", type=Path, help="folder with omni2_2024.dat, sep.json, gst.json")
    a = p.parse_args()
    key = os.getenv("NASA_API_KEY", "DEMO_KEY")

    if a.raw_dir:
        omni_lines = (a.raw_dir / "omni2_2024.dat").read_text().splitlines()
        sep = json.loads((a.raw_dir / "sep.json").read_text())
        gst = json.loads((a.raw_dir / "gst.json").read_text())
    else:
        omni_lines = _get(OMNI_URL.format(year=START.year)).decode().splitlines()
        sep = json.loads(_get(DONKI_URL.format(kind="SEP", start=START, end=END, key=key)))
        gst = json.loads(_get(DONKI_URL.format(kind="GST", start=START, end=END, key=key)))

    OUT.mkdir(parents=True, exist_ok=True)
    hourly = parse_omni(omni_lines)
    with open(OUT / "omni_kp_dst_hourly.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp_utc", "kp", "dst_nt"])
        w.writeheader()
        w.writerows(hourly)
    (OUT / "donki_sep.json").write_text(json.dumps(trim_sep(sep), indent=1) + "\n", encoding="utf-8")
    (OUT / "donki_gst.json").write_text(json.dumps(trim_gst(gst), indent=1) + "\n", encoding="utf-8")
    print(f"saved {len(hourly)} hourly rows, {len(sep)} SEP events, {len(gst)} geomagnetic storms in {OUT}")


if __name__ == "__main__":
    main()
