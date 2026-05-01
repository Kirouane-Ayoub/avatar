# ───────── Stage 1: build the React UI bundle ─────────
FROM node:20-slim AS ui-builder
WORKDIR /ui

# Cache npm install on lockfile only
COPY ui/package.json ui/package-lock.json ./
RUN npm ci

# Build the React/Vite bundle into /ui/dist
COPY ui/ ./
RUN npm run build


# ───────── Stage 2: Python runtime ─────────
FROM python:3.11-slim

WORKDIR /app

# 1. Copy only dependency definition (cached unless deps change)
COPY pyproject.toml .

# 2. Install dependencies without building the project
RUN pip install --no-cache-dir \
    "livekit-agents>=1.3,<2.0" \
    "livekit-plugins-openai>=1.3,<2.0" \
    "livekit-plugins-silero>=1.3,<2.0" \
    "python-dotenv" \
    "numpy" \
    "soundfile" \
    "aiohttp" \
    "mem0ai" \
    "psycopg[binary,pool]"

# 3. Copy source code (only this rebuilds on code changes — fast)
COPY src/ src/
COPY ui/ ui/

# 4. Replace the (potentially stale) host-side ui/dist with the freshly
#    built bundle from stage 1, so the token server always serves the
#    UI that matches src/.
COPY --from=ui-builder /ui/dist ui/dist

EXPOSE 3000

CMD python ui/server.py & python src/agent.py start
