# CPU build of timonharz/Orpheus-FastAPI (the streaming fork).
# The fork only ships Dockerfile.gpu; this is a minimal CPU equivalent
# that mirrors Lex-au's Dockerfile.cpu structure but clones the streaming
# fork instead.
#
# Build context is just this directory (the source is cloned at build
# time), so the context is a few bytes — no project files needed.

FROM ubuntu:22.04

ARG ORPHEUS_REPO_URL=https://github.com/timonharz/Orpheus-FastAPI.git
ARG ORPHEUS_REF=main

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
        python3.10 python3-pip python3-venv \
        libsndfile1 ffmpeg portaudio19-dev \
        git ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1001 appuser && mkdir -p /app && chown -R appuser:appuser /app
USER appuser
WORKDIR /app

# Clone the fork. --depth 1 keeps the image small; pin via ORPHEUS_REF if
# you want reproducibility (e.g. a specific commit SHA).
RUN git clone --depth 1 --branch ${ORPHEUS_REF} ${ORPHEUS_REPO_URL} src

WORKDIR /app/src

RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# CPU-only torch wheels from PyTorch's index, then the fork's requirements.
RUN pip3 install --no-cache-dir torch torchvision torchaudio \
        --index-url https://download.pytorch.org/whl/cpu \
    && pip3 install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    USE_GPU=false

EXPOSE 5005

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5005", "--workers", "1"]
