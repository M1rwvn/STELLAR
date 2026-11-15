# STELLAR Interface Contract — Version 1

Owner / final approval: **Ghandor (Backend Lead)**. Lock date: **day 4**.
Any change after that is announced in the team group **before** it is implemented
and goes in through a Pull Request that updates this file and `app/schemas.py`.

Base URLs: real API `http://<host>:8000` · Mock API `http://<host>:8001`
(same paths, same shapes, fixed data). Interactive docs at `/docs` on both.

## Conventions

- JSON everywhere, `Content-Type: application/json`.
- Timestamps: ISO-8601 UTC with `Z`, e.g. `2026-10-05T10:00:00Z`.
- Astronaut IDs: `AST-001` (Ethan), `AST-002` (Emily), `AST-003` (Ryan).
- Auth: `Authorization: Bearer <access_token>` on every endpoint except `/login` and `/health`.
- `risk_score` is an **integer** 0–100. `change_pct` is a **number** (may have decimals,
  e.g. `14.4`): in Dart parse it as `num`, not `int`.
- Levels (fixed in the whole system): `Normal` 0–25 · `Attention` 25–50 · `High Risk` 50–75 · `Emergency` 75–100.
- Alert `type`: `health` | `security`. `severity`: `critical` (Emergency) | `high` (High Risk / security) | `medium` | `low`.

## Errors

| Code | When | Body |
|---|---|---|
| 401 | missing/invalid/expired token, wrong password | `{"detail": "..."}` |
| 403 | role not allowed, or astronaut accessing someone else | `{"detail": "..."}` |
| 404 | unknown astronaut / alert, or no risk score yet | `{"detail": "..."}` |
| 422 | payload fails validation (bad id, out-of-range value...) | FastAPI validation list |
| 423 | account locked after 5 failed logins (15 min) | `{"detail": "..."}` |

---

## POST /login

```json
// request
{ "username": "ethan", "password": "astro123" }
// 200
{ "access_token": "eyJhbGciOi...", "token_type": "bearer", "role": "astronaut",
  "astronaut_id": "AST-001", "expires_in": 43200 }
```
`astronaut_id` is `null` for non-astronaut roles. The Flutter app uses it to know whose data to show.

## 1) POST /health-data — wearable device / replay script → Backend

Roles: `device`, `astronaut` (own id only).

```json
{
  "astronaut_id": "AST-001",
  "timestamp": "2026-10-05T10:00:00Z",
  "wearable": { "hr": 72, "hrv": 48, "spo2": 97, "resp_rate": 16, "temp": 36.7,
                "sleep_hours": 6.5, "sleep_quality": 0.72, "activity": 0.40 },
  "suit":     { "cabin_pressure_kpa": 101.3, "suit_temp_c": 22.1,
                "o2_pct": 20.9, "co2_pct": 0.04 },
  "vision":   { "posture_score": 0.80, "movement_quality": 0.70, "fatigue_indicator": 0.30 }
}
```

Every sensor field is optional (a dropped sensor must not break the flow); the fusion
layer fills missing values and lists them in `imputed`. Optional extra: `mission_day` (int).

| Field | Unit | Accepted range |
|---|---|---|
| hr | bpm | 20–250 |
| hrv | ms | 0–300 |
| spo2 | % | 50–100 |
| resp_rate | breaths/min | 0–80 |
| temp | °C | 30–45 |
| sleep_hours | h (daily) | 0–24 |
| sleep_quality, activity | 0–1 | 0–1 |
| cabin_pressure_kpa | kPa | 0–200 |
| suit_temp_c | °C | −50–80 |
| o2_pct, co2_pct | % | 0–100 |
| posture_score, movement_quality, fatigue_indicator | 0–1 | 0–1 |

Response 200 = the risk result (same fields as `GET /risk-score`) plus:

```json
{
  "astronaut_id": "AST-003", "timestamp": "2026-10-20T12:00:00Z",
  "risk_score": 100, "level": "Emergency",
  "top_factors": [ {"feature": "sleep_hours", "change_pct": -42.9},
                   {"feature": "hr", "change_pct": 60.7},
                   {"feature": "hrv", "change_pct": -54.5} ],
  "recommendation": "EMERGENCY: contact the Ground Control flight surgeon now. ...",
  "reading_id": 2,
  "alert": { "id": 1, "astronaut_id": "AST-003", "type": "health", "severity": "critical",
             "message": "Emergency: Ryan (AST-003) - ...", "created_at": "2026-10-26T13:48:39Z",
             "acknowledged": false },
  "imputed": []
}
```
`alert` is `null` when no new alert was created (Normal/Attention, or an open alert of the
same or higher severity already exists for that astronaut).

## 2) GET /risk-score/{astronaut_id}

```json
{
  "astronaut_id": "AST-001", "timestamp": "2026-10-05T10:00:05Z",
  "risk_score": 62, "level": "High Risk",
  "top_factors": [ {"feature": "sleep_hours", "change_pct": -30},
                   {"feature": "hr", "change_pct": 12} ],
  "recommendation": "Increase recovery period and reduce training load today",
  "explanation": {
    "reasons": [
      {"feature": "spo2", "text": {"en": "Blood oxygen (SpO2) is 4.6 points below your normal (92.9% vs 97.5%)"}},
      {"feature": "temp", "text": {"en": "Body temperature is 0.9 °C above your normal (37.7 vs 36.8 °C)"}}
    ],
    "summary": {"en": "..."},
    "recommendation": {"en": "Check oxygen supply and re-measure SpO2 at rest"}
  }
}
```
404 until the first reading for that astronaut has been processed.

`explanation` (**v1.1, optional, additive**) comes from Shimaa's Digital Twin: up to 3 reasons, only changes in the
harmful direction, each as a plain-English sentence ready to show in the app. For a normal reading
`reasons` is `[]` and `summary` says all values are within the personal normal pattern. It can be `null`.
Clients that ignore unknown keys keep working. `POST /health-data` returns the same field.

`fusion` (**v1.2, optional, additive**) comes from Mariam's Data Fusion: what was fused for this score.

```json
"fusion": {
  "vitals": {"hr": 93.3, "hrv": 31.8, "spo2": 92.9, "resp_rate": 20.1, "temp": 37.7, "sleep_hours": 3.7, "sleep_quality": 0.5, "activity": 0.1},
  "suit": {"cabin_pressure_kpa": 101.24, "suit_temp_c": 21.21, "o2_pct": 20.87, "co2_pct": 0.048},
  "vision": {"posture_score": 0.67, "movement_quality": 0.53, "fatigue_indicator": 0.95},
  "fatigue_risk": null, "fatigue_level": "High",
  "environment_flags": [],
  "imputed": []
}
```
`environment_flags` lists measured suit values outside the cabin limits, each with `field`, `value`, `limit`,
`direction` and `text` (English). `imputed` lists the fields fusion had to fill.

## 3) GET /astronaut-profile/{astronaut_id}

```json
{
  "astronaut_id": "AST-001", "name": "Ethan Cole", "mission_day": 42, "status": "Normal",
  "baseline": { "hr": [56.47, 68.33], "hrv": [51.513, 70.787], "spo2": [96.61, 98.39],
                "sleep_hours": 6.905, "temp": [36.393, 36.987], "activity": 0.527 },
  "recovery_score": 78
}
```
Values come from Shimaa's Digital Twin v1.1: ranges are median ± 2 robust SD of the calibration days
(mission days 1–14). They hold ≥ 91 % of the astronaut's normal readings, so the app can show them as
"your normal range"; single numbers are the median. Values have decimals (e.g. `"hr": [56.47, 68.33]`).
`recovery_score` is an integer at the top level, not inside `baseline`. Ignore any key you
don't use. `status` = level of the latest reading.

## 4) GET /alerts?astronaut_id=&type=&acknowledged=&limit=

```json
[ { "id": 17, "astronaut_id": "AST-003", "type": "health", "severity": "critical",
    "message": "Possible fatigue detected", "created_at": "2026-10-05T10:00:06Z",
    "acknowledged": false } ]
```
Order: unacknowledged first → most severe → newest (**Emergency first**).
Visibility: astronaut = own health alerts · doctor = all health alerts · ground/admin = health + security.
Security alerts have `astronaut_id: null`.

## Extras (added on top of v1, non-breaking)

### GET /crew  (doctor, ground)
```json
[ { "astronaut_id": "AST-003", "name": "Ryan Mitchell", "mission_day": 60, "status": "Emergency",
    "risk_score": 100, "level": "Emergency", "last_update": "2026-10-22T18:00:00Z",
    "open_alerts": 1 } ]
```
`risk_score`, `level`, `last_update` are `null` before the first reading.

### GET /risk-history/{astronaut_id}?limit=500
```json
{ "astronaut_id": "AST-002",
  "points": [ {"timestamp": "2026-10-02T12:00:00Z", "risk_score": 3, "level": "Normal"},
              {"timestamp": "2026-10-22T12:00:00Z", "risk_score": 41, "level": "Attention"} ] }
```
Oldest first, ready for a line chart.

### POST /alerts/{id}/ack  (doctor, ground)
Returns the updated alert. Idempotent.

### GET /security-events?event_type=&limit=  (ground)
```json
[ { "id": 9, "ts": "2026-10-05T09:58:00Z", "event_type": "account_locked",
    "username": "ethan", "ip": "10.0.0.23", "details": "5 failed attempts" } ]
```
`event_type`: `login_success` | `login_failed` | `account_locked` | `login_while_locked` | `forbidden` | `invalid_token`.

### GET /space-weather (astronaut, doctor, ground)
NASA space weather at the current mission time (mission day 1 = 2024-08-25, real NASA data):
```json
{"nasa_time": "2024-10-10T22:00Z", "mission_day": 47, "kp": 8.7, "dst_nt": -243,
 "geomagnetic": {"level": "G4", "label": "Severe storm"},
 "radiation": {"active": true, "level": "severe", "text": "Solar radiation storm: >100 MeV protons at Earth orbit",
               "event": {"kind": "SEP", "id": "2024-10-09T03:50:00-SEP-001", "time": "2024-10-09T03:50Z", "link": "https://ccmc.gsfc.nasa.gov/DONKI/view/SEP/...", "detail": "GOES-P: SEISS >100 MeV", "storm_start": "2024-10-09T03:50Z"}},
 "kp_last_7_days": [{"time": "2024-10-03T23:00Z", "kp": 2.3}, "... 168 hours"],
 "recent_events": ["... newest first, SEP and GST"],
 "sources": [{"name": "NASA OMNIWeb (GSFC SPDF), hourly Kp and Dst", "url": "..."}, {"name": "NASA DONKI ...", "url": "..."}]}
```
Space-weather alerts have `type: "space_weather"` and `astronaut_id: null` (crew-wide); ground sees them.

### GET /comm/status (doctor, ground) · POST /comm/blackout {"seconds": 20} (ground)
Simulated space-to-ground downlink: what is queued, in flight and delivered, with priorities.

---

## Python functions the backend calls (AI team, agreed day 1)

```python
# AI 1 - Digital Twin (Shimaa)
get_baseline(astronaut_id: str) -> dict          # the Astronaut Profile
compute_deviation(reading: dict, baseline: dict) -> dict   # % deviation per metric

# AI 3 - Data Fusion (Mariam)
build_health_vector(wearable: dict, suit: dict, vision: dict, baseline: dict) -> dict

# AI 2 - Risk (Menna)
predict_risk(vector: dict) -> dict   # {risk_score, level, top_factors, recommendation}
```
Where to put them and the integration rules: [ai_modules/README.md](../ai_modules/README.md).

## Change log

| Version | Day | Change |
|---|---|---|
| 1.0 | 4 | Initial contract (Annex 2) + extras above |
| 1.3 (NASA data, additive) | — | `GET /space-weather`; alert type `space_weather` (crew-wide radiation / geomagnetic storm alerts from NASA DONKI + OMNIWeb) |
| 1.2 (Mariam live, additive) | — | `fusion` in `/risk-score` (Mariam's Core v1.0: `fatigue_risk` in the vector is "Low" / "Medium" / "High"); the vector also holds `environment_flags`. Explanations are English only. A shown `risk_score` always lies inside its `level`'s band (49.9 + Attention is shown as 49) |
| 1.1 (Menna live) | — | Risk scores come from Menna's model v1.1.0; its extra `anomaly_score` (0-1) is not exposed by the API (contract keys unchanged). The stored vector also holds `<k>_s` (24 h means of the deviations) |
| 1.1 (additive) | — | `explanation` in `/risk-score` and `POST /health-data`; profile ranges = median ± 2 robust SD; the stored model vector also holds AI 1's training-identical history features (rolling means, sleep debt, stress, `<m>_pct_dev`) next to AI 3's `<m>_dev_pct` — the team should pick one deviation naming |
| 1.0 (no breaking change) | — | Shimaa's Digital Twin is live. Answers to her open questions: extra profile keys (`baseline_detail`, `calibration`) are accepted and stored but not exposed by `/astronaut-profile`; `recovery_score` stays top-level (integer); `compute_deviation` stays flat; no % for `temp` — in `top_factors`, `temp`'s `change_pct` is the difference in °C from 36.7 |
