"""User identity — the seam where "who is this user?" enters the system.

Today this is thin: every LiveKit token issued by `ui/server.py` carries
the literal identity `"user"` plus a JSON metadata blob with the wizard's
selections (name, persona, voice, etc.). So `UserIdentity.from_participant`
just splits the metadata into typed fields.

When real auth arrives (sign-in, sessions, multi-user), THIS file is
where the swap happens. The token server starts issuing tokens with:
  - `participant.identity` = stable user_id (from your user store)
  - `participant.attributes` (or metadata) = signed JWT with claims
And `from_participant` becomes:
  - validate the JWT signature
  - look up the user record in the DB
  - build UserIdentity from the verified claims + DB fields

Everything downstream (memory.py, agent.py, system_prompt.py) takes a
UserIdentity object — not a participant, not a metadata dict — so the
auth swap touches only this file.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("identity")


@dataclass(frozen=True)
class UserIdentity:
    """Everything the rest of the system needs to know about the user.

    `id` is the stable per-user key — it's what memory.py uses as
    user_id, what future audit logs would key off, what session
    analytics would aggregate by. Today: `participant.identity`
    (always "user"). Tomorrow: a UUID/email from your user store.

    Other fields are session-time selections from the setup wizard,
    NOT durable user attributes. When auth lands, "name/persona/voice"
    will likely move to a per-user profile saved server-side, and this
    dataclass will read them from the user record instead of the
    LiveKit metadata blob.
    """

    id: str
    name: str
    persona: str
    body: str  # "F" or "M"
    voice: Optional[str]  # explicit voice from wizard, or None for auto-pick
    language: Optional[str]  # explicit lang from wizard, or None
    requested_tool_ids: list = field(default_factory=list)

    @classmethod
    def from_participant(
        cls,
        participant,
        default_name: str = "Assistant",
        default_persona: str = "You are a warm, friendly companion. Chat like a close friend.",
    ) -> "UserIdentity":
        """Build a UserIdentity from a LiveKit RemoteParticipant.

        Today: parses participant.metadata (JSON wizard config) and
        uses participant.identity as the user id.

        When auth lands: validate participant.attributes['auth_token']
        as a signed JWT, look up the user, and populate accordingly.
        Callers don't change.
        """
        cfg = _parse_metadata(participant.metadata)

        name = (cfg.get("name") or default_name).strip() or default_name
        persona = (cfg.get("persona") or default_persona).strip() or default_persona
        body = cfg.get("body") if cfg.get("body") in {"F", "M"} else "F"
        voice = cfg.get("voice") or None
        language = cfg.get("language") if cfg.get("language") in {"en", "ja"} else None
        tool_ids = cfg.get("tools") or []
        if not isinstance(tool_ids, list):
            tool_ids = []

        return cls(
            id=participant.identity or "anonymous",
            name=name,
            persona=persona,
            body=body,
            voice=voice,
            language=language,
            requested_tool_ids=list(tool_ids),
        )


def _parse_metadata(raw: Optional[str]) -> dict:
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
