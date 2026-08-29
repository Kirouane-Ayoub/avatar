import http.client
import json
import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from livekit.api import AccessToken, VideoGrants

# Import shared modules from src/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from cues import MOODS
from tts import (
    KOKORO_VOICES,
    ORPHEUS_VOICES,
    SUPERTONIC_VOICES,
    backend_for,
    supertonic_style_for,
)

load_dotenv()

# Auth + DB. Imported AFTER load_dotenv so config.py sees the env vars.
import auth as auth_lib  # noqa: E402
from auth import init_db  # noqa: E402
from config import Config as _Config  # noqa: E402

logger = logging.getLogger("token-server")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

# Module-level singletons shared by every request handler thread. The DB
# pool is thread-safe (psycopg_pool.ConnectionPool); Config is frozen.
_CONFIG = _Config.from_env()
_DB = init_db(_CONFIG)

LIVEKIT_URL = os.environ["LIVEKIT_URL"]
LIVEKIT_EXTERNAL_URL = os.getenv("LIVEKIT_EXTERNAL_URL", LIVEKIT_URL)
LIVEKIT_API_KEY = os.environ["LIVEKIT_API_KEY"]
LIVEKIT_API_SECRET = os.environ["LIVEKIT_API_SECRET"]
PORT = int(os.getenv("UI_PORT", "3000"))
UI_DIR = Path(__file__).parent
DIST_DIR = UI_DIR / "dist"

# Paths that must be served from the source tree (ui/) rather than the built
# React bundle (ui/dist/). Avatar GLBs live in ui/avatar-zoo/.
_SOURCE_ROUTES = ("/avatar-zoo/",)

ALLOWED_TOOLS = {"set_reminder", "online_search", "internal_search"}
ALLOWED_MOODS = frozenset(MOODS)
ALLOWED_LANGUAGES = {"en", "ja"}
ALLOWED_BODIES = {"F", "M"}

MAX_NAME_LEN = 60
MAX_PERSONA_LEN = 2000
MAX_SAMPLE_TEXT = 200
# Bound user-supplied display_name so the DB column doesn't grow without
# limit and so the UI doesn't try to render a 1 MB monogram label.
MAX_DISPLAY_NAME_LEN = 100

TTS_BASE_URL = os.getenv("TTS_BASE_URL", "http://kokoro-tts:8880").rstrip("/")
TTS_MODEL = os.getenv("TTS_MODEL", "kokoro")
ORPHEUS_BASE_URL = (os.getenv("ORPHEUS_BASE_URL") or "").rstrip("/")
ORPHEUS_MODEL = os.getenv("ORPHEUS_MODEL", "orpheus")
# Supertonic root (strip a trailing /v1 if the env var was pasted with it —
# the OpenAI path /v1/audio/speech is appended below).
SUPERTONIC_BASE_URL = (os.getenv("SUPERTONIC_BASE_URL") or "").rstrip("/")
if SUPERTONIC_BASE_URL.endswith("/v1"):
    SUPERTONIC_BASE_URL = SUPERTONIC_BASE_URL[: -len("/v1")]
SUPERTONIC_MODEL = os.getenv("SUPERTONIC_MODEL", "supertonic-3")
SUPERTONIC_SPEED = float(os.getenv("SUPERTONIC_SPEED", "1.0"))

# Serialize voice-sample proxy calls so a fast-clicking user can't pile up
# concurrent Kokoro generations and OOM-kill the container. One concurrent
# request is plenty for interactive preview; bump via env if you want more.
_TTS_CONCURRENCY = int(os.getenv("TTS_SAMPLE_CONCURRENCY", "1"))
_TTS_SEMAPHORE = threading.BoundedSemaphore(max(1, _TTS_CONCURRENCY))


# ── Rate limiting (in-memory, per-IP) ───────────────────────────────────
# Token-bucket per (endpoint, IP). Tuned to slow brute-force without
# punishing legitimate retry-after-typo. Reset state lives in process
# memory — a multi-process deployment would need Redis or a shared store,
# but the app currently runs as a single Python process so this is fine.
#
# Login: 8 attempts per 5 min lets a fat-fingered user retry without
# friction; an attacker-paced 1000-tries/hour attempt gets 96 attempts
# instead. bcrypt cost-12 (~250ms) further throttles each one.
# Signup: 5 per hour per IP — high enough for a household NAT, low
# enough that spam-signup farms hit the wall fast.
_RATE_LIMIT_WINDOWS = {
    "login": (8, 300.0),  # 8 attempts / 5 min
    "signup": (5, 3600.0),  # 5 attempts / hour
}
_rate_state: dict[tuple[str, str], list[float]] = {}
_rate_lock = threading.Lock()


def _rate_limit_check(endpoint: str, ip: str) -> bool:
    """True when the request is allowed; False after sending a 429.
    Sliding-window counter — drops timestamps older than the window each
    call so memory stays bounded as IPs come and go."""
    cap, window = _RATE_LIMIT_WINDOWS[endpoint]
    now = time.monotonic()
    cutoff = now - window
    key = (endpoint, ip)
    with _rate_lock:
        bucket = _rate_state.setdefault(key, [])
        # Drop expired timestamps in place — cheap because the list stays
        # short relative to the window/cap pair.
        i = 0
        while i < len(bucket) and bucket[i] < cutoff:
            i += 1
        if i:
            del bucket[:i]
        if len(bucket) >= cap:
            return False
        bucket.append(now)
        return True


# The upstream Kokoro image ships different voice sets depending on version
# (e.g. v1.0 vs v0 carry-overs). We query the running server for its actual
# voice list and intersect with our metadata catalog — that way
# bf_isabella-style mismatches never reach the UI and fail at play time.
_VOICE_CACHE: dict[str, object] = {"ids": None, "expires": 0.0}
_VOICE_CACHE_LOCK = threading.Lock()
_VOICE_CACHE_TTL = 60.0


def _fetch_kokoro_voice_ids() -> list[str]:
    try:
        with urllib.request.urlopen(f"{TTS_BASE_URL}/v1/audio/voices", timeout=5) as up:
            data = json.load(up)
    except (
        urllib.error.URLError,
        http.client.HTTPException,
        OSError,
        json.JSONDecodeError,
    ):
        return []
    if isinstance(data, dict):
        if isinstance(data.get("voices"), list):
            return [v for v in data["voices"] if isinstance(v, str)]
        if isinstance(data.get("data"), list):
            return [
                d.get("id")
                for d in data["data"]
                if isinstance(d, dict) and isinstance(d.get("id"), str)
            ]
    return []


def _available_voice_ids() -> set[str]:
    """Voices Kokoro actually has intersected with our metadata catalog.
    Falls back to the full catalog if Kokoro is unreachable."""
    with _VOICE_CACHE_LOCK:
        now = time.monotonic()
        if _VOICE_CACHE["ids"] is None or now >= _VOICE_CACHE["expires"]:
            fetched = _fetch_kokoro_voice_ids()
            if fetched:
                _VOICE_CACHE["ids"] = {v for v in fetched if v in KOKORO_VOICES}
            else:
                _VOICE_CACHE["ids"] = set(KOKORO_VOICES)
            _VOICE_CACHE["expires"] = now + _VOICE_CACHE_TTL
        return _VOICE_CACHE["ids"]  # type: ignore[return-value]


def sanitize(body: dict) -> dict:
    name = (body.get("name") or "").strip()[:MAX_NAME_LEN] or "Assistant"
    persona = (body.get("persona") or "").strip()[:MAX_PERSONA_LEN]
    mood = body.get("mood") if body.get("mood") in ALLOWED_MOODS else "neutral"
    language = (
        body.get("language") if body.get("language") in ALLOWED_LANGUAGES else "en"
    )
    body_type = body.get("body") if body.get("body") in ALLOWED_BODIES else "F"
    raw_tools = body.get("tools") or []
    tools = [t for t in raw_tools if t in ALLOWED_TOOLS]
    # Per-avatar opt-in: when True the agent runs ProactiveSpeaker so the
    # avatar will break silence and check in on the user. Default False
    # (quiet companion). bool() handles both literal `true`/`false` JSON
    # and Python truthy values defensively.
    proactive = bool(body.get("proactive", False))
    # Per-avatar opt-out for the ambient mood watcher. Default True
    # mirrors the historical "always on when VLM available" behavior.
    # Explicit-default approach: missing key → True (don't silently
    # disable for clients that haven't been updated).
    vision_watcher = bool(body.get("vision_watcher", True))
    camera = bool(body.get("camera", False))
    avatar = str(body.get("avatar") or "")[:80]
    requested_voice = body.get("voice")
    if requested_voice in _available_voice_ids() or requested_voice in ORPHEUS_VOICES:
        voice = requested_voice
    else:
        voice = None
    return {
        "avatar": avatar,
        "name": name,
        "persona": persona,
        "mood": mood,
        "tools": tools,
        "proactive": proactive,
        "vision_watcher": vision_watcher,
        "camera": camera,
        "language": language,
        "body": body_type,
        "voice": voice,
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # Prefer the built React bundle when present, otherwise fall back to
        # the source tree (useful before the first `npm run build`).
        default_root = DIST_DIR if DIST_DIR.is_dir() else UI_DIR
        super().__init__(*args, directory=str(default_root), **kwargs)

    def end_headers(self):
        # Apply the same baseline security headers to every response (API
        # JSON, static assets, voice-sample stream). Cheap, cross-cutting,
        # and ineffective if applied selectively.
        self._send_security_headers()
        self._send_cache_headers()
        super().end_headers()

    def _send_cache_headers(self):
        """Cache policy for static GETs. Vite content-hashes asset
        filenames (index-<hash>.js/.css), so those are safe to cache
        forever — but index.html references the *current* hashes and MUST
        be revalidated every load, otherwise a stale cached index keeps
        loading old JS/CSS after a redeploy (this is exactly the "icons
        still black after the fix shipped" symptom). API responses set
        their own policy (or none), so skip them to avoid duplicate
        Cache-Control headers."""
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/"):
            return
        if path.startswith("/assets/"):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        elif path == "/" or path.endswith(".html"):
            self.send_header("Cache-Control", "no-cache")

    def _send_security_headers(self):
        """Defense-in-depth headers for browser-loaded responses.
        - nosniff: stop browsers from MIME-sniffing JSON as JS.
        - referrer: don't leak the (potentially session-id-bearing) URL
          to third parties when a user clicks a link out.
        - frame-ancestors: same-origin only — blocks clickjacking even
          if a future overlay route lacks framebusting.
        - X-Frame-Options DENY: legacy fallback for older browsers.
        - permissions: deny the most invasive APIs we don't use, leave
          camera+mic open since LiveKit needs them.
        Deliberately NOT setting Content-Security-Policy: the index page
        loads TalkingHead from a CDN via importmap (see H4 follow-up);
        adding a CSP without vendoring those modules first would break
        the avatar."""
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Permissions-Policy",
            "geolocation=(), payment=(), usb=(), magnetometer=(), accelerometer=()",
        )

    def _send_json(self, status: int, payload: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    # No request body the server actually consumes is over a few KB. Cap
    # at 64 KB so a malicious client can't make us allocate 1 GB on a
    # forged Content-Length. 413 (Payload Too Large) for anything above.
    _MAX_BODY_BYTES = 64 * 1024

    # ── Auth helpers ─────────────────────────────────────────────────────
    def _read_json_body(self) -> dict:
        """Read+parse a JSON body, returning {} on missing/invalid.
        Sends a 400 + raises ValueError if the body was malformed JSON
        (caller should `return` after catching). Sends 413 + raises
        ValueError if Content-Length exceeds the cap."""
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            self._send_json(400, {"error": "invalid Content-Length"})
            raise ValueError("bad content-length") from None
        if length < 0:
            self._send_json(400, {"error": "invalid Content-Length"})
            raise ValueError("negative content-length")
        if length > self._MAX_BODY_BYTES:
            self._send_json(413, {"error": "request body too large"})
            raise ValueError("body too large")
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON"})
            raise ValueError("bad json") from None

    def _bearer_user_id(self) -> str | None:
        """Extract user_id from Authorization: Bearer <session_jwt>.
        Returns None and sends 401 on missing / invalid / expired token."""
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self._send_json(401, {"error": "missing bearer token"})
            return None
        token = auth_header[len("Bearer ") :].strip()
        try:
            return auth_lib.user_id_from_token(token, _CONFIG)
        except auth_lib.InvalidToken as e:
            self._send_json(401, {"error": str(e)})
            return None

    def _user_to_json(self, user) -> dict:
        """Serialize a User dataclass for the wire. Excludes any
        sensitive fields (password_hash never makes it past auth.py).
        Persona/voice/avatar/mood/tools moved to the avatars table —
        the user record is auth-only now."""
        return {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
        }

    def _avatar_to_json(self, avatar) -> dict:
        """Serialize an Avatar dataclass for the wire."""
        return {
            "id": avatar.id,
            "user_id": avatar.user_id,
            "name": avatar.name,
            "persona": avatar.persona,
            "voice": avatar.voice,
            "avatar_key": avatar.avatar_key,
            "tools": avatar.tools,
            "proactive": avatar.proactive,
            "vision_watcher": avatar.vision_watcher,
            "last_used_at": avatar.last_used_at.isoformat()
            if avatar.last_used_at
            else None,
        }

    def _own_avatar_or_404(self, user_id: str, avatar_id: str):
        """Fetch the avatar AND verify the calling user owns it.
        Returns the Avatar on success, None after sending 404 / 403.
        Folds two checks into one to keep callers tidy."""
        avatar = _DB.get_avatar(avatar_id)
        if avatar is None:
            self._send_json(404, {"error": "avatar not found"})
            return None
        if avatar.user_id != user_id:
            # 404 not 403 — don't leak that the avatar exists under
            # someone else.
            self._send_json(404, {"error": "avatar not found"})
            return None
        return avatar

    def _handle_voice_sample(self, qs: dict):
        # Authenticated only — synthesizing a voice sample takes 2-15 s of
        # Metal/CPU on the upstream TTS server, and the global semaphore
        # caps concurrency to 1, so leaving this open lets any anonymous
        # caller wedge the endpoint and burn compute.
        if self._bearer_user_id() is None:
            return  # 401 already sent
        voice = (qs.get("voice", [""])[0] or "").strip()
        text = (qs.get("text", [""])[0] or "").strip()[:MAX_SAMPLE_TEXT]
        backend = backend_for(voice)
        if backend == "orpheus":
            if voice not in ORPHEUS_VOICES:
                self._send_json(400, {"error": "unknown voice"})
                return
            if not ORPHEUS_BASE_URL:
                self._send_json(
                    501,
                    {"error": "orpheus preview unavailable (ORPHEUS_BASE_URL unset)"},
                )
                return
        elif backend == "supertonic":
            if voice not in SUPERTONIC_VOICES:
                self._send_json(400, {"error": "unknown voice"})
                return
            if not SUPERTONIC_BASE_URL:
                self._send_json(
                    501,
                    {
                        "error": "supertonic preview unavailable (SUPERTONIC_BASE_URL unset)"
                    },
                )
                return
        else:
            if voice not in _available_voice_ids():
                self._send_json(400, {"error": "unknown voice"})
                return
        if not text:
            text = "Hey there — this is how I sound."

        # Back off if too many concurrent samples are already running. The
        # browser cancels stale requests, but a slow TTS can still pile up.
        if not _TTS_SEMAPHORE.acquire(timeout=5):
            self._send_json(503, {"error": "tts busy, try again"})
            return
        try:
            self._stream_voice_sample(voice, text, backend)
        finally:
            _TTS_SEMAPHORE.release()

    def _stream_voice_sample(self, voice: str, text: str, backend: str):
        if backend == "orpheus":
            base_url = ORPHEUS_BASE_URL
            model = ORPHEUS_MODEL  # full HF id, e.g. mlx-community/orpheus-...
            response_format = (
                "wav"  # mlx-audio returns a buffered WAV when stream is unset
            )
        elif backend == "supertonic":
            base_url = SUPERTONIC_BASE_URL
            model = SUPERTONIC_MODEL
            response_format = "wav"  # Supertonic serves a buffered 44.1kHz WAV
        else:
            base_url = TTS_BASE_URL
            model = TTS_MODEL
            response_format = "mp3"
        payload_obj = {
            "model": model,
            "voice": voice,
            "input": text,
            "response_format": response_format,
        }
        if backend == "orpheus":
            # Match the Orpheus model card's recommended sampling params; the
            # mlx-audio server's defaults (temperature=0.7, top_p=0.95,
            # repetition_penalty=1.0) produce noticeably worse audio.
            payload_obj.update(
                {"temperature": 0.6, "top_p": 0.8, "repetition_penalty": 1.3}
            )
        elif backend == "supertonic":
            # `voice` is the bare style (F1..M5); spoken language is a
            # separate field so Greek samples (el_F2) preview in Greek.
            payload_obj["voice"] = supertonic_style_for(voice)
            payload_obj["speed"] = SUPERTONIC_SPEED
            payload_obj["lang"] = SUPERTONIC_VOICES[voice].get("stt", "en")
        payload = json.dumps(payload_obj).encode()
        req = urllib.request.Request(
            f"{base_url}/v1/audio/speech",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            up = urllib.request.urlopen(req, timeout=30)
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            self.log_error("tts upstream: %s", e)
            self._send_json(502, {"error": "tts upstream unavailable"})
            return

        with up:
            content_type = up.headers.get("Content-Type", "audio/mpeg")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            try:
                while True:
                    chunk = up.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                # Client (browser) cancelled the download — common when the
                # user clicks a different voice before the first finishes.
                self.log_message("voice-sample: client disconnected")
            except (http.client.IncompleteRead, http.client.HTTPException) as e:
                # Kokoro closed the socket mid-stream (usually OOM-kill).
                # Headers are already sent, so we just stop writing. Log a
                # single line instead of a 30-line traceback.
                self.log_error("tts mid-stream failure (likely Kokoro OOM): %s", e)
            except OSError as e:
                self.log_error("tts mid-stream socket error: %s", e)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/signup":
            return self._handle_signup()
        if parsed.path == "/api/login":
            return self._handle_login()
        if parsed.path == "/api/logout":
            # Stateless JWT — nothing to invalidate server-side. The
            # client clears localStorage. Returning 200 keeps the API
            # symmetric and lets us add a server-side blocklist later
            # without changing clients.
            return self._send_json(200, {"ok": True})
        if parsed.path == "/api/token":
            return self._handle_token()
        if parsed.path == "/api/avatars":
            return self._handle_create_avatar()
        # POST /api/avatars/<id>/forget — wipe this avatar's memory
        # (transcripts + Mem0 facts) without deleting the avatar itself.
        # Lets the user "start fresh" with the same companion.
        if parsed.path.startswith("/api/avatars/") and parsed.path.endswith("/forget"):
            avatar_id = parsed.path[len("/api/avatars/") : -len("/forget")].strip("/")
            if avatar_id:
                return self._handle_forget_avatar(avatar_id)
        self.send_error(404)

    def do_PATCH(self):
        parsed = urlparse(self.path)
        avatar_id = self._extract_avatar_id(parsed.path)
        if avatar_id is not None:
            return self._handle_update_avatar(avatar_id)
        self.send_error(404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/me":
            return self._handle_delete_me()
        avatar_id = self._extract_avatar_id(parsed.path)
        if avatar_id is not None:
            return self._handle_delete_avatar(avatar_id)
        self.send_error(404)

    @staticmethod
    def _extract_avatar_id(path: str) -> str | None:
        """`/api/avatars/<id>` → <id>; otherwise None. Used by GET /
        PATCH / DELETE on a single avatar."""
        prefix = "/api/avatars/"
        if not path.startswith(prefix):
            return None
        avatar_id = path[len(prefix) :].strip("/")
        return avatar_id or None

    # ── DELETE /api/me — wipe account + every avatar + their memories ──
    def _handle_delete_me(self):
        user_id = self._bearer_user_id()
        if user_id is None:
            return  # 401 already sent

        # Reconfirm the password before doing anything irreversible. A
        # session JWT alone is enough to read the account but NOT enough
        # to nuke it — this stops a stolen-token (XSS / shoulder-surf)
        # from also wiping every avatar + memory bag the user has built.
        try:
            body = self._read_json_body()
        except ValueError:
            return
        password = body.get("password") if isinstance(body, dict) else None
        if not password:
            return self._send_json(400, {"error": "password required"})
        try:
            user_check = _DB.get_user_by_id(user_id)
            if user_check is None:
                return self._send_json(401, {"error": "user no longer exists"})
            # Re-verify against the current credentials. We deliberately
            # don't expose `verify_user_password` on auth_lib — the call
            # below mirrors the login path: lookup by username + verify.
            try:
                auth_lib.login(
                    _DB,
                    _CONFIG,
                    username=user_check.username,
                    password=password,
                )
            except auth_lib.InvalidCredentials:
                return self._send_json(401, {"error": "invalid password"})
        except Exception:
            logger.exception("delete-me reconfirm failed for user_id=%s", user_id)
            return self._send_json(500, {"error": "reconfirm failed"})

        # Memory is keyed by avatar_id (not user_id), so we have to
        # enumerate this user's avatars and forget each one's memories
        # BEFORE deleting the user. The user delete CASCADEs to the
        # avatar rows via the FK; the memory rows are owned by Mem0 in
        # its own table and need explicit cleanup or they're orphaned.
        import asyncio

        from memory import build_provider

        try:
            avatars = _DB.list_avatars(user_id)
            if avatars:
                provider = build_provider(_CONFIG)

                async def _wipe_all():
                    for av in avatars:
                        await provider.forget(av.id)

                asyncio.run(_wipe_all())
        except Exception:
            logger.exception(
                "memory wipe failed for user_id=%s — proceeding with user delete",
                user_id,
            )
        deleted = _DB.delete_user(user_id)
        logger.info(
            "delete account: user_id=%s avatars_wiped=%d row_deleted=%s",
            user_id,
            len(avatars) if "avatars" in locals() else 0,
            deleted,
        )
        self._send_json(200, {"ok": True, "deleted": deleted})

    def _client_ip(self) -> str:
        """Best-effort client IP for rate limiting. Behind a reverse proxy
        the X-Forwarded-For header takes precedence; we trust the first
        entry only when it's set, otherwise fall back to the socket peer.
        Trust model: deploy behind a proxy you control, or accept that
        clients on the public internet can spoof XFF and dilute their own
        rate limit (their problem, not ours)."""
        xff = self.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip()
        return self.client_address[0] if self.client_address else "unknown"

    # ── /api/signup ─────────────────────────────────────────────────────
    def _handle_signup(self):
        if not _rate_limit_check("signup", self._client_ip()):
            return self._send_json(429, {"error": "too many signups, slow down"})
        try:
            body = self._read_json_body()
        except ValueError:
            return
        username = body.get("username", "")
        password = body.get("password", "")
        display_name = body.get("display_name") or body.get("displayName")
        if isinstance(display_name, str):
            display_name = display_name.strip()[:MAX_DISPLAY_NAME_LEN]
        try:
            user, token = auth_lib.signup(
                _DB,
                _CONFIG,
                username=username,
                password=password,
                display_name=display_name,
            )
        except auth_lib.UsernameTaken:
            return self._send_json(409, {"error": "username already taken"})
        except (auth_lib.WeakPassword, auth_lib.AuthError) as e:
            return self._send_json(400, {"error": str(e)})
        except Exception as e:
            logger.exception("signup failed")
            return self._send_json(500, {"error": f"signup failed: {e}"})
        self._send_json(201, {"user": self._user_to_json(user), "session_token": token})

    # ── /api/login ──────────────────────────────────────────────────────
    def _handle_login(self):
        if not _rate_limit_check("login", self._client_ip()):
            return self._send_json(
                429, {"error": "too many login attempts, try again later"}
            )
        try:
            body = self._read_json_body()
        except ValueError:
            return
        try:
            user, token = auth_lib.login(
                _DB,
                _CONFIG,
                username=body.get("username", ""),
                password=body.get("password", ""),
            )
        except auth_lib.InvalidCredentials:
            return self._send_json(401, {"error": "invalid username or password"})
        except Exception as e:
            logger.exception("login failed")
            return self._send_json(500, {"error": f"login failed: {e}"})
        self._send_json(200, {"user": self._user_to_json(user), "session_token": token})

    # ── /api/token (LiveKit room access — requires session JWT + avatar_id) ─
    def _handle_token(self):
        # Verify the session JWT first; reject unauthorized requests
        # before doing any other work (and before consuming the body).
        user_id = self._bearer_user_id()
        if user_id is None:
            return  # 401 already sent
        user = _DB.get_user_by_id(user_id)
        if user is None:
            return self._send_json(401, {"error": "user no longer exists"})

        try:
            body = self._read_json_body()
        except ValueError:
            return
        avatar_id = (body.get("avatar_id") or "").strip()
        if not avatar_id:
            return self._send_json(400, {"error": "avatar_id required"})

        avatar = self._own_avatar_or_404(user_id, avatar_id)
        if avatar is None:
            return  # 404 already sent

        # Persist wizard choices that came along (the user may have
        # tweaked persona/voice/avatar_key/tools right before starting).
        # Mood is intentionally NOT saved — it's a transient preview.
        cfg = sanitize(body)
        try:
            _DB.update_avatar(
                avatar.id,
                name=cfg.get("name") or None,
                persona=cfg.get("persona") or None,
                voice=cfg.get("voice"),
                avatar_key=cfg.get("avatar") or None,
                tools=cfg.get("tools"),
                proactive=cfg.get("proactive"),
                vision_watcher=cfg.get("vision_watcher"),
                touch_last_used=True,  # bumps last_used_at for "recently chatted" sort
            )
        except Exception:
            logger.exception("avatar profile save failed for avatar_id=%s", avatar.id)

        room_name = f"session-{uuid.uuid4().hex[:8]}"
        # Identity = avatar_id. Memory keys by this; agent's identity
        # layer looks up the Avatar row by it. Wizard cfg in metadata
        # for body / mood / language hints the agent uses for voice
        # defaults and initial preview state.
        #
        # Token is short-lived (handshake only — LiveKit's WS connection
        # outlives the token's TTL), and source-restricted to mic+camera so
        # a compromised browser can't publish unexpected media. A leaked
        # token expires before it's useful for offline replay.
        token = (
            AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
            .with_identity(avatar.id)
            .with_metadata(json.dumps(cfg))
            .with_ttl(timedelta(minutes=10))
            .with_grants(
                VideoGrants(
                    room_join=True,
                    room=room_name,
                    can_publish_sources=["camera", "microphone"],
                )
            )
            .to_jwt()
        )
        self._send_json(
            200,
            {
                "token": token,
                "url": LIVEKIT_EXTERNAL_URL,
                "config": cfg,
                "user": self._user_to_json(user),
                "avatar": self._avatar_to_json(avatar),
            },
        )

    # ── POST /api/avatars — create a new avatar ─────────────────────────
    def _handle_create_avatar(self):
        user_id = self._bearer_user_id()
        if user_id is None:
            return
        try:
            body = self._read_json_body()
        except ValueError:
            return
        name = (body.get("name") or "").strip()
        if not name:
            return self._send_json(400, {"error": "name required"})
        # Apply the same value sanitization as /api/token so we don't
        # ever store an unknown voice or out-of-range field.
        cfg = sanitize(body)
        try:
            avatar = _DB.create_avatar(
                user_id=user_id,
                name=name,
                persona=cfg.get("persona") or None,
                voice=cfg.get("voice"),
                avatar_key=cfg.get("avatar") or None,
                tools=cfg.get("tools") or None,
                proactive=bool(cfg.get("proactive", False)),
                vision_watcher=bool(cfg.get("vision_watcher", True)),
            )
        except Exception as e:
            logger.exception("create_avatar failed")
            return self._send_json(500, {"error": f"create failed: {e}"})
        self._send_json(201, {"avatar": self._avatar_to_json(avatar)})

    # ── PATCH /api/avatars/:id — partial update ─────────────────────────
    def _handle_update_avatar(self, avatar_id: str):
        user_id = self._bearer_user_id()
        if user_id is None:
            return
        avatar = self._own_avatar_or_404(user_id, avatar_id)
        if avatar is None:
            return
        try:
            body = self._read_json_body()
        except ValueError:
            return
        cfg = sanitize(body)
        # Only fields actually present in the body are forwarded so the
        # caller can patch one field at a time.
        kwargs: dict = {}
        if "name" in body:
            kwargs["name"] = cfg.get("name") or avatar.name
        if "persona" in body:
            kwargs["persona"] = cfg.get("persona") or None
        if "voice" in body:
            kwargs["voice"] = cfg.get("voice")
        if "avatar" in body:
            kwargs["avatar_key"] = cfg.get("avatar") or None
        if "tools" in body:
            kwargs["tools"] = cfg.get("tools")
        if "proactive" in body:
            kwargs["proactive"] = bool(cfg.get("proactive", False))
        if "vision_watcher" in body:
            kwargs["vision_watcher"] = bool(cfg.get("vision_watcher", True))
        updated = _DB.update_avatar(avatar.id, **kwargs)
        self._send_json(
            200, {"avatar": self._avatar_to_json(updated) if updated else None}
        )

    # ── POST /api/avatars/:id/forget — wipe memory, KEEP avatar row ─────
    def _handle_forget_avatar(self, avatar_id: str):
        """Two-stage memory wipe for a single avatar:
          1. transcripts table (verbatim short-term recall)
          2. Mem0 distilled facts (long-term semantic memory)

        Avatar row + its persona/voice/tools settings are preserved —
        the user keeps the same companion but with a clean slate.

        Best-effort on the Mem0 side: a memory backend hiccup
        shouldn't block the transcript wipe (the visible part of the
        reset). We log the partial failure but still return 200.
        """
        user_id = self._bearer_user_id()
        if user_id is None:
            return
        avatar = self._own_avatar_or_404(user_id, avatar_id)
        if avatar is None:
            return
        # Step 1: transcripts (always succeeds if DB is reachable).
        transcripts_deleted = 0
        try:
            transcripts_deleted = _DB.delete_transcripts(avatar.id)
        except Exception:
            logger.exception("transcript wipe failed for avatar_id=%s", avatar.id)
        # Step 2: Mem0 (best-effort — no separate count available from
        # the Mem0 SDK, so we just report ok/error).
        import asyncio

        from memory import build_provider

        memory_ok = True
        try:
            provider = build_provider(_CONFIG)
            asyncio.run(provider.forget(avatar.id))
        except Exception:
            logger.exception("memory wipe failed for avatar_id=%s", avatar.id)
            memory_ok = False
        logger.info(
            "forget avatar: avatar_id=%s transcripts_deleted=%d memory_ok=%s",
            avatar.id,
            transcripts_deleted,
            memory_ok,
        )
        self._send_json(
            200,
            {
                "ok": True,
                "transcripts_deleted": transcripts_deleted,
                "memory_cleared": memory_ok,
            },
        )

    # ── DELETE /api/avatars/:id — wipe avatar + its memories ────────────
    def _handle_delete_avatar(self, avatar_id: str):
        user_id = self._bearer_user_id()
        if user_id is None:
            return
        avatar = self._own_avatar_or_404(user_id, avatar_id)
        if avatar is None:
            return
        # Wipe Mem0 memories for this avatar BEFORE deleting the row so
        # they don't end up orphaned. Best-effort; a memory failure
        # shouldn't block the user from removing the avatar.
        import asyncio

        from memory import build_provider

        try:
            provider = build_provider(_CONFIG)
            asyncio.run(provider.forget(avatar.id))
        except Exception:
            logger.exception(
                "memory wipe failed for avatar_id=%s — proceeding with delete",
                avatar.id,
            )
        deleted = _DB.delete_avatar(avatar.id)
        logger.info("delete avatar: avatar_id=%s row_deleted=%s", avatar.id, deleted)
        self._send_json(200, {"ok": True, "deleted": deleted})

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/token":
            # Legacy GET no longer supported — clients must POST the full config.
            self._send_json(405, {"error": "use POST /api/token with a JSON body"})
            return
        if parsed.path == "/api/me":
            # Return the currently-logged-in user's profile. UI hits this
            # on app boot to decide whether to show login or the avatar
            # picker.
            user_id = self._bearer_user_id()
            if user_id is None:
                return  # 401 already sent
            user = _DB.get_user_by_id(user_id)
            if user is None:
                return self._send_json(401, {"error": "user no longer exists"})
            return self._send_json(200, {"user": self._user_to_json(user)})
        if parsed.path == "/api/avatars":
            # List the calling user's avatars (most-recently-chatted first).
            user_id = self._bearer_user_id()
            if user_id is None:
                return
            avatars = _DB.list_avatars(user_id)
            return self._send_json(
                200, {"avatars": [self._avatar_to_json(a) for a in avatars]}
            )
        avatar_id = self._extract_avatar_id(parsed.path)
        if avatar_id is not None:
            user_id = self._bearer_user_id()
            if user_id is None:
                return
            avatar = self._own_avatar_or_404(user_id, avatar_id)
            if avatar is None:
                return
            return self._send_json(200, {"avatar": self._avatar_to_json(avatar)})
        if parsed.path == "/api/voices":
            # Kokoro voices are intersected with what the running Kokoro image
            # actually has; Orpheus voices are exposed unconditionally — the
            # agent will fail loudly at session start if ORPHEUS_BASE_URL is
            # missing, but we don't probe for Orpheus from the token server.
            available = _available_voice_ids()
            voices = [
                {"id": vid, "backend": "kokoro", **meta}
                for vid, meta in KOKORO_VOICES.items()
                if vid in available
            ]
            voices += [
                {"id": vid, "backend": "orpheus", **meta}
                for vid, meta in ORPHEUS_VOICES.items()
            ]
            # Supertonic exposed unconditionally too — same fail-loud-at-
            # session-start contract as Orpheus if SUPERTONIC_BASE_URL is unset.
            voices += [
                {"id": vid, "backend": "supertonic", **meta}
                for vid, meta in SUPERTONIC_VOICES.items()
            ]
            self._send_json(200, {"voices": voices})
            return
        if parsed.path == "/api/voice-sample":
            self._handle_voice_sample(parse_qs(parsed.query))
            return

        # Assets that live outside the React bundle (e.g. avatar GLBs) are
        # served from the source tree regardless of whether dist/ exists.
        if any(parsed.path.startswith(p) for p in _SOURCE_ROUTES):
            original = self.directory
            self.directory = str(UI_DIR)
            try:
                return super().do_GET()
            finally:
                self.directory = original

        return super().do_GET()


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True
    print(f"UI running at http://localhost:{PORT}")
    server.serve_forever()
