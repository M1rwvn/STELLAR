"""Space weather from NASA data, replayed on the mission timeline.

Data (data/nasa/, made by scripts/fetch_nasa_space_weather.py):
  * omni_kp_dst_hourly.csv - NASA GSFC SPDF OMNIWeb (OMNI2) hourly Kp and Dst, 2024-08-25 .. 2024-10-23
  * donki_sep.json         - NASA DONKI solar energetic particle events in the same window
  * donki_gst.json         - NASA DONKI geomagnetic storms in the same window

Mission day 1 = 2024-08-25 (solar maximum), so mission days 1-60 replay the real space weather of those
60 days, including the 9 October 2024 radiation storm (>100 MeV protons at GOES) and the 10 October
severe geomagnetic storm. Radiation is one of NASA's five hazards of human spaceflight.

What the backend does with it:
  * GET /space-weather: Kp, Dst, geomagnetic level, radiation status and recent NASA events at mission time;
  * a crew-wide `space_weather` alert when a radiation storm reaches Earth orbit (DONKI SEP seen by GOES)
    or a severe geomagnetic storm (Kp >= 7.7) starts, once per event.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alert

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "nasa"
NASA_START = datetime(2024, 8, 25, tzinfo=timezone.utc)        # = mission day 1, 00:00 UTC
SCENARIO_START = datetime(2026, 8, 25, tzinfo=timezone.utc)    # the demo crew data's day 1
RADIATION_HOURS = 48       # a radiation storm is treated as active for 48 h after onset
SOURCES = [
    {"name": "NASA OMNIWeb (GSFC SPDF), hourly Kp and Dst",
     "url": "https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni/"},
    {"name": "NASA DONKI space weather database (CCMC), SEP and GST events",
     "url": "https://ccmc.gsfc.nasa.gov/tools/DONKI/"},
]


def _ts(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


@lru_cache(maxsize=1)
def load() -> dict:
    hourly = {}
    with open(DATA_DIR / "omni_kp_dst_hourly.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            hourly[_ts(r["timestamp_utc"])] = {"kp": float(r["kp"]) if r["kp"] else None,
                                               "dst_nt": int(r["dst_nt"]) if r["dst_nt"] else None}
    sep = json.loads((DATA_DIR / "donki_sep.json").read_text(encoding="utf-8"))
    gst = json.loads((DATA_DIR / "donki_gst.json").read_text(encoding="utf-8"))
    for e in sep:
        e["time"] = _ts(e["eventTime"])
        e["at_earth"] = any(i.startswith("GOES") for i in e["instruments"])     # measured at Earth orbit
        e["over_100mev"] = any(">100 MeV" in i for i in e["instruments"])
    for e in gst:
        e["time"] = _ts(e["startTime"])
    # One storm = GOES events that follow each other within RADIATION_HOURS (NASA logs the >100 MeV
    # and >10 MeV channels of the same storm as separate events)
    storm_start = None
    last = None
    for e in sorted((e for e in sep if e["at_earth"]), key=lambda e: e["time"]):
        if last is None or e["time"] - last >= timedelta(hours=RADIATION_HOURS):
            storm_start = e["time"]
        e["storm_start"] = storm_start
        last = e["time"]
    return {"hourly": hourly, "sep": sorted(sep, key=lambda e: e["time"]),
            "gst": sorted(gst, key=lambda e: e["time"])}


def nasa_time(timestamp: datetime, mission_day: int | None = None) -> datetime:
    """The moment of the NASA record that plays at this mission time."""
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    if mission_day:
        return NASA_START + timedelta(days=mission_day - 1, hours=timestamp.hour, minutes=timestamp.minute)
    return NASA_START + (timestamp - SCENARIO_START)


def geomagnetic_level(kp: float | None) -> dict:
    """NOAA G-scale from Kp (G4 includes Kp 9-)."""
    if kp is None:
        return {"level": None, "label": "No data"}
    for lo, level, label in ((9.0, "G5", "Extreme storm"), (7.67, "G4", "Severe storm"),
                             (6.67, "G3", "Strong storm"), (5.67, "G2", "Moderate storm"),
                             (4.67, "G1", "Minor storm")):
        if kp >= lo:
            return {"level": level, "label": label}
    return {"level": "G0", "label": "Quiet" if kp < 3 else "Unsettled"}


def _event(e: dict, kind: str) -> dict:
    out = {"kind": kind, "id": e.get("sepID") or e.get("gstID"), "time": e["time"].strftime("%Y-%m-%dT%H:%MZ"),
           "link": e.get("link")}
    if kind == "SEP":
        out["detail"] = ", ".join(e["instruments"])
        if e.get("storm_start"):
            out["storm_start"] = e["storm_start"].strftime("%Y-%m-%dT%H:%MZ")
    else:
        out["detail"] = f"Kp max {e['kpMax']:g}"
    return out


def radiation_at(t: datetime) -> dict:
    """Radiation status: active for 48 h after a DONKI SEP event measured by GOES at Earth orbit."""
    active = [e for e in load()["sep"] if e["at_earth"] and e["time"] <= t < e["time"] + timedelta(hours=RADIATION_HOURS)]
    if not active:
        return {"active": False, "level": None, "text": "No solar radiation storm at Earth orbit", "event": None}
    worst = max(active, key=lambda e: (e["over_100mev"], -e["time"].timestamp()))
    severe = worst["over_100mev"]
    return {"active": True, "level": "severe" if severe else "moderate",
            "text": ("Solar radiation storm: >100 MeV protons at Earth orbit" if severe
                     else "Solar radiation storm: >10 MeV protons at Earth orbit"),
            "event": _event(worst, "SEP")}


def conditions(t: datetime) -> dict:
    data = load()
    hour = t.replace(minute=0, second=0, microsecond=0)
    row = data["hourly"].get(hour, {"kp": None, "dst_nt": None})
    history = [{"time": (hour - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%MZ"),
                "kp": data["hourly"].get(hour - timedelta(hours=h), {}).get("kp")} for h in range(167, -1, -1)]
    events = [_event(e, "SEP") for e in data["sep"] if e["at_earth"] and e["time"] <= t]
    events += [_event(e, "GST") for e in data["gst"] if e["time"] <= t]
    events.sort(key=lambda e: e["time"], reverse=True)
    return {"nasa_time": t.strftime("%Y-%m-%dT%H:%MZ"), "kp": row["kp"], "dst_nt": row["dst_nt"],
            "geomagnetic": geomagnetic_level(row["kp"]), "radiation": radiation_at(t),
            "kp_last_7_days": history, "recent_events": events[:6], "sources": SOURCES}


def _already_alerted(db: Session, event_id: str) -> bool:
    return db.scalar(select(Alert.id).where(Alert.type == "space_weather",
                                            Alert.message.contains(event_id)).limit(1)) is not None


def maybe_create_alert(db: Session, t: datetime) -> Alert | None:
    """One crew-wide alert per radiation storm reaching Earth orbit, and per severe geomagnetic storm."""
    rad = radiation_at(t)
    if rad["active"]:
        storm_id = f"SEP storm {rad['event']['storm_start']}"
        if not _already_alerted(db, storm_id):
            ev = rad["event"]
            alert = Alert(astronaut_id=None, type="space_weather",
                          severity="critical" if rad["level"] == "severe" else "high",
                          message=f"{rad['text']} (NASA DONKI {storm_id}; {ev['detail']}). "
                                  "Crew to the shielded area, postpone EVAs, monitor dosimeters.")
            db.add(alert)
            return alert
    kp = load()["hourly"].get(t.replace(minute=0, second=0, microsecond=0), {}).get("kp")
    if kp is not None and kp >= 7.67:
        storm = max((e for e in load()["gst"] if e["time"] <= t), key=lambda e: e["time"], default=None)
        storm_id = f"GST {storm['gstID']}" if storm else f"Kp {t:%Y-%m-%d}"
        if not _already_alerted(db, storm_id):
            g = geomagnetic_level(kp)
            alert = Alert(astronaut_id=None, type="space_weather", severity="medium",
                          message=f"{g['label']} ({g['level']}, Kp {kp:g}) (NASA OMNIWeb + DONKI {storm_id}). "
                                  "Expect higher radiation in the South Atlantic Anomaly and possible "
                                  "communication outages.")
            db.add(alert)
            return alert
    return None
