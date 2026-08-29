"""App database — users + per-user profile.

Uses the existing postgres-memory container (same DB as Mem0). The
users table sits alongside Mem0's memories. Splitting later is
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

from psycopg.rows import dict_row
from psycopg.types.json import Json
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
# memories are per-avatar, not per-user. This is what makes "Sofia
# remembers your dog" different from "Marcus remembers your dog".
#
# `mood` is intentionally NOT on avatars — it's a transient UI preview
# value during the wizard, then the LLM/watcher take over per-turn.
# Per-avatar transcript retention cap. Opportunistically pruned on each
# INSERT so the table is bounded as the user base grows. 200 rows ≈ 100
# user turns + 100 assistant turns — far more than the 6-turn recall
# window needs, but enough headroom for ad-hoc debugging / future
# features that want a deeper trail.
TRANSCRIPT_RETENTION = 200


# Explicit column lists for every read/write. NEVER use `SELECT *` here:
# - `*` ships every column over the wire whether we use it or not (worst
#   on `users` where we'd otherwise leak `password_hash` into every
#   row dict — see _USER_PUBLIC vs _USER_WITH_HASH).
# - Schema additions silently expand the result set, which can break
#   row-to-dataclass mapping in subtle ways the type-checker won't catch.
# - Explicit columns make it possible to grep "where do we read X" and
#   to enable index-only scans later if a hot query gets that narrow.
#
# Order matters: it must match the dataclass field order in _row_to_*
# (we read by key, but the convention keeps reviewers honest).
_USER_PUBLIC = "id, username, display_name, created_at, updated_at"
_AVATAR_COLS = (
    "id, user_id, name, persona, voice, avatar_key, "
    "tools_json, proactive, vision_watcher, "
    "created_at, updated_at, last_used_at"
)
_TRANSCRIPT_COLS = "id, avatar_id, role, text, created_at"


_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    -- UNIQUE NOT NULL implicitly creates a unique index — no separate
    -- index needed. (We previously had a redundant `users_username_idx`
    -- here; the migration block below drops it on existing installs.)
    username        TEXT         UNIQUE NOT NULL,
    password_hash   TEXT         NOT NULL,
    display_name    TEXT         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

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
    tools_json      JSONB,                           -- JSON array of enabled tool ids
    -- Opt-in: when TRUE, the agent will proactively break silence and
    -- check in on the user (no help-desk energy, gated heavily). When
    -- FALSE (default), the avatar only speaks in response to user turns
    -- — quiet companion mode.
    proactive       BOOLEAN      NOT NULL DEFAULT FALSE,
    -- Per-avatar toggle for the ambient VisionWatcher. When TRUE
    -- (default — preserves prior behavior), the watcher periodically
    -- classifies the camera frame into a mood cue. When FALSE, no
    -- mood cues are emitted from camera; chat-time image injection
    -- still works (the camera is still useful for the LLM seeing you
    -- when you ask "do you like my shirt?"). Independent of the
    -- camera toggle: camera off ⇒ no frames ⇒ watcher idle anyway.
    vision_watcher  BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    -- Touched on every session start; lets the UI sort "recently chatted with"
    last_used_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
-- (avatars_user_id_idx is redundant — the composite below covers it via
-- the leftmost-prefix rule. Migration drops it on existing installs.)
CREATE INDEX IF NOT EXISTS avatars_last_used_idx ON avatars (user_id, last_used_at DESC);

-- Short-term memory: verbatim transcript per (avatar, turn). Used to
-- show the avatar "what we just talked about" at the next session
-- start (cross-session recency). Long-term semantic recall is Mem0's
-- job — this table is just the recent N raw lines, queried by
-- (avatar_id, created_at DESC LIMIT N) at session start.
--
-- ON DELETE CASCADE through avatar (and through user via avatar) so
-- delete-account / delete-avatar cleans these up automatically.
CREATE TABLE IF NOT EXISTS transcripts (
    id              BIGSERIAL    PRIMARY KEY,
    avatar_id       UUID         NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    role            TEXT         NOT NULL CHECK (role IN ('user', 'assistant')),
    text            TEXT         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
-- Index drives the "last N for this avatar" query on every session start
-- AND the FK cascade lookup when an avatar is deleted.
CREATE INDEX IF NOT EXISTS transcripts_avatar_ts_idx
    ON transcripts (avatar_id, created_at DESC);

-- ── Migrations from earlier schema versions (idempotent) ───────────────
-- Drop indexes that turned out to be redundant. UNIQUE constraints and
-- composite indexes (via leftmost-prefix) cover the same lookups.
DROP INDEX IF EXISTS users_username_idx;
DROP INDEX IF EXISTS avatars_user_id_idx;

-- Backfill: existing avatar rows from before the proactive feature
-- need the column added (CREATE TABLE IF NOT EXISTS skips it on
-- existing tables). Default FALSE — opt-in.
ALTER TABLE avatars ADD COLUMN IF NOT EXISTS proactive BOOLEAN NOT NULL DEFAULT FALSE;
-- Default TRUE preserves prior behavior (watcher always ran whenever
-- VLM was configured) for any avatar created before the column existed.
ALTER TABLE avatars ADD COLUMN IF NOT EXISTS vision_watcher BOOLEAN NOT NULL DEFAULT TRUE;

-- Convert avatars.tools_json from TEXT to JSONB. Wrapped in a DO block
-- so it only fires when the column is still TEXT — re-running on JSONB
-- would error. Empty strings become NULL (JSONB can't parse "").
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'avatars'
      AND column_name = 'tools_json'
      AND data_type = 'text'
  ) THEN
    ALTER TABLE avatars ALTER COLUMN tools_json TYPE JSONB
      USING NULLIF(tools_json, '')::jsonb;
  END IF;
END
$$;
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
class Transcript:
    """One verbatim turn of the conversation. Cheap raw history —
    different from Mem0's distilled facts. Used to give the avatar
    cross-session short-term recall ("we were just talking about X")."""

    id: int
    avatar_id: str
    role: str  # "user" or "assistant"
    text: str
    created_at: datetime


@dataclass(frozen=True)
class Avatar:
    """Row from the avatars table — one chat-context entity owned by a
    user. Each avatar has its own persona, voice, 3D model, tool set,
    and (via Mem0 keyed by avatar.id) its own memory.
    """

    id: str
    user_id: str
    name: str
    persona: str | None
    voice: str | None
    avatar_key: str | None
    tools: list  # decoded from tools_json
    # Whether this avatar should proactively break silence (per-avatar
    # opt-in). Drives src/proactive.py at session start. Off by default
    # — quiet companion mode is the safer baseline.
    proactive: bool
    # Whether the ambient VisionWatcher runs for this avatar. ON by
    # default to preserve historical behavior. Doesn't affect chat-time
    # camera frame injection (that's still active whenever the camera
    # track is published).
    vision_watcher: bool
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
            conninfo=conninfo,
            min_size=1,
            max_size=10,
            open=False,
            kwargs={"row_factory": dict_row},
        )
        self._opened = False
        logger.info(
            "Db initialized (pool not yet opened): %s:%d/%s",
            config.app_pg_host,
            config.app_pg_port,
            config.app_pg_dbname,
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
    def get_user_by_id(self, user_id: str) -> User | None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {_USER_PUBLIC} FROM users WHERE id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
                return _row_to_user(row) if row else None

    def get_user_by_username(self, username: str) -> User | None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {_USER_PUBLIC} FROM users WHERE username = %s",
                    (username.lower(),),
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
                    f"""
                    INSERT INTO users (id, username, password_hash, display_name)
                    VALUES (%s, %s, %s, %s)
                    RETURNING {_USER_PUBLIC}
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
        the memories table which Mem0 owns the schema of.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
                # rowcount is the number of rows the last SQL touched.
                return cur.rowcount > 0

    def update_display_name(self, user_id: str, display_name: str) -> User | None:
        """The only mutable field on `users` post-refactor. Wizard /
        profile-edit calls this when the user changes their display
        name; everything else (persona, voice, etc.) lives on avatars."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE users SET display_name = %s, updated_at = NOW() "
                    f"WHERE id = %s RETURNING {_USER_PUBLIC}",
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
                    f"SELECT {_AVATAR_COLS} FROM avatars "
                    f"WHERE user_id = %s ORDER BY last_used_at DESC",
                    (user_id,),
                )
                return [_row_to_avatar(row) for row in cur.fetchall()]

    def get_avatar(self, avatar_id: str) -> Avatar | None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {_AVATAR_COLS} FROM avatars WHERE id = %s",
                    (avatar_id,),
                )
                row = cur.fetchone()
                return _row_to_avatar(row) if row else None

    def create_avatar(
        self,
        *,
        user_id: str,
        name: str,
        persona: str | None = None,
        voice: str | None = None,
        avatar_key: str | None = None,
        tools: list | None = None,
        proactive: bool = False,
        vision_watcher: bool = True,
    ) -> Avatar:
        """Insert a new avatar for the given user. Required: user_id +
        name. All other fields optional — caller can fill them in
        later via update_avatar."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO avatars
                        (user_id, name, persona, voice, avatar_key,
                         tools_json, proactive, vision_watcher)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING {_AVATAR_COLS}
                    """,
                    (
                        user_id,
                        name,
                        persona,
                        voice,
                        avatar_key,
                        # Json() wraps the list so psycopg sends it to the
                        # JSONB column with the right type adapter (without
                        # this, psycopg would try str-cast and Postgres would
                        # reject the cast).
                        Json(tools) if tools is not None else None,
                        proactive,
                        vision_watcher,
                    ),
                )
                row = cur.fetchone()
                return _row_to_avatar(row)

    def update_avatar(
        self,
        avatar_id: str,
        *,
        name: str | None = None,
        persona: str | None = None,
        voice: str | None = None,
        avatar_key: str | None = None,
        tools: list | None = None,
        proactive: bool | None = None,
        vision_watcher: bool | None = None,
        touch_last_used: bool = False,
    ) -> Avatar | None:
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
            params.append(Json(tools))
        if proactive is not None:
            sets.append("proactive = %s")
            params.append(proactive)
        if vision_watcher is not None:
            sets.append("vision_watcher = %s")
            params.append(vision_watcher)
        if touch_last_used:
            sets.append("last_used_at = NOW()")
        if not sets:
            return self.get_avatar(avatar_id)
        sets.append("updated_at = NOW()")
        params.append(avatar_id)
        sql = (
            f"UPDATE avatars SET {', '.join(sets)} "
            f"WHERE id = %s RETURNING {_AVATAR_COLS}"
        )
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

    # ── Transcripts (cross-session short-term memory) ───────────────────
    def delete_transcripts(self, avatar_id: str) -> int:
        """Wipe every transcript row for this avatar. Returns the count
        of rows deleted, so the UI / caller can show "cleared N
        messages." Mem0 facts live in a separate table — call
        memory.forget(avatar_id) alongside this for a full reset.

        Used by the per-avatar "Forget memory" UI action and by the
        delete-avatar flow's memory cleanup path.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM transcripts WHERE avatar_id = %s",
                    (avatar_id,),
                )
                return cur.rowcount

    def record_transcript(self, avatar_id: str, role: str, text: str) -> None:
        """Append one verbatim turn to the transcripts table. Called for
        BOTH user and assistant turns. Cheap insert; no LLM in the
        path. The row's id auto-increments via BIGSERIAL.

        After the insert, opportunistically prunes the avatar's history
        to TRANSCRIPT_RETENTION rows so the table is bounded as the user
        base grows. The prune subquery uses transcripts_avatar_ts_idx
        with OFFSET to find the cutoff timestamp; under the cap, the
        subquery returns NULL and the DELETE is a no-op.

        Best-effort: a DB hiccup shouldn't break the conversation. The
        agent calls this via `asyncio.to_thread(...)` then ignores any
        exception so the failure doesn't bubble into the voice loop.
        """
        if not text or not text.strip():
            return
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO transcripts (avatar_id, role, text) VALUES (%s, %s, %s)",
                    (avatar_id, role, text),
                )
                # Cap rows per avatar. Cheap with the index — index seek to
                # the (TRANSCRIPT_RETENTION)th newest row, then drop everything
                # older. No-op when the avatar is under cap.
                cur.execute(
                    """
                    DELETE FROM transcripts
                    WHERE avatar_id = %s
                      AND created_at < (
                          SELECT created_at FROM transcripts
                          WHERE avatar_id = %s
                          ORDER BY created_at DESC
                          OFFSET %s LIMIT 1
                      )
                    """,
                    (avatar_id, avatar_id, TRANSCRIPT_RETENTION - 1),
                )

    def recent_transcripts(self, avatar_id: str, limit: int = 20) -> list[Transcript]:
        """Return the most recent N turns for this avatar in
        CHRONOLOGICAL order (oldest first), so the system prompt can
        present them as a normal dialogue. Internally we ORDER BY DESC
        then reverse — that way the index covers the "last N" query
        even as the table grows.
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {_TRANSCRIPT_COLS} FROM transcripts "
                    f"WHERE avatar_id = %s ORDER BY created_at DESC LIMIT %s",
                    (avatar_id, limit),
                )
                rows = cur.fetchall()
        # Flip to chronological for prompt injection.
        return list(reversed([_row_to_transcript(r) for r in rows]))


def _row_to_user(row: dict) -> User:
    """Translate a row (columns from _USER_PUBLIC) into a typed User.
    `password_hash` is NOT in the row — that's fetched via a dedicated
    query in auth/flows.py only when verifying credentials."""
    return User(
        id=str(row["id"]),
        username=row["username"],
        display_name=row["display_name"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_transcript(row: dict) -> Transcript:
    """Translate a row (columns from _TRANSCRIPT_COLS) into a typed Transcript."""
    return Transcript(
        id=int(row["id"]),
        avatar_id=str(row["avatar_id"]),
        role=row["role"],
        text=row["text"],
        created_at=row["created_at"],
    )


def _row_to_avatar(row: dict) -> Avatar:
    """Translate a row (columns from _AVATAR_COLS) into a typed Avatar.

    `tools_json` is JSONB, so psycopg returns it pre-parsed (list/dict/None).
    The `json.loads` branch is a backstop for the brief migration window
    where an existing install hasn't yet hit the TEXT→JSONB ALTER.
    """
    tools_json = row.get("tools_json")
    tools: list = []
    if isinstance(tools_json, list):
        tools = tools_json
    elif isinstance(tools_json, str) and tools_json:
        # Pre-migration fallback: column was still TEXT, value is a JSON
        # string. Decode defensively — bad data shouldn't crash list_avatars.
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
        proactive=bool(row.get("proactive", False)),
        vision_watcher=bool(row.get("vision_watcher", True)),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_used_at=row["last_used_at"],
    )


# Module-level singleton so the agent and token server (running in the
# same Python process) share one pool. Set up via init_db(config).
_db: Db | None = None


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
