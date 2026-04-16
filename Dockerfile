FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY . .

# UI server port
EXPOSE 3000

# LiveKit agent defaults
ENV LIVEKIT_URL=ws://localhost:7880
ENV LIVEKIT_API_KEY=devkey
ENV LIVEKIT_API_SECRET=secret

# Start the UI server and the agent
CMD python ui/server.py dev & python agent.py start
