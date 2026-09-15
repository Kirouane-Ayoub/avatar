"""Session identity — the avatar the agent is talking AS.

Architecture:
  Users own avatars. An avatar is a chat-context entity (name, persona,
  voice, 3D model, tools) with its own memory bag. When the user starts
  a session, they pick which avatar to inhabit; the LiveKit token's
  `participant.identity` is the avatar_id (not the user_id).

  Memory is keyed by avatar_id. So "Sofia remembers your dog" and
  "Marcus doesn't" are emergent from picking different avatars at
  session start.

  The token server validates that the avatar belongs to the calling
  user before issuing the LiveKit token, so the agent can trust
  participant.identity as a verified avatar_id.

This module's job:
  - Look up the Avatar row by avatar_id
  - Apply per-field defaults for fields the user hasn't customized
  - Return a SessionIdentity the rest of the agent consumes

When auth/avatar concepts evolve (avatar marketplace, sharing avatars
across users, etc.), this file is where the resolution logic changes.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from .db import Db

logger = logging.getLogger("identity")


class UnknownAvatarError(RuntimeError):
    """Raised when participant.identity points at an avatar that no
    longer exists. Caller (agent.py:entrypoint) is expected to disconnect
    cleanly rather than synthesize a fallback identity."""


@dataclass(frozen=True)
class SessionIdentity:
    """Everything the agent needs to set up a session.

    `id` is the avatar_id — what Mem0 keys memories by, what audit
    logs would key off, what session analytics aggregate by.

    Other fields come from the Avatar row, with wizard-time fallbacks
    applied when the avatar hasn't customized them yet (e.g. fresh
    avatar with only a name set).
    """

    id: str  # = avatar_id
    user_id: str  # owning user (for ownership checks, audit)
    name: str
    persona: str
    body: str  # "F" or "M"
    voice: str | None
    language: str | None
    requested_tool_ids: list = field(default_factory=list)
    # Per-avatar opt-in: when True, the agent runs ProactiveSpeaker so
    # the avatar will break silence and check in on the user. When False
    # (default), the avatar only speaks in response to user turns.
    proactive: bool = False
    # Per-avatar toggle for the ambient mood watcher. Defaults True to
    # preserve historical behavior. When False, no ambient mood cues
    # are published — chat-time camera image injection is unaffected.
    vision_watcher: bool = True

    @classmethod
    def from_participant(
        cls,
        participant,
        db: Db,
        default_persona: str = "You are a warm, friendly companion. Chat like a close friend.",
    ) -> SessionIdentity:
        """Build a SessionIdentity from a LiveKit RemoteParticipant.

        participant.identity is the avatar_id (the token server set it
        after validating the user owns this avatar). participant.metadata
        carries the wizard cfg for fields the avatar hasn't saved yet
        (mostly `body` for voice-default selection, occasionally a
        wizard override).

        Resolution per field:
          1. Avatar row (DB)
          2. Wizard metadata (current session's wizard choices)
          3. Hardcoded defaults
        """
        cfg = _parse_metadata(participant.metadata)
        avatar_id = participant.identity or ""
        avatar = db.get_avatar(avatar_id) if avatar_id else None
        if avatar is None:
            # Fail closed: an unknown avatar_id means either the row was
            # deleted between token issue and session start, or the token
            # was forged. Either way, falling back to user-supplied
            # wizard metadata would let the session run with a persona
            # the server never validated. Refuse the connect instead and
            # let the agent surface a clean error.
            logger.error(
                "session refused for unknown avatar_id=%s (deleted or forged)",
                avatar_id,
            )
            raise UnknownAvatarError(
                f"avatar_id {avatar_id!r} not found — refusing to start session"
            )

        # Per-field DB → wizard → default fallback. Avatar fields are
        # nullable (fresh avatar may not have them set).
        name = (avatar.name or cfg.get("name") or "Assistant").strip() or "Assistant"
        persona = (
            (avatar.persona or "").strip()
            or (cfg.get("persona") or "").strip()
            or default_persona
        )
        body = cfg.get("body") if cfg.get("body") in {"F", "M"} else "F"
        voice = avatar.voice or cfg.get("voice") or None
        cfg_language = (
            cfg.get("language") if cfg.get("language") in {"en", "ja"} else None
        )
        # Tools: avatar wins if it has any saved, else wizard.
        tool_ids = avatar.tools if avatar.tools else (cfg.get("tools") or [])
        if not isinstance(tool_ids, list):
            tool_ids = []

        return cls(
            id=avatar.id,
            user_id=avatar.user_id,
            name=name,
            persona=persona,
            body=body,
            voice=voice,
            language=cfg_language,
            requested_tool_ids=list(tool_ids),
            proactive=bool(getattr(avatar, "proactive", False)),
            vision_watcher=bool(getattr(avatar, "vision_watcher", True)),
        )


# Backwards-compat alias so external imports keep resolving while we
# migrate. Remove once all references switch to SessionIdentity.
UserIdentity = SessionIdentity


def _parse_metadata(raw: str | None) -> dict:
    """Parse the wizard config from participant.metadata. Tolerates
    missing/bad JSON — returns {} so the defaults can apply."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        logger.warning("Failed to parse participant metadata: %r", raw)
        return {}
