#!/usr/bin/env sh
# Plan B: run the backend with no Docker and no internet (SQLite).
#   ./scripts/run_local.sh          # API  -> http://localhost:8000/docs
#   ./scripts/run_local.sh mock     # Mock -> http://localhost:8001/docs
set -e
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi
[ -f .env ] || cp .env.example .env

if [ "$1" = "mock" ]; then
  exec .venv/bin/python -m uvicorn app.mock_api:app --host 0.0.0.0 --port 8001
else
  exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
fi
