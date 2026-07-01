"""
utils/auth.py
─────────────
JWT helpers and the FastAPI dependency used to protect routes.

Token payload:
    { "sub": "<student_id>", "email": "<email>", "name": "<name>", "exp": <unix_ts> }

NOTE: passlib is unmaintained and broken on Python 3.13 + bcrypt 4.x.
      We call bcrypt directly to avoid the incompatibility.
"""

from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from core.config import settings

# ── Password hashing ─────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Return a bcrypt hash of *plain* text password."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches the stored bcrypt *hashed* value."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ── JWT ──────────────────────────────────────────────────────────────────────
_bearer = HTTPBearer(auto_error=True)


def create_access_token(student_id: str, email: str, name: str) -> str:
    """
    Create a signed JWT access token.

    Payload fields:
        sub   – student's MongoDB _id (as string)
        email – student email (for convenience in downstream services)
        name  – student display name
        exp   – expiry timestamp (UTC)
    """
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.ACCESS_TOKEN_EXPIRE_DAYS
    )
    payload = {
        "sub": student_id,
        "email": email,
        "name": name,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def _decode_token(token: str) -> dict:
    """Decode and validate a JWT; raise 401 on any failure."""
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── FastAPI dependency ────────────────────────────────────────────────────────

class CurrentUser:
    """Thin struct holding the decoded token claims."""

    def __init__(self, student_id: str, email: str, name: str):
        self.student_id = student_id
        self.email = email
        self.name = name

    def __repr__(self) -> str:  # pragma: no cover
        return f"CurrentUser(id={self.student_id}, email={self.email})"


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> CurrentUser:
    """
    FastAPI dependency — extracts and validates the Bearer token.

    Usage in a router:
        @router.get("/me")
        async def me(user: CurrentUser = Depends(get_current_user)):
            return {"student_id": user.student_id}
    """
    payload = _decode_token(credentials.credentials)

    student_id: str | None = payload.get("sub")
    email: str | None = payload.get("email")
    name: str | None = payload.get("name")

    if not student_id or not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload is missing required fields.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return CurrentUser(student_id=student_id, email=email, name=name or "")
