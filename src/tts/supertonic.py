from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

import aiohttp
from livekit.agents import tts, utils

logger = logging.getLogger("supertonic_tts")

# Supertonic outputs studio-grade 44.1kHz 16-bit mono WAV — note this is
# NOT the 24kHz that Kokoro/Orpheus use. We declare 44100 here and let
# LiveKit resample to the room's rate.
SAMPLE_RATE = 44100

# Safety net: any bracketed cue tag that slipped past the agent's tts_node
# filter must NOT be sent to the TTS, or it would be spoken aloud.
_BRACKET_TAG_RE = re.compile(
    r"\[\s*(?:mood|gesture|pose|view)\s*:[^\]]{0,40}\]", re.IGNORECASE
)


def _strip_v1(base_url: str) -> str:
    """Normalise a base URL to the server root (no trailing slash, no
    trailing /v1). The user-facing env var is sometimes pasted with the
    ``/v1`` suffix (since the OpenAI path is ``/v1/audio/speech``); we
    append the full ``/v1/audio/speech`` ourselves, so strip it here to
    avoid ``/v1/v1/audio/speech``."""
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    return root


def _wav_to_pcm(buf: bytes) -> bytes:
    """Extract the raw PCM payload from a RIFF/WAVE container by walking
    the chunk list to find ``data`` (the header is usually 44 bytes but
    isn't guaranteed — some encoders insert ``LIST``/``fact`` chunks
    first). Returns the buffer unchanged if it isn't a WAV (e.g. the
    server was configured to return raw PCM)."""
    if len(buf) < 12 or buf[:4] != b"RIFF" or buf[8:12] != b"WAVE":
        return buf
    pos = 12
    while pos + 8 <= len(buf):
        chunk_id = buf[pos : pos + 4]
        size = int.from_bytes(buf[pos + 4 : pos + 8], "little")
        body = pos + 8
        if chunk_id == b"data":
            return buf[body : body + size]
        # Chunks are word-aligned: an odd size is followed by a pad byte.
        pos = body + size + (size & 1)
    logger.warning("WAV had no data chunk; sending nothing")
    return b""


@dataclass
class SupertonicConfig:
    """Config for the Supertonic TTS server (supertone-inc/supertonic).

    OpenAI-compatible: POST ``{base_url}/v1/audio/speech`` with
    {model, input, voice, speed, lang}. ``voice`` is a style name
    (F1-F5 / M1-M5). The server returns a buffered 44.1kHz 16-bit mono
    WAV — no streaming PCM and no word timestamps (lipsync falls back to
    amplitude-driven jaw-only, same as Orpheus)."""

    base_url: str = "http://localhost:7788"
    model: str = "supertonic-3"
    voice: str = "F2"
    speed: float = 1.0
    # Language code the server should synthesize in ("na" lets Supertonic
    # auto-fallback). None omits the field entirely.
    lang: Optional[str] = None


class SupertonicTTS(tts.TTS):
    def __init__(self, config: SupertonicConfig) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=SAMPLE_RATE,
            num_channels=1,
        )
        self._config = config

    def synthesize(self, text: str, **kwargs) -> "SupertonicChunkedStream":
        return SupertonicChunkedStream(self, text, **kwargs)


class SupertonicChunkedStream(tts.ChunkedStream):
    def __init__(self, provider: SupertonicTTS, text: str, **kwargs) -> None:
        super().__init__(tts=provider, input_text=text, **kwargs)
        self._provider = provider
        self._text = text

    async def _run(self, output_emitter) -> None:
        config = self._provider._config

        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/pcm",
        )

        clean_text = _BRACKET_TAG_RE.sub("", self._text).strip()
        if clean_text != self._text.strip():
            logger.warning("Stripped leftover cue tag(s) from TTS input")
        if not clean_text:
            logger.info("TTS skipped: empty after cue strip")
            output_emitter.flush()
            return

        logger.info(
            "TTS request: voice=%s model=%s text=%r",
            config.voice,
            config.model,
            clean_text[:80],
        )

        url = f"{_strip_v1(config.base_url)}/v1/audio/speech"
        # response_format=wav — Supertonic's OpenAI endpoint serves a
        # buffered WAV (wav/flac/ogg supported; no pcm/stream). We strip
        # the RIFF header to raw PCM below before pushing.
        payload = {
            "model": config.model,
            "input": clean_text,
            "voice": config.voice,
            "response_format": "wav",
            "speed": config.speed,
        }
        if config.lang:
            payload["lang"] = config.lang

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                resp.raise_for_status()
                wav_bytes = await resp.read()

        pcm = _wav_to_pcm(wav_bytes)
        if pcm:
            output_emitter.push(pcm)
            logger.info("Got %d bytes WAV -> %d bytes PCM", len(wav_bytes), len(pcm))
        else:
            logger.warning("No audio received from Supertonic")

        output_emitter.flush()
