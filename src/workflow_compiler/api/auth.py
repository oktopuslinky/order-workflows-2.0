"""Local-account authentication for the HTTP API.

Design (deliberately dependency-free, matching the local-first architecture):

- Passwords are hashed with stdlib ``hashlib.scrypt`` (n=2**14, r=8, p=1,
  16-byte random salt) and compared in constant time.
- Sessions are an HMAC-SHA256-signed token ``<user_id>.<expiry>.<signature>``
  carried in an HttpOnly, SameSite=Lax cookie — no JWT library, no server-side
  session state.
- The signing secret comes from ``WORKFLOW_COMPILER_SESSION_SECRET`` or, when
  unset, a ``session_secret`` file generated once under the state-store root so
  restarts don't invalidate sessions.

This protects the HTTP surface only. The CLI drives the compiler directly and
is intentionally unauthenticated — appropriate for a local tool whose state
lives in files the operator already owns.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from functools import lru_cache
from pathlib import Path

from fastapi import Cookie, Depends, HTTPException, Response, status

from workflow_compiler.config import get_settings
from workflow_compiler.exceptions import StateNotFoundError
from workflow_compiler.models.user import User
from workflow_compiler.storage.user_store import UserStore

SESSION_COOKIE = "wc_session"

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """Return ``(hex_digest, hex_salt)`` for storing a password."""
    salt = salt if salt is not None else secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    return digest.hex(), salt.hex()


def verify_password(password: str, password_hash: str, password_salt: str) -> bool:
    """Constant-time check of ``password`` against a stored hash + salt."""
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=bytes.fromhex(password_salt),
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
    )
    return hmac.compare_digest(digest.hex(), password_hash)


@lru_cache(maxsize=1)
def _secret() -> bytes:
    """Resolve the session-signing secret (setting, else a persisted random one)."""
    settings = get_settings()
    if settings.session_secret:
        return settings.session_secret.encode("utf-8")
    path = Path(settings.state_store_path) / "session_secret"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip().encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    generated = secrets.token_hex(32)
    path.write_text(generated, encoding="utf-8")
    return generated.encode("utf-8")


def _signature(payload: str) -> str:
    return hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def sign_session(user_id: str, ttl_hours: float | None = None) -> str:
    """Create a signed session token for ``user_id``."""
    ttl = ttl_hours if ttl_hours is not None else get_settings().session_ttl_hours
    expiry = int(time.time() + ttl * 3600)
    payload = f"{user_id}.{expiry}"
    return f"{payload}.{_signature(payload)}"


def verify_session(token: str) -> str | None:
    """Return the token's user id, or ``None`` if invalid or expired."""
    payload, _, signature = token.rpartition(".")
    if not payload or not hmac.compare_digest(_signature(payload), signature):
        return None
    user_id, _, expiry = payload.rpartition(".")
    if not user_id or not expiry.isdigit() or int(expiry) < time.time():
        return None
    return user_id


def set_session_cookie(response: Response, user: User) -> None:
    """Attach a fresh session cookie for ``user`` to ``response``."""
    ttl_hours = get_settings().session_ttl_hours
    response.set_cookie(
        SESSION_COOKIE,
        sign_session(user.user_id),
        max_age=int(ttl_hours * 3600),
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Remove the session cookie."""
    response.delete_cookie(SESSION_COOKIE, path="/")


def get_user_store() -> UserStore:
    """Provide the process-wide user store (tests override this dependency)."""
    return _default_user_store()


@lru_cache(maxsize=1)
def _default_user_store() -> UserStore:
    from workflow_compiler.storage.user_store import FileUserStore

    return FileUserStore(get_settings().state_store_path)


async def get_current_user(
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    store: UserStore = Depends(get_user_store),
) -> User:
    """Resolve the signed-in user from the session cookie, or 401."""
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in.")
    user_id = verify_session(session)
    if user_id is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Session expired — sign in again."
        )
    try:
        return await store.load(user_id)
    except StateNotFoundError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Session expired — sign in again."
        ) from exc
