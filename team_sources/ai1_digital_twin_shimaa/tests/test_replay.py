import json

import pandas as pd
import pytest

from astroguardian_digital_twin import replay
from astroguardian_digital_twin.data_cleaning import WEARABLE_FIELDS
from astroguardian_digital_twin.demo_scenarios import write_demo_artifacts


@pytest.fixture(scope="module")
def demo_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp("proj")
    write_demo_artifacts(root, seed=42)
    return root / "data" / "demo"


def test_payload_matches_backend_contract(demo_dir):
    df = pd.read_csv(demo_dir / "ahmed_normal.csv")
    p = replay.row_to_payload(df.iloc[10])
    assert set(p) == {"astronaut_id", "timestamp", "wearable"}
    assert p["astronaut_id"] == "AST-001" and p["timestamp"] == "2026-08-25T10:00:00Z"
    assert tuple(p["wearable"]) == WEARABLE_FIELDS
    assert all(isinstance(v, float) for v in p["wearable"].values())
    assert set(replay.row_to_payload(df.iloc[0], include_empty_sections=True)) >= {"suit", "vision"}


def test_chronological_order_and_day_filter(demo_dir):
    allp = pd.concat([pd.read_csv(demo_dir / f) for f in ("ahmed_normal.csv", "omar_emergency.csv")])
    out = list(replay.iter_payloads(allp, start_day=56))
    assert len(out) == 2 * 5 * 24
    ts = [p["timestamp"] for p in out]
    assert ts == sorted(ts) and ts[0] == "2026-10-19T00:00:00Z"
    assert {p["astronaut_id"] for p in out} == {"AST-001", "AST-003"}


def test_nan_becomes_null_and_json_is_strict():
    row = pd.Series({"astronaut_id": "AST-001", "timestamp": "2026-08-25T00:00:00Z", **{f: 1.0 for f in WEARABLE_FIELDS}})
    row["hr"] = float("nan")
    p = replay.row_to_payload(row)
    assert p["wearable"]["hr"] is None
    json.dumps(p, allow_nan=False)


def test_missing_column_and_file_errors(tmp_path):
    with pytest.raises(replay.ReplayError):
        replay.row_to_payload(pd.Series({"astronaut_id": "x"}))
    with pytest.raises(replay.ReplayError):
        replay.load_source(tmp_path / "nope.csv")


def test_local_cli_makes_no_network_calls(demo_dir, tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("network used in local mode")
    monkeypatch.setattr(replay.urllib.request, "urlopen", boom)
    out = tmp_path / "r.jsonl"
    rc = replay.main(["--scenario", "sara", "--data-dir", str(demo_dir), "--limit", "5", "--output", str(out)])
    assert rc == 0
    lines = [json.loads(l) for l in out.read_text().splitlines()]
    assert len(lines) == 5 and lines[0]["astronaut_id"] == "AST-002"


def test_http_mode_only_when_requested(demo_dir, monkeypatch):
    calls = []

    class Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"risk_score": 10, "level": "Normal", "alert": null}'

    def fake_urlopen(req, timeout=0):
        calls.append((req.full_url, json.loads(req.data)))
        return Resp()
    monkeypatch.setattr(replay.urllib.request, "urlopen", fake_urlopen)
    rc = replay.main(["--scenario", "omar", "--data-dir", str(demo_dir), "--limit", "3",
                      "--post-url", "http://localhost:8000/health-data"])
    assert rc == 0 and len(calls) == 3 and calls[0][0].endswith("/health-data")
    assert calls[0][1]["wearable"]["hr"] is not None


def test_unknown_scenario_returns_error_code(demo_dir, capsys):
    assert replay.main(["--scenario", "zed", "--data-dir", str(demo_dir)]) == 2


def test_login_url_is_derived_from_post_url():
    from astroguardian_digital_twin.replay import login_url_for
    assert login_url_for("http://127.0.0.1:8000/health-data") == "http://127.0.0.1:8000/login"
    assert login_url_for("https://api.example.test/health-data/") == "https://api.example.test/login"
