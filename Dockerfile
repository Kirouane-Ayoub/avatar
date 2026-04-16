FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY . .

# UI server port
EXPOSE 3000

# Start the UI server and the agent
CMD python ui/server.py & python src/agent.py start
