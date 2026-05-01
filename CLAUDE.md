# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Avatar is a real-time speech-to-speech voice agent stack built with LiveKit. The name is a nod to the Hollywood craft of dubbing voice and sound onto a face that's already moving — which is literally what the lipsync + TTS pipeline does. The default persona ships as **Liva** but is fully configurable per session (name, persona, voice, avatar, tools) via the setup wizard. The system features a 3D animated avatar with lip sync, vision capabilities (camera input), function calling (tools), and latency metrics. The pipeline: User speaks → STT (Faster Whisper) → LLM (default `mlx-community/Qwen3.5-9B-MLX-4bit`, running natively via `mlx_vlm.server` because the same server transparently handles VL models too — set `LLM_MODEL=mlx-community/Qwen3.6-27B-4bit` or any `*-VL-*` model to enable in-conversation image_url content) → TTS (Kokoro for word-timestamped lipsync, or Orpheus via `mlx-audio` for higher quality) → Avatar lip sync + audio playback.

## Running

```bash
# Recommended: use the management script — sources .env, brings up the host-side
# MLX LLM (and optionally Orpheus TTS) plus the Docker stack in the right order.
./run.sh start|stop|restart|status|logs

# Include Orpheus TTS (host-side mlx-audio with Metal):
ORPHEUS=1 ./run.sh start

# Just the Docker stack (Kokoro-only, no host MLX):
docker-compose up --build         # UI at http://localhost:3000

# UI dev server (Vite, with proxy to server.py on :3000)
cd ui && npm run dev              # :5173, hot reload
cd ui && npm run typecheck        # TS check only
cd ui && npm run build            # Production build → ui/dist

# Benchmark pipeline latency
python benchmark.py --rounds 5
```

## Host-side dependencies (one-time)

MLX servers run natively on the Mac so they can use Metal. Install via `uv`:

```bash
# Chat LLM + ambient affect VLM (both served by mlx-vlm). mlx-vlm is a
# superset of mlx-lm — same OpenAI-compatible server, also accepts
# image_url content parts. mlx-vlm's pyproject is missing torch/torchvision
# (Qwen2VL's video preprocessor needs them) plus the FastAPI runtime deps.
uv tool install --with 'uvicorn[standard]' --with fastapi \
  --with python-multipart --with torch --with torchvision mlx-vlm

# Orpheus TTS — mlx-audio's pyproject is missing several runtime deps, so
# inject them explicitly. WITHOUT --with the server crashes on import.
uv tool install --with 'uvicorn[standard]' --with fastapi \
  --with python-multipart --with webrtcvad-wheels mlx-audio

# Ollama (for Mem0 embeddings). Ships an OpenAI-compatible /v1/embeddings
# endpoint out of the box on port 11434, runs as a host service on macOS.
# Install via brew or the Ollama app from ollama.com, then pull the
# small embedding model the agent uses by default:
brew install ollama   # or download the macOS app
ollama pull all-minilm   # ~46 MB, 384-dim MiniLM
```

`mlx-lm` is no longer needed — `run.sh:start_llm` now invokes `mlx_vlm.server`. You can `uv tool uninstall mlx-lm` if you have it.

`run.sh:start_orpheus` checks for `mlx_audio.server` on PATH and prints this exact command if it's missing.

## Architecture

**Agent** (`src/agent.py`): LiveKit `Agent` subclass. Connects STT, LLM, TTS. Handles vision by capturing video frames → encoding to JPEG → injecting as `ImageContent` into the LLM chat context via `on_user_turn_completed`. Publishes metrics and lip sync word timestamps to the UI via LiveKit DataChannel (topic: `"metrics"`). System prompt includes the canonical cue vocabulary from `src/cues.py`.

**Cues** (`src/cues.py` + `ui/src/data/cues.ts`): Canonical vocabulary for `[mood:X][gesture:Y][pose:Z]` tags the LLM emits. Two files (Python + TypeScript) must stay in sync — pure data, no logic. Server-side validation (`ui/server.py:ALLOWED_MOODS`) imports from `src/cues.py` via `sys.path` shim.

**TTS** (`src/kokoro_tts.py`): Custom LiveKit TTS plugin. Uses Kokoro's `/dev/captioned_speech` endpoint which returns audio (base64 PCM) + **word-level** timestamps. Phoneme-level timing exists in Kokoro internals but the FastAPI wrapper collapses it before serializing — see `Lipsync` section below for how the UI compensates client-side. The regular `/v1/audio/speech` endpoint does NOT provide timestamps.

**Orpheus TTS** (`src/orpheus_tts.py`): Alternative TTS via host-side [`mlx-audio`](https://github.com/Blaizzy/mlx-audio) — runs the Orpheus 3B model on Metal end-to-end (autoregressive token generation **and** SNAC decode). The agent (in Docker) talks to the native daemon at `http://host.docker.internal:5005/v1/audio/speech` with `stream: true, response_format: "pcm"` so int16 LE bytes arrive without a RIFF header to skip. The client coalesces TCP arrivals into 4800-byte (100 ms) frames and pushes them through LiveKit's segment-based emitter (`output_emitter.initialize(stream=True)` + `start_segment` / `end_segment` — required for multi-push reframing; without `stream=True` audio sounds "token-by-token" choppy). No word timestamps (lipsync falls back to jaw-only via `useLipsyncDriver.ts`). Activated per-session by selecting an Orpheus voice; backend routing via `voices.py:backend_for(voice)`. Default model is `mlx-community/orpheus-3b-0.1-ft-4bit` (~1.8 GB, faster); 6bit/8bit available. The English fine-tune covers the canonical eight voices (`tara, leah, jess, leo, dan, mia, zac, zoe`); multilingual voices in the catalog require swapping `ORPHEUS_MODEL` to a language-specific repo (per-voice model mapping not yet wired). Bring up with `ORPHEUS=1 ./run.sh start` — `run.sh` then launches `mlx_audio.server` natively. The model loads lazily on first request (~5–10 s after download). Was previously a triple of Docker services (`orpheus-tts` wrapper + `orpheus-llama-cpp` + `orpheus-model-init`); moved native because Docker on macOS has no Metal.

**Voices** (`src/voices.py`): Two catalogs. `KOKORO_VOICES` is the single-letter-prefix Kokoro set; `ORPHEUS_VOICES` is the (mostly English) Orpheus set with `stt`/`description` per voice. `backend_for(voice)` returns `"kokoro"` or `"orpheus"` and drives the agent's TTS factory. `stt_language_for(voice_id)` derives the Whisper language: prefix lookup for Kokoro, explicit `stt` field for Orpheus. Mirrored client-side as `ui/src/data/voice_lang.ts:languageFromVoice()` (must contain the same Orpheus voice→language map).

**Tools** (`src/tools.py`): Function tools decorated with `@function_tool`. All async. Weather uses wttr.in (no API key). Tools are passed to the `Agent` constructor.

**UI** (`ui/`): React + TypeScript + Vite app. Entry is `ui/index.html` (importmap shell that loads TalkingHead + per-language `lipsync-*` modules from CDN), real app is in `ui/src/`. Two top-level views in `App.tsx`:
- **Setup wizard** (`SetupWizard.tsx`) — avatar rail, mood, persona, voice picker, abilities chips, device overlay (mic + camera dropdowns + tiny circular cam preview) on the stage-preview.
- **Session view** (`SessionView.tsx`) — full-bleed avatar stage with status badge + metrics pill + camera self-view bubble; right side panel with chat transcript and call controls (Whisper / Mic / Cam / Leave).

**Token server** (`ui/server.py`): Serves the React `dist/` (or source tree paths like `/avatar-zoo/`) + `/api/token` endpoint + `/api/voices` (Kokoro voices intersected with the running Kokoro server, plus Orpheus voices unconditionally — each tagged with `backend: "kokoro" | "orpheus"`) + `/api/voice-sample` (proxy with concurrency cap that backend-routes to the right TTS server). Generates unique room names per session (`lisa-{uuid}`) so disconnect/reconnect always gets a fresh agent.

## Key Data Flows

### Lipsync (per-language)

Kokoro returns `{audio, words, wtimes, wdurations}`. Agent publishes `{type:"lipsync", …}` via DataChannel. The UI driver (`ui/src/hooks/useLipsyncDriver.ts`) routes by language:

| Language | Strategy | Source |
|---|---|---|
| `en` | TalkingHead's `LipsyncEn` phonemizer (real phonemes per word) | CDN module via importmap |
| `fr` | TalkingHead's `LipsyncFr` phonemizer | CDN module via importmap |
| `ja` | Kana → mora viseme map (90 entries, hiragana + katakana + handles `ー` long vowel) | `ui/src/data/kana_viseme.ts` |
| any other | Jaw-only (amplitude-driven from MediaStream analyser) | inline |

Adding another phonemized language: add an importmap entry in `index.html`, declare the `Window.LipsyncXx` global in `types/talkinghead.d.ts`, register a factory in `phonemes.ts:FACTORIES`. No driver changes needed.

The driver writes morphs **directly** to `mesh.morphTargetInfluences[i]`, bypassing `head.setValue()` whose `system`-slot smoothing is too slow for phoneme-rate visemes (especially on subtle-morph models like VRoid).

### Vision

`rtc.VideoStream` captures frames continuously → `encode()` to JPEG 512x512 → stored as base64 data URL → injected into user's `ChatMessage.content` as `ImageContent` in `on_user_turn_completed` → old images stripped from chat history each turn.

### Cue dispatch

Agent emits `[mood:X][gesture:Y][pose:Z]` at the start of every reply. The agent strips these from the spoken text and publishes them as separate DataChannel messages (`{type:"mood"|"gesture"|"pose", value:"…"}`). UI's `SessionView` routes:
- `mood` → React state → `head.setMood()` (via `useTalkingHead`'s mood-effect)
- `gesture` → `head.playGesture(name, 3, false, 1000)`
- `pose` → `head.setPoseFromTemplate(template, 2000)`

**Auto view**: 250 ms debounced. `[mood]` only → `head` view (face close-up); `[mood][gesture]` → `upper`; `[mood][gesture][pose]` → `full`. The agent owns view because gesture/pose framing belongs to the character, not the user.

### Mic flow (with whisper mode)

UI does **not** use LiveKit's high-level `setMicrophoneEnabled`. Instead `useSession.ts` does:

```
getUserMedia → MediaStreamSource → GainNode → MediaStreamDestination → publishTrack
```

This lets whisper mode flip `gain.gain.value` from 1.0 → 2.5 (≈ +8 dB) and toggle `noiseSuppression` via `applyConstraints` on the raw track, all live, no republish. Mute/unmute still uses `pub.mute()/unmute()` on the publication.

### Language resolution

Voice fully drives language. `requestToken` (UI) sends `language: languageFromVoice(setup.voice)`; agent (`agent.py`) ignores `cfg.language` whenever a voice is supplied and re-derives via `stt_language_for(voice)`. Avatars carry no language metadata. Any avatar pairs with any voice.

### Metrics

`conversation_item_added` event → extract `transcription_delay`, `llm_node_ttft`, `tts_node_ttfb`, `e2e_latency` from `ChatMessage.metrics`. Also `metrics_collected` (deprecated but still fires) for `STTMetrics.duration` and `TTSMetrics.ttfb`. Published as `{type:"pipeline", …}` on the `metrics` topic; UI renders them as a colored pill (good ≤ green, ok ≤ amber, slow > red).

### Persistent memory (Mem0)

Per-user long-term memory via the Mem0 SDK, **embedded** inside the agent process (not a separate REST server — fewer containers). Storage: the new `postgres-memory` container (pgvector image). Fact-extraction LLM: small VLM at `:5006` by default (keeps the 27B chat LLM free of extraction load). Embeddings: local sentence-transformers (`BAAI/bge-small-en-v1.5`, ~130 MB) cached in the `hf-cache` Docker volume.

Wrapper at `src/memory.py` (Protocol + `Mem0Provider` + `NullProvider`) — the seam so a future `ZepProvider` (or cloud-managed alt) can drop in by changing one line in `agent.py`. `NullProvider` kicks in when `MEM0_PG_HOST` is unset, so memory is fully optional. Best-effort semantics: every call is wrapped in try/except — Mem0 failures NEVER break the conversation pipeline.

Per-user identity comes from `participant.identity`. The token server (`ui/server.py`) currently hardcodes that to `"user"` so today's deployment is single-user. When real auth lands the token server starts issuing per-user identities and the agent picks them up automatically (zero changes to memory code).

Wired in `agent.py` at two points:
- **Session start**: `memory.recall(user_id)` → injected into the system prompt via `memory_block(...)` so Lisa knows things from prior sessions before her first reply.
- **`conversation_item_added` event**: `memory.record_turn(user_id, role, text)` for both user and assistant messages. Cue tags stripped from assistant text first so memory doesn't see `[mood:happy]`. Fact extraction runs async inside Mem0 — does NOT block the next turn.

## Docker Services

All on `avatar-network` bridge. Agent reaches services by container name: `livekit-server:7880`, `kokoro-tts:8880`, `speaches:8000`, `postgres-memory:5432`. Browser connects to LiveKit via `LIVEKIT_EXTERNAL_URL` (localhost). LLM is external (not in compose).

Kokoro has ONNX CPU optimizations tuned for M4 Pro (4 threads, parallel execution, reduced chunk size for lower TTFB).

**Orpheus is no longer in compose** — it runs natively via `mlx-audio` (see Orpheus TTS section above). Bring it up alongside the rest with `ORPHEUS=1 ./run.sh start`; Docker stays Kokoro-only.

## Environment

All config via `.env`. Required: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `TTS_BASE_URL`, `STT_BASE_URL`. Optional but used when `ORPHEUS=1`: `ORPHEUS_BASE_URL` (default `http://host.docker.internal:5005`), `ORPHEUS_MODEL` (default `mlx-community/orpheus-3b-0.1-ft-4bit`), `ORPHEUS_PORT`. The `enable_thinking: False` is passed to Qwen via `extra_body` to disable chain-of-thought reasoning (critical for voice — without it the model generates endless thinking tokens). **`run.sh` sources `.env` near the top** so changes to `LLM_MODEL` / `ORPHEUS_MODEL` take effect on the next start; previously the host-side daemons fell through to a hardcoded default and ignored `.env`.

## Important Gotchas

- `AutoSubscribe.SUBSCRIBE_ALL` causes an STT crash (`start_time_offset must be non-negative`) when video + audio arrive at different times. Use `AUDIO_ONLY` and manually subscribe to video tracks via `track_published` event.
- LiveKit's `video_sampler` / `push_video` only works with Realtime API models (GPT-4o Realtime). For regular chat completion models, manually capture frames and inject as `ImageContent`.
- TalkingHead's `streamAudio()` does NOT auto-generate visemes from audio. It only plays audio. Lip sync requires either pre-computed visemes or word timestamps passed alongside audio.
- `setValue()` on TalkingHead routes through a `system` slot with exponential smoothing capped at ~5 updates/sec — fine for mood morphs, far too slow for phoneme-rate visemes. The driver bypasses this by writing `mesh.morphTargetInfluences[i]` directly.
- Kokoro's `/dev/captioned_speech` with `stream: false` returns full audio + timestamps as JSON. With `stream: true` it chunks audio but loses timestamp alignment. Phoneme-level timing exists in Kokoro internals (`result.tokens`) but the FastAPI wrapper aggregates to word level before responding.
- `createMediaElementSource()` doesn't work for analyzing LiveKit audio tracks (CORS). Use `createMediaStreamSource(new MediaStream([track.mediaStreamTrack]))` instead.
- Docker on macOS can't access Metal GPU — MLX must run natively. Containers reach it via `host.docker.internal`.
- **Avatars need ARKit blendshapes** (~72 morph targets per face mesh) for moods, gestures, and English/French lipsync to do anything. Models with only `mouthOpen` + `mouthSmile` (under ~1.5 MB GLBs are usually a tell) silently fail — `setMood()` and viseme writes are no-ops because the targets don't exist on the mesh.
- **`backdrop-filter: blur(...)` over the WebGL canvas** (e.g. on overlay glass pills) tanks framerate of the avatar idle, because every canvas repaint forces re-blur of the overlay region. Use solid-ish opaque backgrounds for overlays that float over the TalkingHead canvas, or restrict blur to elements that don't overlap the canvas.
- **Vite + importmap**: TalkingHead, `lipsync-*` modules, and `three` are loaded from the browser's importmap (in `ui/index.html`) and exposed on `window`. They're externalized in `vite.config.ts` (`external: [/^three($|\/)/, 'talkinghead', /^lipsync-/]`) so the bundler doesn't try to resolve them. New CDN-loaded module → add to externals + importmap + `Window` declaration.
- **mlx-audio's pyproject is missing runtime deps** (`uvicorn`, `fastapi`, `python-multipart`, `webrtcvad`). A bare `uv tool install mlx-audio` produces a `mlx_audio.server` binary that crashes on import. Use the `--with` form documented in the Host-side dependencies section above.
- **Orpheus streaming has SNAC chunk-boundary artifacts** ("echo" on words straddling a chunk seam) because mlx-audio's per-chunk decode isn't a sliding window. `OrpheusConfig.streaming_interval` defaults to `2.0` s so most short replies fit in one chunk → no boundary → no echo. Lowering it to `0.5` s improves TTFB but reintroduces the artifact for any reply >2 s.
- **Orpheus model loads lazily on first request** — the very first TTS call after starting `mlx_audio.server` triggers a download (if not cached) + an in-RAM load that blocks the FastAPI worker. The agent typically times out and the session ends. Pre-warm with a one-line curl after launch (`POST /v1/audio/speech` with any short text) before pointing the agent at it.
- **Docker on macOS Colima is starved by default** (4 CPU / 8 GB on M4 Pro). For Orpheus + Kokoro + Whisper to run smoothly, bump to at least `colima start --cpu 8 --memory 24`. Settings persist in `~/.colima/default/colima.yaml`.
- **`avatar-network` is pinned by name** in `docker-compose.yml` (`networks: avatar-network: name: avatar-network`) so Docker reuses the same network across `up` cycles; without this, profile toggles or interrupted starts left containers holding references to a dead network UUID and caused recurring `failed to set up container networking: network ... not found` errors.
- **Dockerfile is multi-stage** (`node:20-slim AS ui-builder` → `python:3.11-slim`) so the React bundle is rebuilt inside the image from current source rather than copied from a possibly-stale host `ui/dist/`. Before this, host `ui/dist/` was baked in via `COPY ui/ ui/` and silently drifted behind `src/`.
- **Use `docker-compose` (hyphen, v1)**, never `docker compose` (space, v2 plugin) — the v2 plugin form fails with `unknown flag` on the user's machine. Same for any docs/scripts you edit.
- **Use `uv` for Python package management** (`uv tool install` / `uv add` / `uv pip install`) — never `pip` / `pipx` / `python -m venv`.
- **mlx-vlm uses non-OpenAI usage field names** (`input_tokens`/`output_tokens` instead of `prompt_tokens`/`completion_tokens`) which crashes strict OpenAI clients like livekit-agents (`pydantic ValidationError: completion_tokens / prompt_tokens — Input should be a valid integer [input_value=None]` → `APIConnectionError`). Until upstream fixes it, we patch `OpenAIUsage` in `~/.local/share/uv/tools/mlx-vlm/lib/python*/site-packages/mlx_vlm/server.py`: rename the fields to OpenAI-spec names with `validation_alias=AliasChoices(...)` for backwards-compat with internal callers + `populate_by_name=True`. The patch survives until the next `uv tool upgrade mlx-vlm` / `--force` reinstall, after which it must be reapplied. The marker comment in the patched class begins with `LIVA PATCH:` for easy grep / re-detection.

## Code Style

Pre-commit hooks enforce: `black` formatter (Python 3.11 target), YAML validation, trailing whitespace removal, EOF newlines. The React/TS app uses standard 2-space indent and the existing component conventions (functional components, hooks for state/effects, type-only imports where possible).
