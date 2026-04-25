#!/bin/bash
# Start the full Lisa voice agent pipeline
# Usage: ./run.sh [start|stop|restart|logs|status]
#
# Set ORPHEUS=1 to include the optional Orpheus TTS profile:
#   ORPHEUS=1 ./run.sh start

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Load .env so LLM_MODEL (and other vars docker-compose already reads) are
# also visible to the host-side MLX server we launch below. Without this,
# changing LLM_MODEL in .env had no effect on what model run.sh boots.
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

LLM_MODEL="${LLM_MODEL:-mlx-community/Qwen3.6-27B-4bit}"
LLM_PORT="${LLM_PORT:-8090}"
LLM_PID_FILE="$SCRIPT_DIR/.llm.pid"

# Orpheus TTS now runs natively via mlx-audio (was Docker'd llama.cpp+SNAC).
# Native = full Metal end-to-end. Docker'd containers have been removed
# from compose; ORPHEUS=1 just toggles the host-side daemon.
ORPHEUS_PORT="${ORPHEUS_PORT:-5005}"
ORPHEUS_PID_FILE="$SCRIPT_DIR/.orpheus.pid"
ORPHEUS_MODEL="${ORPHEUS_MODEL:-mlx-community/orpheus-3b-0.1-ft-6bit}"

start_llm() {
    if [ -f "$LLM_PID_FILE" ] && kill -0 "$(cat "$LLM_PID_FILE")" 2>/dev/null; then
        echo "[LLM] Already running (PID $(cat "$LLM_PID_FILE"))"
        return
    fi
    echo "[LLM] Starting MLX server: $LLM_MODEL on port $LLM_PORT"
    mlx_lm.server --model "$LLM_MODEL" --port "$LLM_PORT" > /tmp/lisa-llm.log 2>&1 &
    echo $! > "$LLM_PID_FILE"
    echo "[LLM] Started (PID $!), waiting for server..."

    for i in $(seq 1 30); do
        if curl -s "http://localhost:$LLM_PORT/v1/models" > /dev/null 2>&1; then
            echo "[LLM] Ready"
            return
        fi
        sleep 1
    done
    echo "[LLM] WARNING: Server not responding after 30s, check /tmp/lisa-llm.log"
}

stop_llm() {
    if [ -f "$LLM_PID_FILE" ]; then
        PID=$(cat "$LLM_PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "[LLM] Stopping (PID $PID)"
            kill "$PID" 2>/dev/null
            wait "$PID" 2>/dev/null || true
        fi
        rm -f "$LLM_PID_FILE"
    else
        echo "[LLM] Not running"
    fi
}

start_orpheus() {
    if [ -f "$ORPHEUS_PID_FILE" ] && kill -0 "$(cat "$ORPHEUS_PID_FILE")" 2>/dev/null; then
        echo "[Orpheus] Already running (PID $(cat "$ORPHEUS_PID_FILE"))"
        return
    fi
    if ! command -v mlx_audio.server >/dev/null 2>&1; then
        echo "[Orpheus] ERROR: mlx_audio.server not on PATH. Install with:"
        echo "  uv tool install --with 'uvicorn[standard]' --with fastapi \\"
        echo "    --with python-multipart --with webrtcvad-wheels mlx-audio"
        return 1
    fi
    echo "[Orpheus] Starting mlx-audio server on port $ORPHEUS_PORT"
    mlx_audio.server --host 0.0.0.0 --port "$ORPHEUS_PORT" \
        > /tmp/lisa-orpheus.log 2>&1 &
    echo $! > "$ORPHEUS_PID_FILE"
    echo "[Orpheus] Started (PID $!), waiting for server..."

    # Server is up almost instantly; the model only loads on first request.
    for i in $(seq 1 15); do
        if curl -s "http://localhost:$ORPHEUS_PORT/" > /dev/null 2>&1; then
            echo "[Orpheus] Ready (model $ORPHEUS_MODEL will lazy-load on first request)"
            return
        fi
        sleep 1
    done
    echo "[Orpheus] WARNING: Server not responding after 15s, check /tmp/lisa-orpheus.log"
}

stop_orpheus() {
    if [ -f "$ORPHEUS_PID_FILE" ]; then
        PID=$(cat "$ORPHEUS_PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "[Orpheus] Stopping (PID $PID)"
            kill "$PID" 2>/dev/null
            wait "$PID" 2>/dev/null || true
        fi
        rm -f "$ORPHEUS_PID_FILE"
    else
        echo "[Orpheus] Not running"
    fi
}

start_docker() {
    echo "[Docker] Starting services..."
    docker-compose up --build -d --remove-orphans
    echo "[Docker] Services started"
}

stop_docker() {
    echo "[Docker] Stopping services..."
    docker-compose down --remove-orphans
}

show_status() {
    echo ""
    echo "── LLM ──"
    if [ -f "$LLM_PID_FILE" ] && kill -0 "$(cat "$LLM_PID_FILE")" 2>/dev/null; then
        echo "   Running (PID $(cat "$LLM_PID_FILE"))"
        curl -s "http://localhost:$LLM_PORT/v1/models" 2>/dev/null | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    for m in d['data']: print(f\"   Model: {m['id']}\")
except: print('   Not responding')
" 2>/dev/null || echo "   Not responding"
    else
        echo "   Stopped"
    fi
    echo ""
    echo "── Docker ──"
    docker-compose ps --format "   {{.Name}}: {{.Status}}" 2>/dev/null || echo "   No containers"
    echo ""
    echo "── UI ──"
    echo "   http://localhost:3000"
    echo ""
}

show_logs() {
    echo "── LLM logs (last 20 lines) ──"
    tail -20 /tmp/lisa-llm.log 2>/dev/null || echo "   No LLM logs"
    echo ""
    echo "── Docker logs ──"
    docker-compose logs --tail 30
}

case "${1:-start}" in
    start)
        start_llm
        if [ "${ORPHEUS:-0}" = "1" ]; then start_orpheus; fi
        start_docker
        echo ""
        echo "Lisa is ready at http://localhost:3000"
        ;;
    stop)
        stop_docker
        stop_orpheus
        stop_llm
        echo "Lisa stopped"
        ;;
    restart)
        stop_docker
        stop_orpheus
        stop_llm
        sleep 1
        start_llm
        if [ "${ORPHEUS:-0}" = "1" ]; then start_orpheus; fi
        start_docker
        echo ""
        echo "Lisa is ready at http://localhost:3000"
        ;;
    logs)
        show_logs
        ;;
    status)
        show_status
        ;;
    *)
        echo "Usage: ./run.sh [start|stop|restart|logs|status]"
        exit 1
        ;;
esac
