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

MODEL="${1:-${LLM_MODEL:-mlx-community/Qwen3.5-9B-MLX-4bit}}"
PORT="${2:-${LLM_PORT:-8090}}"
KV_BITS="${LLM_KV_BITS:-3.5}"
KV_QUANT_SCHEME="${LLM_KV_QUANT_SCHEME:-turboquant}"

if ! command -v mlx_vlm.server >/dev/null 2>&1; then
    echo "ERROR: mlx_vlm.server not on PATH. Install with:"
    echo "  uv tool install --with 'uvicorn[standard]' --with fastapi \\"
    echo "    --with python-multipart --with torch --with torchvision mlx-vlm"
    exit 1
fi

ARGS=(--host 0.0.0.0 --model "$MODEL" --port "$PORT")
if [ -n "$KV_BITS" ] && [ "$KV_BITS" != "off" ]; then
    ARGS+=(--kv-bits "$KV_BITS" --kv-quant-scheme "$KV_QUANT_SCHEME")
    KV_DESC="${KV_BITS}-bit ${KV_QUANT_SCHEME}"
else
    KV_DESC="uncompressed"
fi

echo "Starting MLX LLM server (via mlx-vlm — handles text and vision)..."
echo "  Model:    $MODEL"
echo "  Port:     $PORT"
echo "  KV cache: $KV_DESC"
echo ""
echo "The Docker agent connects via: http://host.docker.internal:$PORT/v1"
echo "──────────────────────────────────────────────────"

exec mlx_vlm.server "${ARGS[@]}"
