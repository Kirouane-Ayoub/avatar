#!/bin/bash
# Start local MLX LLM server for the voice agent pipeline
# Runs natively on Mac (MLX needs Metal GPU, can't run in Docker)

MODEL="${1:-mlx-community/Qwen3.5-2B-MLX-4bit}"
PORT="${2:-8090}"

echo "Starting MLX LLM server..."
echo "  Model: $MODEL"
echo "  Port:  $PORT"
echo ""
echo "The Docker agent connects via: http://host.docker.internal:$PORT/v1"
echo "──────────────────────────────────────────────────"

mlx_lm.server --model "$MODEL" --port "$PORT"
