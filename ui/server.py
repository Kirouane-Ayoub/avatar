import http.client
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from livekit.api import AccessToken, VideoGrants

# Import the shared voice catalog from src/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from cues import MOODS  # noqa: E402
from voices import KOKORO_VOICES, ORPHEUS_VOICES, backend_for  # noqa: E402

load_dotenv()

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

ALLOWED_TOOLS = {"calculate", "set_reminder", "online_search", "internal_search"}
ALLOWED_MOODS = frozenset(MOODS)
ALLOWED_LANGUAGES = {"en", "ja"}
ALLOWED_BODIES = {"F", "M"}

MAX_NAME_LEN = 60
MAX_PERSONA_LEN = 2000
MAX_SAMPLE_TEXT = 200

TTS_BASE_URL = os.getenv("TTS_BASE_URL", "http://kokoro-tts:8880").rstrip("/")
TTS_MODEL = os.getenv("TTS_MODEL", "kokoro")
ORPHEUS_BASE_URL = (os.getenv("ORPHEUS_BASE_URL") or "").rstrip("/")
ORPHEUS_MODEL = os.getenv("ORPHEUS_MODEL", "orpheus")

# Serialize voice-sample proxy calls so a fast-clicking user can't pile up
# concurrent Kokoro generations and OOM-kill the container. One concurrent
# request is plenty for interactive preview; bump via env if you want more.
_TTS_CONCURRENCY = int(os.getenv("TTS_SAMPLE_CONCURRENCY", "1"))
_TTS_SEMAPHORE = threading.BoundedSemaphore(max(1, _TTS_CONCURRENCY))

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

    def _send_json(self, status: int, payload: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def _handle_voice_sample(self, qs: dict):
        voice = (qs.get("voice", [""])[0] or "").strip()
        text = (qs.get("text", [""])[0] or "").strip()[:MAX_SAMPLE_TEXT]
        backend = backend_for(voice)
        if backend == "orpheus":
            if voice not in ORPHEUS_VOICES:
                self._send_json(400, {"error": "unknown voice"})
                return
            if not ORPHEUS_BASE_URL:
                self._send_json(
                    501, {"error": "orpheus preview unavailable (ORPHEUS_BASE_URL unset)"}
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
            response_format = "wav"  # mlx-audio returns a buffered WAV when stream is unset
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
        if parsed.path != "/api/token":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0") or 0)
        try:
            body = json.loads(self.rfile.read(length)) if length else {}
            if not isinstance(body, dict):
                body = {}
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON"})
            return

        cfg = sanitize(body)
        room_name = f"session-{uuid.uuid4().hex[:8]}"
        token = (
            AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
            .with_identity("user")
            .with_metadata(json.dumps(cfg))
            .with_grants(VideoGrants(room_join=True, room=room_name))
            .to_jwt()
        )
        self._send_json(
            200, {"token": token, "url": LIVEKIT_EXTERNAL_URL, "config": cfg}
        )

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/token":
            # Legacy GET no longer supported — clients must POST the full config.
            self._send_json(405, {"error": "use POST /api/token with a JSON body"})
            return
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
