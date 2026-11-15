# STELLAR — Technical guide

How the STELLAR system is built and run: **FastAPI + PostgreSQL + Docker**, JWT auth, the AI
pipeline (baseline → fusion → risk), NASA space weather, automatic alerts, the Ground Control
dashboard, a Mock API for other front-ends, and the replay script that runs the demo.
For the overview, see the [project README](../README.md).

```
Wearable + Suit + Vision ──► POST /health-data
                              ├─ get_baseline()        AI 1  Shimaa  (Digital Twin)
                              ├─ build_health_vector() AI 3  Mariam  (Data Fusion)
                              ├─ predict_risk()        AI 2  Menna   (Risk Prediction)
                              ├─ store reading + risk score  (PostgreSQL)
                              ├─ High Risk / Emergency ──► alert (Emergency first)
                              └─ downlink queue to Ground (simulated delay, priority)
                                       │
               Flutter app (Lena) ◄────┴────► Ground dashboard (Marwan)
```

| Risk score | Level | Colour | Meaning |
|---|---|---|---|
| 0 – 25 | Normal | green | stable |
| 25 – 50 | Attention | yellow | needs follow-up |
| 50 – 75 | High Risk | orange | alert to the crew |
| 75 – 100 | Emergency | red | immediate alert to Ground Control |

---

## Quick start

### The prototype in one double-click (Windows)

```bat
START_PROTOTYPE.bat
```
Starts the server (fresh database), opens the **Ground Control dashboard** at
http://127.0.0.1:8000/dashboard and streams the three astronauts live (days 45–60, ~2 minutes).
First run needs internet once to install the libraries (a few minutes); after that it runs offline.
Close the two windows "STELLAR - Server" and "STELLAR - Live data" to stop.

The dashboard (`app/static/dashboard.html`, served by the backend, no external files) shows the crew as
risk rings, the selected astronaut's health-risk / sleep / fatigue rings, the reasons in plain English, the
current vitals against the personal normal, the suit and camera data, the risk chart, alerts with *Acknowledge*, and the space-to-ground link with a *loss of signal* button.

### Option A — Docker (the normal way)

```bash
docker compose up --build
```

| Service | URL |
|---|---|
| API + Swagger | http://localhost:8000/docs |
| Mock API (fixed data, for Flutter/Web) | http://localhost:8001/docs |
| PostgreSQL | localhost:5432 (`astro` / `astro_dev_pw`, db `stellar`) |

Migrations run and demo users are seeded automatically. Then play the demo:

```bash
docker compose --profile demo run --rm replay
```

### Option B — No Docker, no internet (Plan B)

Runs on SQLite with the same code. Needs Python 3.11+.

```bat
:: Windows (Command Prompt or PowerShell, from the project folder, or double-click the .bat)
scripts\run_local.bat           :: API  -> http://127.0.0.1:8000/docs
scripts\run_local.bat -Mock     :: Mock -> http://127.0.0.1:8001/docs
scripts\run_local.bat -Reset    :: start again with an empty database
```
The first run creates `.venv` and downloads the libraries (needs internet once).
Works with Python 3.11 – 3.14. Use the `.bat`: Windows blocks running the `.ps1`
directly when it comes from a downloaded zip.
```bash
# macOS / Linux
./scripts/run_local.sh
./scripts/run_local.sh mock
```

In another terminal:

```bash
python scripts/replay.py --start-day 45 --every-hours 6 --interval 0.3
```

> **Windows tip:** use `127.0.0.1` instead of `localhost` when calling a locally run
> server; `localhost` tries IPv6 first and adds ~2 s to every request.

### Which address to use

| Calling from | Base URL |
|---|---|
| A browser / dashboard on the same laptop | `http://127.0.0.1:8000` |
| Android emulator | `http://10.0.2.2:8000` (the emulator's name for the laptop) |
| iOS simulator | `http://127.0.0.1:8000` |
| A real phone or another laptop | `http://<laptop IP>:8000` — same Wi-Fi, find the IP with `ipconfig`, and click **Allow** on the Windows Firewall prompt the first time the server starts |

Swap `8000` for `8001` to reach the Mock API. If port 5432 is already taken (a local
PostgreSQL), stop that service or change the left side of `"5432:5432"` in `docker-compose.yml`.

### Demo accounts (development only)

All seeded accounts use the password in `SEED_PASSWORD` (default `astro123`).
Change it in `.env` before deploying anywhere public.

| Username | Role | Can do |
|---|---|---|
| `ethan`, `emily`, `ryan` | astronaut | own profile, risk, history, alerts; post own readings |
| `doctor` | doctor | all astronauts, health alerts, acknowledge alerts |
| `ground` | ground | everything on the dashboard incl. security alerts / events, comm link |
| `admin` | admin | everything |
| `device` | device | `POST /health-data` only (wearable / replay script) |

Astronaut IDs: `AST-001` Ethan · `AST-002` Emily · `AST-003` Ryan.

---

## Endpoints

Full request/response examples: [API_CONTRACT.md](API_CONTRACT.md) · live: `/docs`.

| Method | Path | Roles | Purpose |
|---|---|---|---|
| POST | `/login` | public | JWT for a username/password (lockout after 5 failures) |
| POST | `/health-data` | astronaut (self), device | reading → fusion → risk → store → alert |
| GET | `/astronaut-profile/{id}` | astronaut (self), doctor, ground | profile + personal baseline |
| GET | `/risk-score/{id}` | astronaut (self), doctor, ground | latest score, top factors, recommendation |
| GET | `/alerts?astronaut_id=&type=&acknowledged=` | by role | alerts, Emergency first |
| GET | `/crew` | doctor, ground | whole crew status for the dashboard |
| GET | `/risk-history/{id}` | astronaut (self), doctor, ground | score over time for charts |
| POST | `/alerts/{id}/ack` | doctor, ground | acknowledge an alert |
| GET | `/health` | public | liveness + DB + which AI modules are live |
| GET | `/me` | any logged-in | decoded identity |
| GET | `/security-events` | ground | login failures, lockouts, forbidden access (for the IDS view) |
| GET | `/comm/status` | doctor, ground | simulated downlink queue + delivered log |
| POST | `/comm/blackout` | ground | simulate loss of signal |
| GET | `/space-weather` | astronaut, doctor, ground | NASA space weather at mission time: Kp, Dst, G-level, radiation storm, recent DONKI events |

`admin` passes every role check. Send the token as `Authorization: Bearer <token>`.

---

## Project layout

```
app/
  main.py            FastAPI app, CORS, timing/security headers, startup (migrate/seed/comm link)
  config.py          settings from env / .env
  models.py          SQLAlchemy tables (docs/ERD.md)
  schemas.py         Pydantic = the Interface Contract in code
  security.py        JWT, roles, lockout, security events  (owner: Marwan)
  ai/__init__.py     the ONLY place that calls AI code; picks real modules or stubs
  ai/stubs/          contract-compatible stand-ins for AI 1/2/3
  services/pipeline.py   POST /health-data flow
  services/alerts.py     alert rules, de-duplication, Emergency-first ordering
  services/comm_link.py  space-to-ground link: delay + Emergency priority queue
  routers/           endpoints
  mock_api.py        Mock API (fixed data, same shapes)
ai_modules/          the AI team's real modules
  digital_twin.py            AI 1 (Shimaa) - live
  astroguardian_digital_twin/  Shimaa's package, copied unmodified
  profiles/all_profiles.json   her 10 personal baselines (seed 42)
  fusion.py                  AI 3 (Mariam) - live
  mariam_cv_fusion/          Mariam's fusion layer + suit simulator, copied unmodified
  demo_sensors.py            demo suit telemetry (her simulator) + daily camera check
  risk.py                    AI 2 (Menna) - live
  menna_risk/                Menna's model (code unchanged, comments in English)
migrations/          Alembic migrations
mock/fixtures.json   Mock data (also usable as static JSON by the front-ends)
data/scenarios/      Shimaa's demo data: Ethan / Emily / Ryan, 60 days x 24 h (CSV)
scripts/             replay.py, run_local.*, backup/restore
tests/               pytest (auth, flow, alerts, AI contract, comm link, mock)
docs/                contract, ERD, architecture research, demo plan, board, rules
```

## NASA data: space weather

Mission days 1-60 replay the **real space weather of 25 Aug - 23 Oct 2024** (solar maximum), from NASA:

| Dataset | What STELLAR uses | File |
|---|---|---|
| NASA GSFC SPDF **OMNIWeb** (OMNI2 hourly) | Kp and Dst every hour | `data/nasa/omni_kp_dst_hourly.csv` |
| NASA **DONKI** (CCMC), solar energetic particles | radiation storms seen by GOES at Earth orbit | `data/nasa/donki_sep.json` |
| NASA **DONKI** (CCMC), geomagnetic storms | storm start and Kp maximum | `data/nasa/donki_gst.json` |

`scripts/fetch_nasa_space_weather.py` downloads them again from NASA (OMNIWeb file + `api.nasa.gov/DONKI`).
On every reading the backend looks up the NASA record of that mission hour: a radiation storm at Earth orbit
(e.g. the real 9 October 2024 event, >100 MeV protons, mission day 46) creates one crew-wide `space_weather`
alert ("crew to the shielded area, postpone EVAs"), and so does a severe geomagnetic storm (10 October 2024,
Kp 8.7 on mission day 47, Dst down to -333 nT early on day 48). `GET /space-weather` feeds the dashboard's NASA panel. Radiation is one of
NASA's five hazards of human spaceflight; the crew data stays synthetic, the space weather is real.

## AI models

| Module | Owner | Status |
|---|---|---|
| Digital Twin — `get_baseline`, `compute_deviation` | Shimaa (AI 1) | **live** — v1.1.0 (reviewed with the backend) |
| History features — `online_features` | Shimaa (AI 1) | **live** — same features as her training table, from the last 7 days in the DB |
| Explanations — `explain_deviation` | Shimaa (AI 1) | **live** — plain-English reasons in `/risk-score` and alerts |
| Data Fusion — `build_health_vector` | Mariam (AI 3) | **live** — her Core v1.0 (24 fixed columns, fatigue Low / Medium / High, last-known-value filling) with AI 1's real deviations; the connector adds cabin-limit flags. Her MediaPipe video analysis runs where the camera is |
| Risk — `predict_risk` | Menna (AI 2) | **live** — v1.1.0 hybrid model (Random Forest + Isolation Forest + NEWS), fed the 24 h means it was trained on; loaded with an allow-list (only numpy / scikit-learn objects) |

On every reading the backend reads the astronaut's last 7 days from the database and asks
AI 1 for the history features, so the vector stored for Menna's model has **exactly** the
columns and values of AI 1's training table (`tests/test_integration_ai1.py` checks 22 columns
through the API).

All three AI modules are live. To update one, replace its files in `ai_modules/` — nothing else changes. Details and
rules: [ai_modules/README.md](../ai_modules/README.md). `GET /health` shows `"real"` or
`"stub"` for each. If a real module throws, that one request falls back to the stub and
the error is logged, so the demo never stops.

## Demo

[DEMO_PLAN.md](DEMO_PLAN.md) has the full script. Short version (~2 minutes):

```bash
python scripts/replay.py --start-day 45 --every-hours 6 --interval 0.3
```
The replay sends **every hourly reading** (like a real wearable) and prints one line every
6 hours; it first sends the 7 days before the start day silently, so the history features are
complete from the first printed line. Ethan stays green, Emily slides from green into yellow,
Ryan gets an early warning on day 56 and turns red from day 57 — the alert appears on the dashboard and jumps the
downlink queue (`/comm/status`). Try `POST /comm/blackout {"seconds": 20}` first to show
queued data being sent Emergency-first when the link returns.

The scenario data is Shimaa's (`data/demo/*.csv` in her repo, seed 42, identical every
time). To update it, copy her new CSVs into `data/scenarios/`.

## Tests

```bash
python -m pytest
```
78 tests: login/roles/lockout, the full flow, validation, missing sensors, the three
demo scenarios on Shimaa's data (every hour of the last day), Ryan's early warning,
alert ordering and acknowledgement, the AI contract, the priority queue, the Mock API,
a < 1 s response check, and end-to-end integration with AI 1 (training-identical features,
explanations in the app and alerts, strict JSON, normal-range coverage) and with AI 2
(training-identical 24 h means, tampered model file refused, loud fallback, < 1 s) and with AI 3
(her fixed columns, AI 1 deviations instead of her placeholder, per-astronaut last-known values, the
brief's fatigue example, cabin-limit flags, demo sensors, fused data in the API).

## Database

- Migrations: `alembic upgrade head` (Docker does it on start).
  New migration after changing `models.py`: `alembic revision --autogenerate -m "..."`.
- Seed: `python -m app.seed` (also runs on startup when `SEED_ON_STARTUP=true`).
- Backup / restore (Code Freeze): `./scripts/backup_db.sh`, `./scripts/restore_db.sh backups/<file>.sql`.

## Deployment (Render / Railway)

1. Push the repo to GitHub.
2. Create a PostgreSQL instance; copy its URL.
3. Create a web service from the repo using the `Dockerfile`.
4. Environment: `DATABASE_URL` (use the `postgresql+psycopg2://` prefix),
   `JWT_SECRET` (random, long), `SEED_PASSWORD` (not the default), `CORS_ORIGINS`
   (the dashboard URL).
5. Health check path: `/health`. Point the replay script at it:
   `python scripts/replay.py --url https://<your-service> --now`.

Keep Plan B ready anyway: the hackathon network is not under our control.

## Team rules

Branch per person, PRs only, one reviewer, contract changes announced first:
[CONTRIBUTING.md](CONTRIBUTING.md).
