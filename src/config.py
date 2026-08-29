"""Centralized typed configuration.

Single source of truth for every environment variable. ALL other modules
import `Config` from here and pass it down — they never call `os.getenv`
directly. Two reasons:

  1. Findability. "Where does this setting come from?" has one answer.
  2. Auth/login is coming. New env vars (JWT_SECRET, OAUTH_*, DB_URL)
     drop into one obvious place instead of being sprinkled across files.

The factory `Config.from_env()` is called once at agent startup and
threaded through the rest of the system. Resolves Mem0's fallback
chains (e.g. mem0_llm_base_url defaults to llm_base_url) at config
time so consumers don't replicate the fallback logic.

Required vars raise loudly at startup (KeyError); optional vars use
typed defaults. This trades "fail at startup with clear error" for
"silently misbehave at request time" — always the right tradeoff.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# Voice defaults per (language, body) pair. Kept as a top-level constant
# rather than a Config field so the dict shape (tuple keys) stays
# straightforward — Config.pick_voice() reads this.
_VOICE_DEFAULT_KEYS: tuple[tuple[str, str, str, str], ...] = (
    # (language, body, env_var, fallback)
    ("en", "F", "TTS_VOICE_FEMALE_EN", "af_heart"),
    ("en", "M", "TTS_VOICE_MALE_EN", "am_michael"),
    ("ja", "F", "TTS_VOICE_FEMALE_JA", "jf_alpha"),
    ("ja", "M", "TTS_VOICE_MALE_JA", "jm_kumo"),
)


@dataclass(frozen=True)
class Config:
    """Frozen — config is immutable after startup. Pass it everywhere
    instead of reaching for env vars."""

    # ── LiveKit ─────────────────────────────────────────────────────────
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    # External URL is what the BROWSER uses (host-reachable); the agent
    # uses livekit_url internally (Docker network name).
    livekit_external_url: str

    # ── Chat LLM (mlx_vlm.server, OpenAI-compatible) ────────────────────
    llm_base_url: str
    llm_api_key: str
    llm_model: str

    # ── STT (Speaches / faster-whisper) ─────────────────────────────────
    stt_base_url: str
    stt_model: str

    # ── TTS (Kokoro — always on) ────────────────────────────────────────
    tts_base_url: str
    tts_model: str
    voice_defaults: dict = field(default_factory=dict)

    # ── Orpheus TTS (optional second backend) ───────────────────────────
    # When unset, Orpheus voices selected in the wizard will fail loudly
    # at session start — Kokoro voices are unaffected.
    orpheus_base_url: str | None = None
    orpheus_model: str = "orpheus"

    # ── Supertonic TTS (optional third backend) ─────────────────────────
    # When unset, Supertonic voices selected in the wizard fail loudly at
    # session start — Kokoro/Orpheus voices are unaffected. 44.1kHz WAV,
    # no word timestamps (jaw-only lipsync). Voice = style (F1-F5/M1-M5).
    supertonic_base_url: str | None = None
    supertonic_model: str = "supertonic-3"
    supertonic_speed: float = 1.0

    # ── Ambient affect VLM (optional) ───────────────────────────────────
    # When unset, VisionWatcher uses NullProvider equivalent — no ambient
    # mood detection, the LLM's speech-time cues remain the only source.
    vlm_base_url: str | None = None
    vlm_model: str = "mlx-community/Qwen3-VL-2B-Instruct-4bit"

    # ── Persistent memory (Mem0 + Postgres + Ollama embedder) ───────────
    # When mem0_pg_host is unset, NullProvider is used (no per-user
    # memory). All other mem0_* fields are still populated with sensible
    # defaults so partial config doesn't crash.
    mem0_pg_host: str | None = None
    mem0_pg_port: int = 5432
    mem0_pg_user: str = "mem0"
    mem0_pg_password: str = "mem0"
    mem0_pg_dbname: str = "mem0"

    # Mem0's fact-extraction LLM. Defaults to the chat LLM if not set
    # explicitly — fallbacks resolved at config time so memory.py never
    # has to ask "is this set, otherwise the chat one".
    mem0_llm_base_url: str = ""
    mem0_llm_api_key: str = ""
    mem0_llm_model: str = ""

    # Mem0's embedding model. Default = Ollama on the host.
    mem0_embedder_provider: str = "openai"
    mem0_embedder: str = "all-minilm"
    mem0_embedder_base_url: str | None = None
    mem0_embedder_api_key: str | None = None
    mem0_embedder_dims: int | None = None

    # ── Auth / sessions ─────────────────────────────────────────────────
    # JWT_SECRET signs the session token issued at /api/login. Must be set
    # in production — generate with `python -c "import secrets; print(secrets.token_urlsafe(64))"`.
    # Don't commit to .env.example with a real value; commit only the
    # placeholder. Same secret must be available to BOTH the token server
    # (issues tokens) and the agent (verifies tokens) — both run in the
    # same container so .env covers both.
    jwt_secret: str = ""
    # Session JWT lifetime. Seven days is a sensible default for a
    # voice-friend app — short enough to limit blast radius, long enough
    # that returning users don't re-auth on every visit.
    session_token_ttl_days: int = 7

    # ── App database (users + future profile / settings tables) ─────────
    # Reuses the postgres-memory container by default — same host/creds,
    # different (or same) database. We keep the users table in the same
    # `mem0` DB alongside `memories` to avoid spinning up a second
    # postgres just for auth. If you ever split, point app_pg_* at a
    # different host.
    app_pg_host: str = "postgres-memory"
    app_pg_port: int = 5432
    app_pg_user: str = "mem0"
    app_pg_password: str = "mem0"
    app_pg_dbname: str = "mem0"

    # ────────────────────────────────────────────────────────────────────
    @classmethod
    def from_env(cls) -> Config:
        """Read env vars once at startup. Required vars raise KeyError
        with a clear message; optional vars use typed defaults."""

        voice_defaults = {
            (lang, body): os.getenv(env_var, fallback)
            for lang, body, env_var, fallback in _VOICE_DEFAULT_KEYS
        }

        # Refuse to boot with LiveKit's well-known dev defaults (`devkey`
        # / `secret`) unless DEV=1 is set. These ship in .env.example for
        # localhost convenience; on a non-localhost deployment they let
        # anyone on the network mint identity tokens. Loud failure is the
        # right tradeoff — silent acceptance is how this leaks to prod.
        livekit_key = os.environ["LIVEKIT_API_KEY"]
        livekit_secret = os.environ["LIVEKIT_API_SECRET"]
        if os.getenv("DEV") != "1" and (
            livekit_key == "devkey" or livekit_secret == "secret"
        ):
            raise RuntimeError(
                "LIVEKIT_API_KEY/SECRET are set to LiveKit's public dev defaults "
                "('devkey'/'secret'). These are documented and globally known — "
                "any reachable network peer can mint tokens. Generate fresh "
                "credentials and set them in .env, or pass DEV=1 to acknowledge "
                "you are running on localhost only."
            )

        # Resolve Mem0's fallback chain at config time — if MEM0_LLM_*
        # vars aren't set, fall back to the chat LLM config. This keeps
        # memory.py free of os.getenv calls.
        llm_base_url = os.environ["LLM_BASE_URL"]
        llm_api_key = os.environ["LLM_API_KEY"]
        llm_model = os.environ["LLM_MODEL"]

        embedder_dims_env = os.getenv("MEM0_EMBEDDER_DIMS")

        return cls(
            # LiveKit
            livekit_url=os.environ["LIVEKIT_URL"],
            livekit_api_key=livekit_key,
            livekit_api_secret=livekit_secret,
            livekit_external_url=os.getenv(
                "LIVEKIT_EXTERNAL_URL", os.environ["LIVEKIT_URL"]
            ),
            # Chat LLM
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            llm_model=llm_model,
            # STT
            stt_base_url=os.environ["STT_BASE_URL"],
            stt_model=os.getenv("STT_MODEL", "Systran/faster-whisper-base"),
            # TTS
            tts_base_url=os.environ["TTS_BASE_URL"],
            tts_model=os.getenv("TTS_MODEL", "kokoro"),
            voice_defaults=voice_defaults,
            # Orpheus
            orpheus_base_url=os.getenv("ORPHEUS_BASE_URL"),
            orpheus_model=os.getenv("ORPHEUS_MODEL", "orpheus"),
            # Supertonic
            supertonic_base_url=os.getenv("SUPERTONIC_BASE_URL"),
            supertonic_model=os.getenv("SUPERTONIC_MODEL", "supertonic-3"),
            supertonic_speed=float(os.getenv("SUPERTONIC_SPEED", "1.0")),
            # VLM watcher
            vlm_base_url=os.getenv("VLM_BASE_URL"),
            vlm_model=os.getenv("VLM_MODEL", "mlx-community/Qwen3-VL-2B-Instruct-4bit"),
            # Memory: Postgres
            mem0_pg_host=os.getenv("MEM0_PG_HOST"),
            mem0_pg_port=int(os.getenv("MEM0_PG_PORT", "5432")),
            mem0_pg_user=os.getenv("MEM0_PG_USER", "mem0"),
            mem0_pg_password=os.getenv("MEM0_PG_PASSWORD", "mem0"),
            mem0_pg_dbname=os.getenv("MEM0_PG_DBNAME", "mem0"),
            # Memory: extraction LLM (with fallback to chat LLM)
            mem0_llm_base_url=os.getenv("MEM0_LLM_BASE_URL") or llm_base_url,
            mem0_llm_api_key=os.getenv("MEM0_LLM_API_KEY") or llm_api_key,
            mem0_llm_model=os.getenv("MEM0_LLM_MODEL") or llm_model,
            # Memory: embedder
            mem0_embedder_provider=os.getenv("MEM0_EMBEDDER_PROVIDER", "openai"),
            mem0_embedder=os.getenv("MEM0_EMBEDDER", "all-minilm"),
            mem0_embedder_base_url=os.getenv("MEM0_EMBEDDER_BASE_URL"),
            mem0_embedder_api_key=os.getenv("MEM0_EMBEDDER_API_KEY"),
            mem0_embedder_dims=(int(embedder_dims_env) if embedder_dims_env else None),
            # Auth
            jwt_secret=os.environ["JWT_SECRET"],
            session_token_ttl_days=int(os.getenv("SESSION_TOKEN_TTL_DAYS", "7")),
            # App DB (default: reuse postgres-memory)
            app_pg_host=os.getenv("APP_PG_HOST", "postgres-memory"),
            app_pg_port=int(os.getenv("APP_PG_PORT", "5432")),
            app_pg_user=os.getenv("APP_PG_USER", "mem0"),
            app_pg_password=os.getenv("APP_PG_PASSWORD", "mem0"),
            app_pg_dbname=os.getenv("APP_PG_DBNAME", "mem0"),
        )

    # Convenience helpers ────────────────────────────────────────────────
    def pick_voice(self, language: str, body: str) -> str:
        """Default voice for a (language, body) pair. Falls back to the
        English-female default if the pair has no entry."""
        return self.voice_defaults.get(
            (language, body), self.voice_defaults[("en", "F")]
        )

    @property
    def memory_enabled(self) -> bool:
        """True when memory should be wired in. Single check site for the
        agent — keeps the if-condition out of the entrypoint."""
        return bool(self.mem0_pg_host)
