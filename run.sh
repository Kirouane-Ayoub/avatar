#!/bin/bash
# Start the full Liva voice agent pipeline
# Usage: ./run.sh [start|stop|restart|logs|status]
#
# Orpheus TTS, ambient affect VLM (mlx-vlm), and Ollama embedding-model
# pre-flight all run by default. Opt out per-process by setting the env
# var to 0:
#   ORPHEUS=0 ./run.sh start    # Kokoro-only, no Orpheus
#   VLM=0 ./run.sh start        # no ambient affect watcher
#   OLLAMA=0 ./run.sh start     # skip Ollama check + model pull
#                                  (memory will fail unless Ollama is up
#                                  and the model is already pulled)
#   ORPHEUS=0 VLM=0 OLLAMA=0 ./run.sh start    # bare minimum
#
# About Ollama: it runs as its own background service on macOS (launched
# by the Ollama app or `brew services start ollama`). This script does
# NOT start the Ollama daemon — running `ollama serve` while the app is
# also running causes a port conflict on 11434. We only check that it's
# reachable and pull the embedding model (idempotent, fast if cached).

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

LLM_MODEL="${LLM_MODEL:-mlx-community/Qwen3.5-9B-MLX-4bit}"
LLM_PORT="${LLM_PORT:-8090}"
LLM_PID_FILE="$SCRIPT_DIR/.llm.pid"

# TurboQuant KV-cache quantization for the chat LLM. 3.5 bits = 3-bit keys
# + 4-bit values; cuts KV memory almost in half with negligible quality
# loss, which directly extends usable context length on the 27B + vision
# turns. Set LLM_KV_BITS=off to disable (uncompressed KV cache).
LLM_KV_BITS="${LLM_KV_BITS:-3.5}"
LLM_KV_QUANT_SCHEME="${LLM_KV_QUANT_SCHEME:-turboquant}"

# Orpheus TTS now runs natively via mlx-audio (was Docker'd llama.cpp+SNAC).
# Native = full Metal end-to-end. Docker'd containers have been removed
# from compose; ORPHEUS=1 just toggles the host-side daemon.
ORPHEUS_PORT="${ORPHEUS_PORT:-5005}"
ORPHEUS_PID_FILE="$SCRIPT_DIR/.orpheus.pid"
ORPHEUS_MODEL="${ORPHEUS_MODEL:-mlx-community/orpheus-3b-0.1-ft-6bit}"

# Ambient affect VLM (Blaizzy/mlx-vlm) — same native-on-Metal pattern as
# Orpheus. Optional: only started when VLM=1. Lazy-loads model on first
# request, same gotcha as Orpheus.
VLM_PORT="${VLM_PORT:-5006}"
VLM_PID_FILE="$SCRIPT_DIR/.vlm.pid"
VLM_MODEL="${VLM_MODEL:-mlx-community/Qwen3-VL-2B-Instruct-4bit}"
# Watcher KV-cache: leave uncompressed by default — the 2B model with
# tiny single-frame prompts has negligible KV pressure, so quantization
# adds overhead with no benefit. Set VLM_KV_BITS=3.5 to opt in.
VLM_KV_BITS="${VLM_KV_BITS:-}"
VLM_KV_QUANT_SCHEME="${VLM_KV_QUANT_SCHEME:-turboquant}"

start_llm() {
    if [ -f "$LLM_PID_FILE" ] && kill -0 "$(cat "$LLM_PID_FILE")" 2>/dev/null; then
        echo "[LLM] Already running (PID $(cat "$LLM_PID_FILE"))"
        return
    fi
    if ! command -v mlx_vlm.server >/dev/null 2>&1; then
        echo "[LLM] ERROR: mlx_vlm.server not on PATH. Install with:"
        echo "  uv tool install --with 'uvicorn[standard]' --with fastapi \\"
        echo "    --with python-multipart --with torch --with torchvision mlx-vlm"
        return 1
    fi
    # Hosted via mlx_vlm.server (not mlx_lm.server) so the same chat endpoint
    # also handles image_url content parts. Works for both VL models (e.g.
    # Qwen3.6-27B) and text-only models — mlx-vlm is a superset of mlx-lm.
    # Bind loopback only — Docker on macOS routes host.docker.internal to
    # the host's 127.0.0.1, so containers still reach this server, but
    # peers on the LAN (coffee-shop wifi, hotspot) cannot. The MLX server
    # has no auth — leaving it on 0.0.0.0 lets anyone on the network use
    # the LLM for free or DOS it.
    LLM_ARGS=(--host 127.0.0.1 --model "$LLM_MODEL" --port "$LLM_PORT")
    if [ -n "$LLM_KV_BITS" ] && [ "$LLM_KV_BITS" != "off" ]; then
        LLM_ARGS+=(--kv-bits "$LLM_KV_BITS" --kv-quant-scheme "$LLM_KV_QUANT_SCHEME")
        echo "[LLM] Starting mlx-vlm server: $LLM_MODEL on port $LLM_PORT (KV: ${LLM_KV_BITS}-bit ${LLM_KV_QUANT_SCHEME})"
    else
        echo "[LLM] Starting mlx-vlm server: $LLM_MODEL on port $LLM_PORT (KV cache uncompressed)"
    fi
    mlx_vlm.server "${LLM_ARGS[@]}" > /tmp/liva-llm.log 2>&1 &
    echo $! > "$LLM_PID_FILE"
    echo "[LLM] Started (PID $!), waiting for server..."

    for i in $(seq 1 30); do
        if curl -s "http://localhost:$LLM_PORT/v1/models" > /dev/null 2>&1; then
            echo "[LLM] Ready"
            return
        fi
        sleep 1
    done
    echo "[LLM] WARNING: Server not responding after 30s, check /tmp/liva-llm.log"
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
    # Loopback only — same reasoning as the LLM server. Containers reach
    # this via host.docker.internal which resolves to the host's loopback.
    mlx_audio.server --host 127.0.0.1 --port "$ORPHEUS_PORT" \
        > /tmp/liva-orpheus.log 2>&1 &
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
    echo "[Orpheus] WARNING: Server not responding after 15s, check /tmp/liva-orpheus.log"
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

start_vlm() {
    if [ -f "$VLM_PID_FILE" ] && kill -0 "$(cat "$VLM_PID_FILE")" 2>/dev/null; then
        echo "[VLM] Already running (PID $(cat "$VLM_PID_FILE"))"
        return
    fi
    if ! command -v mlx_vlm.server >/dev/null 2>&1; then
        echo "[VLM] ERROR: mlx_vlm.server not on PATH. Install with:"
        echo "  uv tool install --with 'uvicorn[standard]' --with fastapi \\"
        echo "    --with python-multipart --with torch --with torchvision mlx-vlm"
        echo "  (torch+torchvision are needed by Qwen2VL's video preprocessor"
        echo "   even though MLX runs the model itself.)"
        return 1
    fi
    # Loopback only — see start_llm comment.
    VLM_ARGS=(--host 127.0.0.1 --port "$VLM_PORT" --model "$VLM_MODEL")
    if [ -n "$VLM_KV_BITS" ] && [ "$VLM_KV_BITS" != "off" ]; then
        VLM_ARGS+=(--kv-bits "$VLM_KV_BITS" --kv-quant-scheme "$VLM_KV_QUANT_SCHEME")
        echo "[VLM] Starting mlx-vlm server on port $VLM_PORT (model: $VLM_MODEL, KV: ${VLM_KV_BITS}-bit ${VLM_KV_QUANT_SCHEME})"
    else
        echo "[VLM] Starting mlx-vlm server on port $VLM_PORT (model: $VLM_MODEL)"
    fi
    mlx_vlm.server "${VLM_ARGS[@]}" > /tmp/liva-vlm.log 2>&1 &
    echo $! > "$VLM_PID_FILE"
    echo "[VLM] Started (PID $!), waiting for server..."

    # Server binds quickly; the model only loads on first request, same
    # lazy-load gotcha as Orpheus. Pre-warm with a tiny request below so
    # the first ambient frame doesn't time out.
    for i in $(seq 1 15); do
        if curl -s "http://localhost:$VLM_PORT/" > /dev/null 2>&1; then
            echo "[VLM] Ready (model will lazy-load — pre-warming in background)"
            (curl -s -X POST "http://localhost:$VLM_PORT/v1/chat/completions" \
                -H "Content-Type: application/json" \
                -d "{\"model\":\"$VLM_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":1}" \
                > /dev/null 2>&1 &)
            return
        fi
        sleep 1
    done
    echo "[VLM] WARNING: Server not responding after 15s, check /tmp/liva-vlm.log"
}

stop_vlm() {
    if [ -f "$VLM_PID_FILE" ]; then
        PID=$(cat "$VLM_PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "[VLM] Stopping (PID $PID)"
            kill "$PID" 2>/dev/null
            wait "$PID" 2>/dev/null || true
        fi
        rm -f "$VLM_PID_FILE"
    else
        echo "[VLM] Not running"
    fi
}

prep_ollama() {
    # Ollama-as-embeddings pre-flight. We do NOT manage Ollama's daemon
    # (it runs as a macOS service / menu-bar app). We only verify it's
    # reachable and pull the embedding model so the first Mem0 write
    # doesn't fail with "model not found".
    if [ "${OLLAMA:-1}" != "1" ]; then
        echo "[Ollama] Skipped (OLLAMA=0)"
        return
    fi
    if ! command -v ollama >/dev/null 2>&1; then
        echo "[Ollama] WARNING: ollama not on PATH. Memory feature will fail."
        echo "  Install with:  brew install ollama   # or app from ollama.com"
        echo "  Then re-run ./run.sh start to pull the embedding model."
        return
    fi
    if ! curl -s "http://localhost:11434/api/tags" >/dev/null 2>&1; then
        echo "[Ollama] WARNING: port 11434 not reachable. Start the Ollama app or:"
        echo "  brew services start ollama"
        echo "  (memory feature will fail until Ollama is running)"
        return
    fi
    # Use whatever the agent will ask for; falls back to all-minilm
    # which is what the .env.example documents.
    local model="${MEM0_EMBEDDER:-all-minilm}"
    echo "[Ollama] Reachable. Pulling embedding model: $model (idempotent)"
    if ollama pull "$model" 2>&1 | tail -3; then
        echo "[Ollama] Ready (model $model available)"
    else
        echo "[Ollama] WARNING: pull failed for $model — check the model name"
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
    echo "── VLM ──"
    if [ -f "$VLM_PID_FILE" ] && kill -0 "$(cat "$VLM_PID_FILE")" 2>/dev/null; then
        echo "   Running (PID $(cat "$VLM_PID_FILE"))"
        echo "   Model: $VLM_MODEL"
    else
        echo "   Stopped"
    fi
    echo ""
    echo "── Ollama (embeddings, host service — see CLAUDE.md) ──"
    if curl -s "http://localhost:11434/api/tags" > /dev/null 2>&1; then
        echo "   Reachable at http://localhost:11434"
    else
        echo "   Not reachable (install/start Ollama if memory needs embeddings)"
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
    tail -20 /tmp/liva-llm.log 2>/dev/null || echo "   No LLM logs"
    echo ""
    echo "── VLM logs (last 20 lines) ──"
    tail -20 /tmp/liva-vlm.log 2>/dev/null || echo "   No VLM logs"
    echo ""
    echo "── Docker logs ──"
    docker-compose logs --tail 30
}

case "${1:-start}" in
    start)
        start_llm
        if [ "${ORPHEUS:-1}" = "1" ]; then start_orpheus; fi
        if [ "${VLM:-1}" = "1" ]; then start_vlm; fi
        prep_ollama
        start_docker
        echo ""
        echo "Liva is ready at http://localhost:3000"
        ;;
    stop)
        stop_docker
        stop_vlm
        stop_orpheus
        stop_llm
        echo "Liva stopped"
        ;;
    restart)
        stop_docker
        stop_vlm
        stop_orpheus
        stop_llm
        sleep 1
        start_llm
        if [ "${ORPHEUS:-1}" = "1" ]; then start_orpheus; fi
        if [ "${VLM:-1}" = "1" ]; then start_vlm; fi
        prep_ollama
        start_docker
        echo ""
        echo "Liva is ready at http://localhost:3000"
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
