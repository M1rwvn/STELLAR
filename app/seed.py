"""Seed users, the 3 demo astronauts and their baselines (idempotent).

Run manually:  python -m app.seed
It also runs on API startup when SEED_ON_STARTUP=true.
"""
import os
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai
from app.models import Astronaut, Baseline, User
from app.security import hash_password

ASTRONAUTS = [
    ("AST-001", "Ethan Cole", "ethan"),
    ("AST-002", "Emily Carter", "emily"),
    ("AST-003", "Ryan Mitchell", "ryan"),
]

STAFF = [("admin", "admin"), ("doctor", "doctor"), ("ground", "ground"), ("device", "device")]


def seed(db: Session, refresh_baselines: bool = True) -> None:
    # Development-only password shared by all seeded accounts; set SEED_PASSWORD in .env
    password = os.getenv("SEED_PASSWORD", "astro123")
    password_hash: str | None = None

    def ensure_user(username: str, role: str) -> User:
        nonlocal password_hash
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            password_hash = password_hash or hash_password(password)
            user = User(username=username, password_hash=password_hash, role=role,
                        failed_attempts=0)
            db.add(user)
            db.flush()
        return user

    for username, role in STAFF:
        ensure_user(username, role)

    for astronaut_id, name, username in ASTRONAUTS:
        user = ensure_user(username, "astronaut")
        astronaut = db.get(Astronaut, astronaut_id)
        if astronaut is None:
            db.add(Astronaut(id=astronaut_id, name=name, mission_day=1, status="Normal",
                             user_id=user.id))
            db.flush()

        row = db.get(Baseline, astronaut_id)
        if row is None or refresh_baselines:
            profile = ai.get_baseline(astronaut_id)  # AI 1 (real module if installed)
            if row is None:
                db.add(Baseline(astronaut_id=astronaut_id, data_json=profile,
                                updated_at=datetime.now(timezone.utc)))
            else:
                row.data_json = profile
                row.updated_at = datetime.now(timezone.utc)

    db.commit()


if __name__ == "__main__":
    from app.database import Base, SessionLocal, engine

    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        seed(session)
    print("Seed done: users", [u for u, _ in STAFF] + [a[2] for a in ASTRONAUTS])
