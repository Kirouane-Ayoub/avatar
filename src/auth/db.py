"""App database — users + per-user profile.

Uses the existing postgres-memory container (same DB as Mem0). The
users table sits alongside Mem0's lisa_memories. Splitting later is
just an env-var swap (APP_PG_*).

This module owns:
  - the connection pool (psycopg_pool, shared across the agent + token server)
  - the schema (users table — created on init() if absent)
  - typed CRUD helpers (get_user_by_id, get_user_by_username, create_user,
    update_profile)

Why connection pool: the token server has many short-lived requests
(login, signup, /api/me) and the agent has long-lived sessions that
do occasional reads. A pool covers both efficiently without per-request
connection overhead.

Concurrency: psycopg_pool is thread-safe and supports both sync and
async usage. We use sync calls (pool.connection() context manager)
because the token server is sync and the agent's auth lookups happen
on async-to-thread boundaries (cheap, infrequent).

Best-effort init: missing the postgres-memory container at startup
should NOT crash. Callers get clear errors when they try to use it.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from config import Config

logger = logging.getLogger("db")


# Schema. Idempotent — IF NOT EXISTS / IF EXISTS so init() is safe to
# re-run. pgcrypto gives us gen_random_uuid() for primary keys; it
# ships with the pgvector image so no extra install needed.
#
# Architecture: users authenticate; AVATARS are the chat-context
# entities. A user can own multiple avatars (different personas, voices,
# 3D models). Each avatar's id is what Mem0 keys memories by — so
# memories are per-avatar, not per-user. This is what makes "Lisa
# remembers your dog" different from "Marcus remembers your dog".
#
# `mood` is intentionally NOT on avatars — it's a transient UI preview
# value during the wizard, then the LLM/watcher take over per-turn.
_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    username        TEXT         UNIQUE NOT NULL,
    password_hash   TEXT         NOT NULL,
    display_name    TEXT         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS users_username_idx ON users (username);

-- Drop the legacy per-user profile columns. Their data moved to the
-- avatars table (where it conceptually belongs); existing rows under
-- those columns are abandoned. IF EXISTS makes this idempotent on
-- fresh installs that never had the columns.
ALTER TABLE users DROP COLUMN IF EXISTS persona;
ALTER TABLE users DROP COLUMN IF EXISTS voice;
ALTER TABLE users DROP COLUMN IF EXISTS avatar;
ALTER TABLE users DROP COLUMN IF EXISTS mood;
ALTER TABLE users DROP COLUMN IF EXISTS tools_json;

CREATE TABLE IF NOT EXISTS avatars (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    -- ON DELETE CASCADE: deleting the user auto-removes their avatars.
    -- Mem0 memories under each avatar.id need to be wiped separately
    -- BEFORE the user delete (see _handle_delete_me in ui/server.py).
    user_id         UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT         NOT NULL,
    persona         TEXT,
    voice           TEXT,
    avatar_key      TEXT,                            -- 3D model key from ui/data/avatars
    tools_json      TEXT,                            -- JSON array of enabled tool ids
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    -- Touched on every session start; lets the UI sort "recently chatted with"
    last_used_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS avatars_user_id_idx ON avatars (user_id);
CREATE INDEX IF NOT EXISTS avatars_last_used_idx ON avatars (user_id, last_used_at DESC);
"""


@dataclass(frozen=True)
class User:
    """Row from the users table — auth/identity only. No avatar/persona
    fields; those live on the avatars table now."""

    id: str
    username: str
    display_name: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Avatar:
    """Row from the avatars table — one chat-context entity owned by a
    user. Each avatar has its own persona, voice, 3D model, tool set,
    and (via Mem0 keyed by avatar.id) its own memory.
    """

    id: str
    user_id: str
    name: str
    persona: Optional[str]
    voice: Optional[str]
    avatar_key: Optional[str]
    tools: list  # decoded from tools_json
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime


class Db:
    """Thin wrapper around psycopg_pool with our typed CRUD methods."""

    def __init__(self, config: Config) -> None:
        # Connection string — stays in memory only, never logged.
        conninfo = (
            f"host={config.app_pg_host} port={config.app_pg_port} "
            f"user={config.app_pg_user} password={config.app_pg_password} "
            f"dbname={config.app_pg_dbname}"
        )
        # min_size=1, max_size=10 is plenty for token server + agent.
        # open=False because we open lazily on first use — keeps
        # `import db` from blocking on a missing postgres at import
        # time (tests, dev without docker).
        self._pool = ConnectionPool(
            conninfo=conninfo, min_size=1, max_size=10, open=False, kwargs={"row_factory": dict_row}
        )
        self._opened = False
        logger.info(
            "Db initialized (pool not yet opened): %s:%d/%s",
            config.app_pg_host, config.app_pg_port, config.app_pg_dbname,
        )

    def init(self) -> None:
        """Open the pool and create the schema if absent. Safe to call
        many times — schema is idempotent."""
        if not self._opened:
            self._pool.open()
            self._opened = True
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_SCHEMA)
        logger.info("users table ready")

    def close(self) -> None:
        if self._opened:
            self._pool.close()
            self._opened = False

    # ── CRUD ────────────────────────────────────────────────────────────
    def get_user_by_id(self, user_id: str) -> Optional[User]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
                row = cur.fetchone()
                return _row_to_user(row) if row else None

    def get_user_by_username(self, username: str) -> Optional[User]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM users WHERE username = %s", (username.lower(),)
                )
                row = cur.fetchone()
                return _row_to_user(row) if row else None

    def create_user(
        self,
        username: str,
        password_hash: str,
        display_name: str,
    ) -> User:
        """Insert a new user. Caller hashes the password (auth.py owns
        bcrypt). Raises psycopg.errors.UniqueViolation if the username
        is taken — token server maps that to HTTP 409."""
        new_id = str(uuid.uuid4())
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (id, username, password_hash, display_name)
                    VALUES (%s, %s, %s, %s)
                    RETURNING *
                    """,
                    (new_id, username.lower(), password_hash, display_name),
                )
                row = cur.fetchone()
                return _row_to_user(row)

    def delete_user(self, user_id: str) -> bool:
        """Hard-delete the user row. Returns True if a row was actually
        deleted, False if no such id existed (treated as idempotent
        success by callers).

        NOTE: this only touches the `users` table. Mem0 memories are
        wiped separately via memory.forget_user — they live in
        lisa_memories which Mem0 owns the schema of.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
                # rowcount is the number of rows the last SQL touched.
                return cur.rowcount > 0

    def update_display_name(self, user_id: str, display_name: str) -> Optional[User]:
        """The only mutable field on `users` post-refactor. Wizard /
        profile-edit calls this when the user changes their display
        name; everything else (persona, voice, etc.) lives on avatars."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET display_name = %s, updated_at = NOW() "
                    "WHERE id = %s RETURNING *",
                    (display_name, user_id),
                )
                row = cur.fetchone()
                return _row_to_user(row) if row else None

    # ── Avatars ─────────────────────────────────────────────────────────
    def list_avatars(self, user_id: str) -> list[Avatar]:
        """Return all avatars owned by this user, most-recently-chatted
        first. Used by GET /api/avatars and the AvatarPickerScreen."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM avatars WHERE user_id = %s ORDER BY last_used_at DESC",
                    (user_id,),
                )
                return [_row_to_avatar(row) for row in cur.fetchall()]

    def get_avatar(self, avatar_id: str) -> Optional[Avatar]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM avatars WHERE id = %s", (avatar_id,))
                row = cur.fetchone()
                return _row_to_avatar(row) if row else None

    def create_avatar(
        self,
        *,
        user_id: str,
        name: str,
        persona: Optional[str] = None,
        voice: Optional[str] = None,
        avatar_key: Optional[str] = None,
        tools: Optional[list] = None,
    ) -> Avatar:
        """Insert a new avatar for the given user. Required: user_id +
        name. All other fields optional — caller can fill them in
        later via update_avatar."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO avatars (user_id, name, persona, voice, avatar_key, tools_json)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        user_id, name, persona, voice, avatar_key,
                        json.dumps(tools) if tools is not None else None,
                    ),
                )
                row = cur.fetchone()
                return _row_to_avatar(row)

    def update_avatar(
        self,
        avatar_id: str,
        *,
        name: Optional[str] = None,
        persona: Optional[str] = None,
        voice: Optional[str] = None,
        avatar_key: Optional[str] = None,
        tools: Optional[list] = None,
        touch_last_used: bool = False,
    ) -> Optional[Avatar]:
        """Patch update — only fields passed as kwargs are written. Set
        `touch_last_used=True` to also bump last_used_at (called by
        /api/token on every session start)."""
        sets: list = []
        params: list = []
        if name is not None:
            sets.append("name = %s")
            params.append(name)
        if persona is not None:
            sets.append("persona = %s")
            params.append(persona)
        if voice is not None:
            sets.append("voice = %s")
            params.append(voice)
        if avatar_key is not None:
            sets.append("avatar_key = %s")
            params.append(avatar_key)
        if tools is not None:
            sets.append("tools_json = %s")
            params.append(json.dumps(tools))
        if touch_last_used:
            sets.append("last_used_at = NOW()")
        if not sets:
            return self.get_avatar(avatar_id)
        sets.append("updated_at = NOW()")
        params.append(avatar_id)
        sql = f"UPDATE avatars SET {', '.join(sets)} WHERE id = %s RETURNING *"
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                row = cur.fetchone()
                return _row_to_avatar(row) if row else None

    def delete_avatar(self, avatar_id: str) -> bool:
        """Hard-delete the avatar row. Mem0 memories under this avatar
        must be wiped separately via memory.forget(avatar_id) BEFORE
        calling this — Mem0 owns its schema."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM avatars WHERE id = %s", (avatar_id,))
                return cur.rowcount > 0


def _row_to_user(row: dict) -> User:
    """Translate a SELECT * row into a typed User."""
    return User(
        id=str(row["id"]),
        username=row["username"],
        display_name=row["display_name"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_avatar(row: dict) -> Avatar:
    """Translate a SELECT * row from the avatars table into a typed Avatar."""
    tools_json = row.get("tools_json")
    tools: list = []
    if tools_json:
        try:
            decoded = json.loads(tools_json)
            if isinstance(decoded, list):
                tools = decoded
        except (TypeError, json.JSONDecodeError):
            logger.warning("bad tools_json for avatar %s", row.get("id"))
    return Avatar(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        name=row["name"],
        persona=row.get("persona"),
        voice=row.get("voice"),
        avatar_key=row.get("avatar_key"),
        tools=tools,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_used_at=row["last_used_at"],
    )


# Module-level singleton so the agent and token server (running in the
# same Python process) share one pool. Set up via init_db(config).
_db: Optional[Db] = None


def init_db(config: Config) -> Db:
    """Initialize the singleton, open the pool, create the schema.
    Safe to call multiple times — returns the existing singleton on
    subsequent calls."""
    global _db
    if _db is None:
        _db = Db(config)
        _db.init()
    return _db


def get_db() -> Db:
    """Get the singleton. Raises if init_db() wasn't called first —
    surfaces the misconfiguration loudly instead of silently failing."""
    if _db is None:
        raise RuntimeError(
            "db.get_db() called before init_db(config) — "
            "the token server / agent should call init_db(Config.from_env()) at startup"
        )
    return _db
