# Demo plan (days 32 & 35) — backend side

Ghandor runs the demo from behind the scenes: replay script, Swagger/logs, and the
architecture part of the pitch.

## Before the demo (checklist)

- [ ] Code freeze tag pushed (`git tag v1.0-demo`), no changes after day 31.
- [ ] `docker compose up --build` on the demo laptop, `GET /health` → `"status": "ok"`.
- [ ] `GET /health` shows which AI modules are `real`; `python -m pytest` all green.
- [ ] DB backup taken: `./scripts/backup_db.sh`.
- [ ] Plan B tested **with Wi-Fi off**: `scripts\run_local.bat` + replay.
- [ ] Screen recording of the full flow (backup if everything fails).
- [ ] Dashboard (Marwan) and Flutter app (Lena) pointed at the demo laptop IP, logged in as `ground` and `ryan`.
- [ ] Terminal font large, colours on.

## Reset to a clean state

```bash
docker compose down -v && docker compose up --build -d      # Docker
scripts\run_local.bat -Reset                                # Plan B
```

## Script (≈ 4 minutes)

| Time | Who | What happens on screen |
|---|---|---|
| 0:00 | Ghandor | Architecture slide: Edge → Secure Comm → Backend → Apps (30 s) |
| 0:30 | Ghandor | Start: `python scripts/replay.py --start-day 45 --every-hours 6 --interval 0.3` (~10 s warm-up + ~2 min) — coloured log, alerts always shown |
| 0:45 | Shimaa | Figure 1 (`outputs/figures/fig1_why_digital_twin.png` in her repo): a 100 bpm alarm never fires for Ryan, his personal range flags day 56 |
| 1:30 | Menna | Emily's risk curve (`/risk-history/AST-002`) sliding green → yellow, top factors "sleep −25%, HR +19%" |
| 2:15 | everyone | Day 56: Ryan early warning (High Risk alert) → day 57: **Emergency**; the screen shows "Blood oxygen (SpO2) is 4.6 points below your normal" |
| 2:45 | Ghandor | `/comm/status`: Emergency left before routine data; (optional) blackout demo below |
| 3:15 | Marwan | Security: failed logins → account locked → security alert |
| 3:40 | Ghandor | Doctor acknowledges the alert (`POST /alerts/{id}/ack`) → disappears from the open list |

### Optional: loss-of-signal demo (30 s)

```bash
# as ground in Swagger: POST /comm/blackout {"seconds": 20}
python scripts/replay.py --start-day 55 --end-day 58 --daily --interval 0.3
# GET /comm/status -> everything "queued"; after 20 s the Emergency is sent first
```

## Plan B ladder

| Problem | Fallback |
|---|---|
| Venue internet down | Everything runs on the laptop (Docker or Plan B SQLite); phones/dashboard on the laptop hotspot |
| Docker broken | `scripts\run_local.bat` (SQLite, no Docker) |
| A real AI model crashes | Automatic stub fallback per request (logged); or set `AI_MODE=stub` |
| DB corrupted | `./scripts/restore_db.sh backups/<file>.sql` or `-Reset` + replay |
| Laptop dies | Recorded video + slides |

## Architecture talking points (task 19)

1. **Edge processing:** risk is computed next to the astronaut in milliseconds — Mars delay is up to ~22 minutes.
2. **Secure communication:** JWT + roles, lockout, audit log, TLS in deployment.
3. **Priority over a slow link:** Emergency messages jump the queue; data waits safely during blackout.
4. **Robust by design:** missing sensors are filled and flagged, AI failures fall back, offline mode.
5. **Open contract:** each team member plugged in their module without changing the backend.
