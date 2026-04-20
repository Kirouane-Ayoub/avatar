# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

BRO is a real-time speech-to-speech voice agent named **Lisa**, built with LiveKit. It features a 3D animated avatar with lip sync, vision capabilities (camera input), function calling (tools), and latency metrics. The pipeline: User speaks → STT (Faster Whisper) → LLM (Qwen 3.5, OpenAI-compatible) → TTS (Kokoro with word timestamps) → Avatar lip sync + audio playback.

## Running

```bash
# Full stack via Docker Compose
docker compose up --build
# UI at http://localhost:3000

# Management script
./run.sh start|stop|restart|status|logs

# If using local MLX LLM (Mac Metal GPU)
./start-llm.sh                    # Terminal 1 (port 8090)
docker compose up                 # Terminal 2

# Benchmark pipeline latency
python benchmark.py --rounds 5
```

## Architecture

**Agent** (`src/agent.py`): LiveKit `Agent` subclass. Connects STT, LLM, TTS. Handles vision by capturing video frames → encoding to JPEG → injecting as `ImageContent` into the LLM chat context via `on_user_turn_completed`. Publishes metrics and lip sync word timestamps to the UI via LiveKit DataChannel (topic: `"metrics"`).

**TTS** (`src/kokoro_tts.py`): Custom LiveKit TTS plugin. Uses Kokoro's `/dev/captioned_speech` endpoint which returns audio (base64 PCM) + word-level timestamps. The timestamps are sent to the UI for avatar lip sync. The regular `/v1/audio/speech` endpoint does NOT provide timestamps.

**Orpheus TTS** (`src/orpheus_tts.py`): Alternative TTS using llama.cpp + SNAC codec. Requires `snac` + `torch` (optional deps via `pip install -e ".[orpheus]"`). Not used by default.

**Tools** (`src/tools.py`): Function tools decorated with `@function_tool`. All async. Weather uses wttr.in (no API key). Tools are passed to the `Agent` constructor.

**UI** (`ui/index.html`): Single-file app. Left panel: 3D avatar (TalkingHead.js + Three.js + Ready Player Me GLB model). Right panel: chat bubbles, mood/gesture/view controls, latency metrics. Lip sync driven by word timestamps from agent → character-to-viseme mapping → `head.setValue()` calls. Setup overlay handles device selection before connecting.

**Token server** (`ui/server.py`): Serves static files + `/api/token` endpoint. Generates unique room names per session (`lisa-{uuid}`) so disconnect/reconnect always gets a fresh agent.

## Key Data Flows

- **Lip sync**: Kokoro returns `{audio, timestamps}` → agent publishes `{type:"lipsync", words, wtimes, wdurations}` via DataChannel → UI queues lipsync data → when audio starts playing (detected via MediaStream analyser), steps through word timestamps mapping chars to Oculus visemes via `head.setValue()`.

- **Vision**: `rtc.VideoStream` captures frames continuously → `encode()` to JPEG 512x512 → stored as base64 data URL → injected into user's `ChatMessage.content` as `ImageContent` in `on_user_turn_completed` → old images stripped from chat history each turn.

- **Metrics**: `conversation_item_added` event → extract `transcription_delay`, `llm_node_ttft`, `tts_node_ttfb`, `e2e_latency` from `ChatMessage.metrics`. Also `metrics_collected` (deprecated but still fires) for `STTMetrics.duration` and `TTSMetrics.ttfb`.

## Docker Services

All on `bro-network` bridge. Agent reaches services by container name: `livekit-server:7880`, `kokoro-tts:8880`, `speaches:8000`. Browser connects to LiveKit via `LIVEKIT_EXTERNAL_URL` (localhost). LLM is external (not in compose).

Kokoro has ONNX CPU optimizations tuned for M4 Pro (4 threads, parallel execution, reduced chunk size for lower TTFB).

## Environment

All config via `.env`. Required: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `TTS_BASE_URL`, `STT_BASE_URL`. The `enable_thinking: False` is passed to Qwen 3.5 via `extra_body` to disable chain-of-thought reasoning (critical for voice — without it the model generates endless thinking tokens).

## Important Gotchas

- `AutoSubscribe.SUBSCRIBE_ALL` causes an STT crash (`start_time_offset must be non-negative`) when video + audio arrive at different times. Use `AUDIO_ONLY` and manually subscribe to video tracks via `track_published` event.
- LiveKit's `video_sampler` / `push_video` only works with Realtime API models (GPT-4o Realtime). For regular chat completion models, manually capture frames and inject as `ImageContent`.
- TalkingHead's `streamAudio()` does NOT auto-generate visemes from audio. It only plays audio. Lip sync requires either pre-computed visemes or word timestamps passed alongside audio.
- `setValue()` on TalkingHead sets morph targets but they can be overridden by the animation system. The `system` priority level works but expires after the specified duration.
- Kokoro's `/dev/captioned_speech` with `stream: false` returns full audio + timestamps as JSON. With `stream: true` it chunks audio but loses timestamp alignment.
- `createMediaElementSource()` doesn't work for analyzing LiveKit audio tracks (CORS). Use `createMediaStreamSource(new MediaStream([track.mediaStreamTrack]))` instead.
- Docker on macOS can't access Metal GPU — MLX must run natively. Containers reach it via `host.docker.internal`.

## Code Style

Pre-commit hooks enforce: `black` formatter (Python 3.11 target), YAML validation, trailing whitespace removal, EOF newlines.
