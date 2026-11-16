"""Passwords, login sessions and login rate limiting."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt

COOKIE_NAME = "rahsaaf_session"
MIN_PASSWORD_LENGTH = 10

# scrypt cost settings: about 16 MB of memory and a few tens of milliseconds
# per check. That is nothing for one login, and expensive for someone trying
# millions of guesses against a stolen database.
_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    encode = lambda raw: base64.b64encode(raw).decode()  # noqa: E731
    return f"scrypt${_N}${_R}${_P}${encode(salt)}${encode(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            password.encode(),
            salt=base64.b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def load_or_create_secret(configured: str, path: Path) -> str:
    """The key that signs login sessions.

    Taken from SECRET_KEY if set. Otherwise one is generated once and kept in
    a file only this user can read, so sessions survive a server restart.
    """
    if configured:
        return configured
    if path.exists():
        return path.read_text().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(48)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(secret)
    return secret


def password_stamp(password_hash: str) -> str:
    """A short fingerprint of a stored password hash.

    Each login session carries the stamp of the password it was opened with.
    When the password changes, the stamp changes, and every session opened
    with the old password stops working at once.
    """
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def create_session_token(officer_id: int, secret: str, hours: float, stamp: str = "") -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(officer_id), "iat": now, "exp": now + timedelta(hours=hours), "pw": stamp}
    return jwt.encode(payload, secret, algorithm="HS256")


def read_session(token: str, secret: str) -> tuple[int, str] | None:
    """(officer ID, password stamp) from a valid, unexpired token; otherwise None."""
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return int(payload["sub"]), str(payload.get("pw", ""))
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def read_session_token(token: str, secret: str) -> int | None:
    """The officer ID in a valid, unexpired token; otherwise None."""
    session = read_session(token, secret)
    return session[0] if session else None


class LoginLimiter:
    """Locks out a username + address pair after repeated wrong passwords."""

    def __init__(self, max_failures: int = 5, lock_seconds: float = 300.0, clock=time.monotonic):
        self.max_failures = max_failures
        self.lock_seconds = lock_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: dict[tuple[str, str], tuple[int, float]] = {}

    def seconds_locked(self, username: str, address: str) -> float:
        with self._lock:
            count, since = self._failures.get((username.lower(), address), (0, 0.0))
            if count < self.max_failures:
                return 0.0
            remaining = self.lock_seconds - (self._clock() - since)
            if remaining <= 0:
                del self._failures[(username.lower(), address)]
                return 0.0
            return remaining

    def record_failure(self, username: str, address: str) -> None:
        key = (username.lower(), address)
        with self._lock:
            count, _ = self._failures.get(key, (0, 0.0))
            self._failures[key] = (count + 1, self._clock())

    def record_success(self, username: str, address: str) -> None:
        with self._lock:
            self._failures.pop((username.lower(), address), None)
