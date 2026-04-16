"""Custom LiveKit TTS plugin for Kokoro FastAPI server."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import aiohttp
from livekit.agents import tts, utils

logger = logging.getLogger("kokoro_tts")

SAMPLE_RATE = 24000


@dataclass
class KokoroConfig:
    base_url: str = "http://localhost:8880"
    model: str = "kokoro"
    voice: str = "af_heart"
    speed: float = 1.0


class KokoroTTS(tts.TTS):
    def __init__(self, config: KokoroConfig) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=SAMPLE_RATE,
            num_channels=1,
        )
        self._config = config

    def synthesize(self, text: str, **kwargs) -> "KokoroChunkedStream":
        return KokoroChunkedStream(self, text, **kwargs)


class KokoroChunkedStream(tts.ChunkedStream):
    def __init__(self, provider: KokoroTTS, text: str, **kwargs) -> None:
        super().__init__(tts=provider, input_text=text, **kwargs)
        self._provider = provider
        self._text = text

    async def _run(self, output_emitter) -> None:
        config = self._provider._config
        url = f"{config.base_url}/v1/audio/speech"
        payload = {
            "model": config.model,
            "input": self._text,
            "voice": config.voice,
            "response_format": "pcm",
            "speed": config.speed,
        }

        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/pcm",
        )

        logger.info("TTS request: voice=%s text=%r", config.voice, self._text[:80])

        payload["stream"] = True

        total_bytes = 0
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                async for chunk in resp.content.iter_chunked(4096):
                    if chunk:
                        output_emitter.push(chunk)
                        total_bytes += len(chunk)

        if total_bytes:
            logger.info("Streamed %d bytes of audio", total_bytes)
        else:
            logger.warning("No audio received from Kokoro")

        output_emitter.flush()
