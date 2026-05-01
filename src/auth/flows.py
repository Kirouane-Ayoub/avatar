"""Auth — signup, login, session JWT.

This module owns every cryptographic decision:
  - Password hashing (bcrypt, 12 rounds — sensible default in 2026)
  - Session token issuance (HS256-signed JWT)
  - Session token verification (signature + expiry checks)

The token server (ui/server.py) calls signup() / login() and gets back
either a session JWT or a typed exception. The agent calls
decode_session_token() during identity resolution. Same JWT_SECRET
across both — they live in the same container and read the same .env.

Auth-specific exceptions are typed so the token server can map them
to clean HTTP responses (409 for username taken, 401 for bad creds,
401 for expired token) without leaking implementation details.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
import psycopg.errors

from config import Config

from .db import Db, User

logger = logging.getLogger("auth")


# ── Typed errors so the token server can return clean HTTP statuses ────
class AuthError(Exception):
    """Base for all auth-layer errors. Token server catches this."""


class UsernameTaken(AuthError):
    """create_user hit a UNIQUE constraint on username."""


class InvalidCredentials(AuthError):
    """Wrong username or password — deliberately one error type so the
    response body never leaks which one was wrong (timing attacks
    aside; bcrypt verify is constant-time enough for our threat model)."""


class InvalidToken(AuthError):
    """Session JWT is malformed, signature-invalid, or expired."""


class WeakPassword(AuthError):
    """Password didn't pass the minimum policy."""


# ── Username/password policy ────────────────────────────────────────────
# Lowercased, alphanumeric + underscore + dot + hyphen, 3-32 chars.
# Same restrictions as most chat/email handles. Tightening later is a
# one-regex change.
_USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,32}$")
_MIN_PASSWORD_LEN = 8


def _normalize_username(username: str) -> str:
    """Lowercase + strip. The DB stores lowercase, so login lookups
    are case-insensitive without needing CITEXT."""
    return (username or "").strip().lower()


def _validate_username(username: str) -> None:
    if not _USERNAME_RE.match(username):
        raise AuthError(
            "Username must be 3-32 chars: lowercase letters, digits, dot, dash, underscore."
        )


def _validate_password(password: str) -> None:
    if len(password) < _MIN_PASSWORD_LEN:
        raise WeakPassword(f"Password must be at least {_MIN_PASSWORD_LEN} characters.")


# ── Password hashing ────────────────────────────────────────────────────
def _hash_password(password: str) -> str:
    """bcrypt with 12 rounds. Returns the hash as a UTF-8 string for
    storing in TEXT columns."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        # Malformed hash in DB shouldn't crash login — reject as bad creds.
        logger.exception("bcrypt verify failed (malformed hash?)")
        return False


# ── Session JWT ─────────────────────────────────────────────────────────
_JWT_ALG = "HS256"


def issue_session_token(user: User, config: Config) -> str:
    """Sign a session JWT for this user. Lifetime = config.session_token_ttl_days.

    Claims (intentionally minimal):
      - sub:      user_id (the only identifier the agent uses to key memory etc.)
      - username: convenience for client-side display, NOT trusted by agent
      - iat:      issued-at (for audit / future revocation)
      - exp:      expires-at (enforced on every verify)
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.id,
        "username": user.username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=config.session_token_ttl_days)).timestamp()),
    }
    return jwt.encode(payload, config.jwt_secret, algorithm=_JWT_ALG)


def decode_session_token(token: str, config: Config) -> dict:
    """Verify signature + expiry, return the claims dict. Raises
    InvalidToken on any failure — token server catches this and
    responds 401."""
    if not token:
        raise InvalidToken("missing token")
    if not config.jwt_secret:
        # Misconfiguration — fail loud so we don't accidentally accept
        # any token in dev.
        raise InvalidToken("server misconfigured: no jwt_secret")
    try:
        return jwt.decode(token, config.jwt_secret, algorithms=[_JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise InvalidToken("token expired")
    except jwt.InvalidTokenError as e:
        raise InvalidToken(f"invalid token: {e}")


def user_id_from_token(token: str, config: Config) -> str:
    """Convenience: extract just the user_id from a verified token.
    Used by the agent's identity layer."""
    claims = decode_session_token(token, config)
    sub = claims.get("sub")
    if not sub:
        raise InvalidToken("token missing sub claim")
    return sub


# ── High-level flows ────────────────────────────────────────────────────
def signup(
    db: Db,
    config: Config,
    *,
    username: str,
    password: str,
    display_name: Optional[str] = None,
) -> tuple[User, str]:
    """Create a user + return (user, session_jwt) so the client is
    logged in immediately after signup.

    Raises:
      AuthError       — username didn't pass policy
      WeakPassword    — password too short
      UsernameTaken   — username already in use
    """
    username = _normalize_username(username)
    _validate_username(username)
    _validate_password(password)
    display_name = (display_name or "").strip() or username
    password_hash = _hash_password(password)
    try:
        user = db.create_user(
            username=username,
            password_hash=password_hash,
            display_name=display_name,
        )
    except psycopg.errors.UniqueViolation:
        raise UsernameTaken(f"username {username!r} is already taken")
    token = issue_session_token(user, config)
    logger.info("signup: created user_id=%s username=%s", user.id, user.username)
    return user, token


def login(
    db: Db,
    config: Config,
    *,
    username: str,
    password: str,
) -> tuple[User, str]:
    """Verify credentials + issue a session JWT.

    Raises InvalidCredentials for both "no such user" and "wrong
    password" — never leak which one was wrong.
    """
    username = _normalize_username(username)
    user = db.get_user_by_username(username)
    if user is None:
        # Run a dummy bcrypt check to keep timing roughly constant
        # against username enumeration.
        bcrypt.checkpw(b"x", b"$2b$12$" + b"x" * 53)
        raise InvalidCredentials("invalid username or password")
    # Need the password_hash which User dataclass deliberately doesn't
    # carry (so it can't be returned to clients). Re-fetch the raw
    # column directly via the pool — db.py exposes get_user_by_id /
    # get_user_by_username; for the hash we run a tiny dedicated query.
    password_hash = _fetch_password_hash(db, user.id)
    if not _verify_password(password, password_hash):
        raise InvalidCredentials("invalid username or password")
    token = issue_session_token(user, config)
    logger.info("login: user_id=%s username=%s", user.id, user.username)
    return user, token


def _fetch_password_hash(db: Db, user_id: str) -> str:
    """Pull the password_hash column for a user. Kept inline here
    rather than on the Db class because no other code path needs it
    — the hash should NEVER leave the auth module."""
    with db._pool.connection() as conn:  # noqa: SLF001 — intentional
        with conn.cursor() as cur:
            cur.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            return row["password_hash"] if row else ""
