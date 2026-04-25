# BRO - Voice Agent

A fully local, real-time speech-to-speech voice agent built with LiveKit.

**Stack:** Qwen 3.5 (LLM) + Kokoro (TTS) + Faster Whisper (STT) + LiveKit

## Project Structure

```
BRO/
├── src/            # Agent & TTS plugins
├── ui/             # Web frontend + token server
├── config/         # LiveKit server config
├── docker-compose.yml
├── Dockerfile
└── .env
```

## Quick Start

1. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your service URLs and API keys
   ```

2. **Run with Docker Compose:**
   ```bash
   docker-compose up --build
   ```

3. **Open** `http://localhost:3000`, select your mic, and click **Connect**.

## Run Locally (without Docker)

If you already have LiveKit, TTS, and STT services running:

```bash
pip install -e .
python ui/server.py &
python src/agent.py start
```

## Environment Variables

| Variable | Description |
|---|---|
| `LIVEKIT_URL` | LiveKit server WebSocket URL |
| `LIVEKIT_API_KEY` | LiveKit API key |
| `LIVEKIT_API_SECRET` | LiveKit API secret |
| `LLM_BASE_URL` | LLM endpoint (OpenAI-compatible) |
| `LLM_API_KEY` | LLM API key |
| `LLM_MODEL` | LLM model name |
| `TTS_BASE_URL` | Kokoro TTS server URL |
| `STT_BASE_URL` | Speaches/Whisper server URL |

See `.env.example` for all options.

## Services (Docker Compose)

| Service | Port | Description |
|---|---|---|
| `livekit-server` | 7880 | WebRTC signaling & media |
| `kokoro-tts` | 8880 | Text-to-speech |
| `speaches` | 8000 | Speech-to-text (Faster Whisper) |
| `agent` | 3000 | Voice agent + Web UI |
