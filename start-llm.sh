#!/bin/bash
# Start the local MLX LLM server (foreground; standalone use).
#
# This is the manual / "watch-the-logs" variant — runs in the foreground,
# logs to stderr/stdout, exits when you Ctrl+C. For background-managed use
# alongside Docker, use `./run.sh start` instead (which calls start_llm
# as a backgrounded daemon and tracks the PID).
#
# Resolution order for the model id:
#   1. positional arg ($1)
#   2. LLM_MODEL env var (auto-loaded from .env if present)
#   3. fallback default (current recommended Qwen)
# Same for the port: $2 → LLM_PORT → 8090.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load .env so LLM_MODEL / LLM_PORT match the rest of the stack.
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

MODEL="${1:-${LLM_MODEL:-mlx-community/Qwen3.6-27B-4bit}}"
PORT="${2:-${LLM_PORT:-8090}}"

if ! command -v mlx_lm.server >/dev/null 2>&1; then
    echo "ERROR: mlx_lm.server not on PATH. Install with:"
    echo "  uv tool install mlx-lm"
    exit 1
fi

echo "Starting MLX LLM server..."
echo "  Model: $MODEL"
echo "  Port:  $PORT"
echo ""
echo "The Docker agent connects via: http://host.docker.internal:$PORT/v1"
echo "──────────────────────────────────────────────────"

exec mlx_lm.server --model "$MODEL" --port "$PORT"
