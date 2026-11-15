"""Auth module: JWT, roles, account lockout, security events.

Ownership: Marwan (Security/Web 2) owns this module; Ghandor uses it in the
endpoints. The agreed integration point is `Depends(require_role([...]))`.
Marwan can harden it (refresh tokens, IDS hooks...) without touching routers
as long as `require_role`, `get_current_user` and `log_security_event` keep
their signatures.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import Alert, Astronaut, SecurityEvent, User

ROLES = ("astronaut", "doctor", "ground", "admin", "device")

bearer_scheme = HTTPBearer(auto_error=False, description="Paste the access_token from POST /login")

# Used to keep timing equal when the username does not exist
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt()).decode()


@dataclass
class CurrentUser:
    id: int
    username: str
    role: str
    astronaut_id: str | None  # set when role == "astronaut"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host


def log_security_event(db: Session, event_type: str, username: str | None = None,
                       ip: str | None = None, details: str | None = None) -> SecurityEvent:
    event = SecurityEvent(event_type=event_type, username=username, ip=ip, details=details)
    db.add(event)
    db.commit()
    return event


def create_access_token(user: User, astronaut_id: str | None) -> tuple[str, int]:
    settings = get_settings()
    expires_in = settings.jwt_expire_minutes * 60
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.username,
        "role": user.role,
        "astronaut_id": astronaut_id,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_in


def astronaut_id_for_user(db: Session, user: User) -> str | None:
    if user.role != "astronaut":
        return None
    return db.scalar(select(Astronaut.id).where(Astronaut.user_id == user.id))


class AccountLocked(Exception):
    pass


def authenticate(db: Session, username: str, password: str, ip: str | None) -> User | None:
    """Check credentials and apply the lockout policy. Returns the user or None."""
    settings = get_settings()
    user = db.scalar(select(User).where(User.username == username))
    now = datetime.now(timezone.utc)

    if user is None:
        verify_password(password, _DUMMY_HASH)
        log_security_event(db, "login_failed", username, ip, "unknown username")
        return None

    locked_until = _as_utc(user.locked_until)
    if locked_until and locked_until > now:
        log_security_event(db, "login_while_locked", username, ip,
                           f"locked until {locked_until.isoformat()}")
        raise AccountLocked()

    if not verify_password(password, user.password_hash):
        user.failed_attempts = (user.failed_attempts or 0) + 1
        if user.failed_attempts >= settings.max_failed_logins:
            user.failed_attempts = 0
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            db.add(Alert(
                astronaut_id=None, type="security", severity="high",
                message=f"Account '{username}' locked after {settings.max_failed_logins} "
                        f"failed logins (ip {ip})",
            ))
            db.commit()
            log_security_event(db, "account_locked", username, ip,
                               f"{settings.max_failed_logins} failed attempts")
        else:
            db.commit()
            log_security_event(db, "login_failed", username, ip,
                               f"bad password (attempt {user.failed_attempts})")
        return None

    user.failed_attempts = 0
    user.locked_until = None
    db.commit()
    log_security_event(db, "login_success", username, ip)
    return user


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> CurrentUser:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if creds is None:
        raise unauthorized
    settings = get_settings()
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret,
                             algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        log_security_event(db, "invalid_token", None, client_ip(request), "expired token")
        raise unauthorized
    except jwt.PyJWTError:
        log_security_event(db, "invalid_token", None, client_ip(request), "bad signature/format")
        raise unauthorized

    user = db.scalar(select(User).where(User.username == payload.get("sub")))
    if user is None:
        raise unauthorized
    return CurrentUser(
        id=user.id,
        username=user.username,
        role=user.role,
        astronaut_id=astronaut_id_for_user(db, user),
    )


def require_role(roles: list[str]):
    """Dependency factory: `Depends(require_role(["doctor", "ground"]))`.

    "admin" is always allowed.
    """
    allowed = set(roles) | {"admin"}

    def checker(
        request: Request,
        user: CurrentUser = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> CurrentUser:
        if user.role not in allowed:
            log_security_event(db, "forbidden", user.username, client_ip(request),
                               f"{request.method} {request.url.path} needs {sorted(allowed)}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Not allowed for your role")
        return user

    return checker


def ensure_can_access_astronaut(user: CurrentUser, astronaut_id: str, request: Request,
                                db: Session) -> None:
    """Astronauts may only see their own data; other allowed roles see everyone."""
    if user.role == "astronaut" and user.astronaut_id != astronaut_id:
        log_security_event(db, "forbidden", user.username, client_ip(request),
                           f"astronaut tried to access {astronaut_id}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Astronauts can only access their own data")
