# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

BRO is a real-time speech-to-speech voice agent named **Lisa**, built with LiveKit. It features a 3D animated avatar with lip sync, vision capabilities (camera input), function calling (tools), and latency metrics. The pipeline: User speaks → STT (Faster Whisper) → LLM (Qwen 3.5, OpenAI-compatible) → TTS (Kokoro with word timestamps) → Avatar lip sync + audio playback.

## Running

```bash
# Full stack via Docker Compose
docker-compose up --build
# UI at http://localhost:3000

# Management script
./run.sh start|stop|restart|status|logs

# If using local MLX LLM (Mac Metal GPU)
./start-llm.sh                    # Terminal 1 (port 8090)
docker-compose up                 # Terminal 2

# UI dev server (Vite, with proxy to server.py on :3000)
cd ui && npm run dev              # :5173, hot reload
cd ui && npm run typecheck        # TS check only
cd ui && npm run build            # Production build → ui/dist

# Benchmark pipeline latency
python benchmark.py --rounds 5
```

## Architecture

**Agent** (`src/agent.py`): LiveKit `Agent` subclass. Connects STT, LLM, TTS. Handles vision by capturing video frames → encoding to JPEG → injecting as `ImageContent` into the LLM chat context via `on_user_turn_completed`. Publishes metrics and lip sync word timestamps to the UI via LiveKit DataChannel (topic: `"metrics"`). System prompt includes the canonical cue vocabulary from `src/cues.py`.

**Cues** (`src/cues.py` + `ui/src/data/cues.ts`): Canonical vocabulary for `[mood:X][gesture:Y][pose:Z]` tags the LLM emits. Two files (Python + TypeScript) must stay in sync — pure data, no logic. Server-side validation (`ui/server.py:ALLOWED_MOODS`) imports from `src/cues.py` via `sys.path` shim.

**TTS** (`src/kokoro_tts.py`): Custom LiveKit TTS plugin. Uses Kokoro's `/dev/captioned_speech` endpoint which returns audio (base64 PCM) + **word-level** timestamps. Phoneme-level timing exists in Kokoro internals but the FastAPI wrapper collapses it before serializing — see `Lipsync` section below for how the UI compensates client-side. The regular `/v1/audio/speech` endpoint does NOT provide timestamps.

**Orpheus TTS** (`src/orpheus_tts.py`): Alternative TTS via host-side [`mlx-audio`](https://github.com/Blaizzy/mlx-audio) — runs the Orpheus 3B model on Metal end-to-end (autoregressive token generation **and** SNAC decode). The agent (in Docker) talks to the native daemon at `http://host.docker.internal:5005/v1/audio/speech` with `stream: true, response_format: "pcm"` so int16 LE bytes arrive without a RIFF header to skip. The client coalesces TCP arrivals into 4800-byte (100 ms) frames and pushes them through LiveKit's segment-based emitter. No word timestamps (lipsync falls back to jaw-only via `useLipsyncDriver.ts`). Activated per-session by selecting an Orpheus voice; backend routing via `voices.py:backend_for(voice)`. The English fine-tune (`mlx-community/orpheus-3b-0.1-ft-6bit`) covers the canonical eight voices (`tara, leah, jess, leo, dan, mia, zac, zoe`); multilingual voices in the catalog require swapping `ORPHEUS_MODEL` to a language-specific repo (per-voice model mapping not yet wired). Bring up with `ORPHEUS=1 ./run.sh start`. Was previously a triple of Docker services (`orpheus-tts` wrapper + `orpheus-llama-cpp` + `orpheus-model-init`); moved native because Docker on macOS has no Metal.

**Voices** (`src/voices.py`): Kokoro voice catalog. `stt_language_for(voice_id)` derives the language code from the voice prefix (`a/b → en`, `f → fr`, `j → ja`, etc.). Mirrored client-side as `ui/src/data/voice_lang.ts:languageFromVoice()`.

**Tools** (`src/tools.py`): Function tools decorated with `@function_tool`. All async. Weather uses wttr.in (no API key). Tools are passed to the `Agent` constructor.

**UI** (`ui/`): React + TypeScript + Vite app. Entry is `ui/index.html` (importmap shell that loads TalkingHead + per-language `lipsync-*` modules from CDN), real app is in `ui/src/`. Two top-level views in `App.tsx`:
- **Setup wizard** (`SetupWizard.tsx`) — avatar rail, mood, persona, voice picker, abilities chips, device overlay (mic + camera dropdowns + tiny circular cam preview) on the stage-preview.
- **Session view** (`SessionView.tsx`) — full-bleed avatar stage with status badge + metrics pill + camera self-view bubble; right side panel with chat transcript and call controls (Whisper / Mic / Cam / Leave). Replaces the deprecated `legacy.html` reference monolith.

**Token server** (`ui/server.py`): Serves the React `dist/` (or source tree paths like `/avatar-zoo/`) + `/api/token` endpoint + `/api/voices` (cached intersection of upstream Kokoro voices with our catalog) + `/api/voice-sample` (proxy with concurrency cap). Generates unique room names per session (`lisa-{uuid}`) so disconnect/reconnect always gets a fresh agent.

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

## Docker Services

All on `bro-network` bridge. Agent reaches services by container name: `livekit-server:7880`, `kokoro-tts:8880`, `speaches:8000`. Browser connects to LiveKit via `LIVEKIT_EXTERNAL_URL` (localhost). LLM is external (not in compose).

Kokoro has ONNX CPU optimizations tuned for M4 Pro (4 threads, parallel execution, reduced chunk size for lower TTFB).

**Orpheus is no longer in compose** — it runs natively via `mlx-audio` (see Orpheus TTS section above). Bring it up alongside the rest with `ORPHEUS=1 ./run.sh start`; Docker stays Kokoro-only.

## Environment

All config via `.env`. Required: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `TTS_BASE_URL`, `STT_BASE_URL`. The `enable_thinking: False` is passed to Qwen 3.5 via `extra_body` to disable chain-of-thought reasoning (critical for voice — without it the model generates endless thinking tokens).

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

## Code Style

Pre-commit hooks enforce: `black` formatter (Python 3.11 target), YAML validation, trailing whitespace removal, EOF newlines. The React/TS app uses standard 2-space indent and the existing component conventions (functional components, hooks for state/effects, type-only imports where possible).
