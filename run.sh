#!/bin/bash
# Start the full Lisa voice agent pipeline
# Usage: ./run.sh [start|stop|restart|logs|status]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

LLM_MODEL="${LLM_MODEL:-mlx-community/Qwen3.5-2B-MLX-4bit}"
LLM_PORT="${LLM_PORT:-8090}"
LLM_PID_FILE="$SCRIPT_DIR/.llm.pid"

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

start_docker() {
    echo "[Docker] Starting services..."
    docker compose up --build -d
    echo "[Docker] Services started"
}

stop_docker() {
    echo "[Docker] Stopping services..."
    docker compose down
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
    docker compose ps --format "   {{.Name}}: {{.Status}}" 2>/dev/null || echo "   No containers"
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
    docker compose logs --tail 30
}

case "${1:-start}" in
    start)
        start_llm
        start_docker
        echo ""
        echo "Lisa is ready at http://localhost:3000"
        ;;
    stop)
        stop_docker
        stop_llm
        echo "Lisa stopped"
        ;;
    restart)
        stop_docker
        stop_llm
        sleep 1
        start_llm
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
