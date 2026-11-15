"""Replay demo readings in the backend's POST /health-data format (wearable fields only).

Default = LOCAL mode: payloads are printed as JSON lines (or written to a file); NO network.
HTTP is only used when ``--post-url`` is given (stdlib urllib; optional bearer token from the
ASTROGUARDIAN_TOKEN environment variable).  ``suit`` and ``vision`` belong to other team members
and are omitted unless ``--include-empty-sections`` is set (then they are sent as empty objects).

Examples
    python -m astroguardian_digital_twin.replay --scenario omar --start-day 56 --limit 5
    python -m astroguardian_digital_twin.replay --scenario all --output replay.jsonl
    python -m astroguardian_digital_twin.replay --scenario sara --post-url http://127.0.0.1:8000/health-data         --username device --password astro123 --verbose

HTTP auth: ``--username/--password`` log in to ``<base>/login`` first; or set ASTROGUARDIAN_TOKEN.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Union

import pandas as pd

from .data_cleaning import WEARABLE_FIELDS
from .demo_scenarios import DEMO_SCENARIOS

_ROUND = {"hr": 1, "hrv": 1, "spo2": 1, "resp_rate": 1, "temp": 2, "sleep_hours": 2,
          "sleep_quality": 3, "activity": 3}


class ReplayError(RuntimeError):
    """Raised for replay input or transmission problems."""


def _clean_number(v: Any, nd: int) -> Optional[float]:
    if v is None or (isinstance(v, float) and not math.isfinite(v)) or pd.isna(v):
        return None
    return round(float(v), nd)


def row_to_payload(row: Union[pd.Series, dict], include_empty_sections: bool = False) -> dict:
    """One CSV/DataFrame row -> contract payload (JSON-safe: NaN becomes null)."""
    missing = [c for c in ("astronaut_id", "timestamp", *WEARABLE_FIELDS) if c not in row]
    if missing:
        raise ReplayError(f"Row is missing column(s): {missing}")
    ts = pd.Timestamp(row["timestamp"])
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    payload = {"astronaut_id": str(row["astronaut_id"]),
               "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
               "wearable": {f: _clean_number(row[f], _ROUND[f]) for f in WEARABLE_FIELDS}}
    if include_empty_sections:
        payload["suit"], payload["vision"] = {}, {}
    return payload


def load_source(source: Union[str, Path, pd.DataFrame]) -> pd.DataFrame:
    if isinstance(source, pd.DataFrame):
        df = source.copy()
    else:
        p = Path(source)
        if not p.exists():
            raise ReplayError(f"Replay file not found: {p}")
        df = pd.read_csv(p)
    if "timestamp" not in df.columns:
        raise ReplayError("Replay data needs a 'timestamp' column")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def iter_payloads(source: Union[str, Path, pd.DataFrame], start_day: int = 1, end_day: Optional[int] = None,
                  limit: Optional[int] = None, include_empty_sections: bool = False) -> Iterator[dict]:
    """Yield payloads in chronological order (ties broken by astronaut_id)."""
    df = load_source(source)
    if "mission_day" in df.columns:
        df = df[df["mission_day"] >= start_day]
        if end_day is not None:
            df = df[df["mission_day"] <= end_day]
    df = df.sort_values(["timestamp", "astronaut_id"], kind="mergesort")
    if limit is not None:
        df = df.head(limit)
    for _, row in df.iterrows():
        yield row_to_payload(row, include_empty_sections)


def login_url_for(post_url: str) -> str:
    """``http://host:8000/health-data`` -> ``http://host:8000/login``."""
    base = post_url.rstrip("/")
    if base.endswith("/health-data"):
        base = base[: -len("/health-data")]
    return base + "/login"


def _post_json(url: str, body: dict, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body, allow_nan=False).encode(),
                                 headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (explicit opt-in)
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:  # show the backend's reason (401, 422 ...)
        detail = exc.read().decode(errors="replace")[:300]
        raise ReplayError(f"{url} returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ReplayError(f"Could not POST to {url}: {exc}") from exc


def login_token(post_url: str, username: str, password: str, timeout: float = 5.0) -> str:
    """Log in to the backend and return the bearer token."""
    body = _post_json(login_url_for(post_url), {"username": username, "password": password}, {}, timeout)
    if "access_token" not in body:
        raise ReplayError("Login response has no access_token")
    return body["access_token"]


def make_http_sink(url: str, timeout: float = 5.0, token: Optional[str] = None,
                   verbose: bool = False) -> Callable[[dict], None]:
    """Sink that POSTs JSON to ``url`` (only used when explicitly requested)."""
    token = token or os.environ.get("ASTROGUARDIAN_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    def _send(payload: dict) -> None:
        result = _post_json(url, payload, headers, timeout)
        if verbose:
            alert = result.get("alert")
            print(f"{payload['astronaut_id']} {payload['timestamp']} -> risk {result.get('risk_score')} "
                  f"{result.get('level')}" + (f"  ALERT {alert.get('severity')}" if alert else ""),
                  file=sys.stderr)
    return _send


def replay(payloads: Iterator[dict], sink: Callable[[dict], None], delay_seconds: float = 0.0,
           continue_on_error: bool = False) -> int:
    """Send payloads to ``sink`` one by one; returns the number delivered."""
    sent = 0
    for p in payloads:
        try:
            sink(p)
            sent += 1
        except ReplayError:
            if not continue_on_error:
                raise
        if delay_seconds > 0:
            time.sleep(delay_seconds)
    return sent


def _resolve_sources(scenario: str, data_dir: Path) -> list[Path]:
    names = list(DEMO_SCENARIOS) if scenario == "all" else [scenario]
    if any(n not in DEMO_SCENARIOS for n in names):
        raise ReplayError(f"Unknown scenario {scenario!r}; choose from {[*DEMO_SCENARIOS, 'all']}")
    return [data_dir / DEMO_SCENARIOS[n][1] for n in names]


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Replay synthetic demo readings (local by default).")
    ap.add_argument("--scenario", default="ahmed", help="ahmed | sara | omar | all")
    ap.add_argument("--data-dir", default=str(Path(__file__).resolve().parents[2] / "data" / "demo"))
    ap.add_argument("--csv", help="replay this CSV instead of a named scenario")
    ap.add_argument("--start-day", type=int, default=1)
    ap.add_argument("--end-day", type=int)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--delay", type=float, default=0.0, help="seconds between emitted readings")
    ap.add_argument("--output", help="write JSON lines to this file instead of stdout")
    ap.add_argument("--post-url", help="OPTIONAL: POST each payload to this URL (network!)")
    ap.add_argument("--username", help="log in to <post-url base>/login first (e.g. device)")
    ap.add_argument("--password", default=os.environ.get("ASTROGUARDIAN_PASSWORD"),
                    help="password for --username (or env ASTROGUARDIAN_PASSWORD)")
    ap.add_argument("--verbose", action="store_true", help="HTTP mode: print the risk result per reading")
    ap.add_argument("--include-empty-sections", action="store_true")
    ap.add_argument("--continue-on-error", action="store_true")
    args = ap.parse_args(argv)
    try:
        sources = [Path(args.csv)] if args.csv else _resolve_sources(args.scenario, Path(args.data_dir))
        frames = [load_source(s) for s in sources]
        df = pd.concat(frames, ignore_index=True)
        payloads = iter_payloads(df, args.start_day, args.end_day, args.limit, args.include_empty_sections)
        out = open(args.output, "w", encoding="utf-8") if args.output else sys.stdout
        try:
            def local_sink(p: dict) -> None:
                out.write(json.dumps(p, allow_nan=False) + "\n")
            if args.post_url:
                token = (login_token(args.post_url, args.username, args.password or "")
                         if args.username else None)
                sink = make_http_sink(args.post_url, token=token, verbose=args.verbose)
            else:
                sink = local_sink
            n = replay(payloads, sink, args.delay, args.continue_on_error)
        finally:
            if args.output:
                out.close()
    except ReplayError as exc:
        print(f"replay error: {exc}", file=sys.stderr)
        return 2
    print(f"Replayed {n} reading(s) ({'HTTP' if args.post_url else 'local'} mode).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
