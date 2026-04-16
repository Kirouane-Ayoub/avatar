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
    "aiohttp"

# 3. Copy source code (only this rebuilds on code changes — fast)
COPY src/ src/
COPY ui/ ui/

EXPOSE 3000

CMD python ui/server.py & python src/agent.py start
