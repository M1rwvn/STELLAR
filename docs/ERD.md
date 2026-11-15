# Database design (ERD)

PostgreSQL in Docker / production, SQLite for the offline Plan B — same models
(`app/models.py`), same migration (`migrations/versions/0001_initial_schema.py`).

```mermaid
erDiagram
    users ||--o| astronauts : "logs in as"
    astronauts ||--|| baselines : "has personal"
    astronauts ||--o{ health_readings : "sends"
    astronauts ||--o{ risk_scores : "gets"
    health_readings ||--o| risk_scores : "produces"
    astronauts ||--o{ alerts : "raises"

    users {
        int id PK
        string username UK
        string password_hash "bcrypt"
        string role "astronaut|doctor|ground|admin|device"
        int failed_attempts
        timestamptz locked_until
    }
    astronauts {
        string id PK "AST-001"
        string name
        int mission_day
        string status "latest level"
        int user_id FK
    }
    baselines {
        string astronaut_id PK,FK
        json data_json "profile from get_baseline()"
        timestamptz updated_at
    }
    health_readings {
        int id PK
        string astronaut_id FK
        timestamptz ts
        json wearable_json
        json suit_json
        json vision_json
        json vector_json "Unified Health Vector"
    }
    risk_scores {
        int id PK
        string astronaut_id FK
        int reading_id FK
        timestamptz ts
        float risk_score
        string level
        json top_factors_json
        text recommendation
    }
    alerts {
        int id PK
        string astronaut_id FK "NULL for security"
        string type "health|security"
        string severity "critical|high|medium|low"
        text message
        timestamptz created_at
        bool acknowledged
        string acknowledged_by
        timestamptz acknowledged_at
    }
    security_events {
        int id PK
        timestamptz ts
        string event_type
        string username
        string ip
        text details
    }
```

## Why it looks like this

- **Raw sensor groups as JSON** (`wearable_json`, `suit_json`, `vision_json`): the three
  sources evolve separately and the AI team may add fields; JSON keeps the schema stable
  while the contract validates every field on the way in.
- **`vector_json`** stores exactly what the risk model saw, so any score can be explained
  and re-computed later (useful for Menna's evaluation and for the demo).
- **`risk_scores` separate from readings**: the dashboard and charts read only this small
  table; `reading_id` links back to the raw data.
- **`baselines` one row per astronaut**: refreshed from `get_baseline()` on startup, so a
  new Digital Twin model is picked up by restarting the API.
- **`security_events`** is an append-only audit log for Marwan's IDS / dashboard;
  `alerts` with `type = security` are the ones a human must look at.

## Columns added beyond the brief

| Table | Column | Reason |
|---|---|---|
| health_readings | vector_json | keep the fused vector (Mariam: "vector is stored") |
| risk_scores | reading_id | trace each score to its reading |
| alerts | acknowledged_by, acknowledged_at | audit for `POST /alerts/{id}/ack` |
| alerts | astronaut_id nullable | security alerts are not about one astronaut |

## Indexes (task 16)

| Index | Serves |
|---|---|
| `health_readings (astronaut_id, ts)` | latest / history per astronaut |
| `risk_scores (astronaut_id, ts)` | `/risk-score`, `/risk-history`, `/crew` |
| `alerts (acknowledged, severity, created_at)` | Emergency-first alert list |
| `alerts (astronaut_id, created_at)` | per-astronaut alerts, de-duplication |
| `security_events (ts)` | latest security events |
| `users (username)` unique | login |
