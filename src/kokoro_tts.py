"""Custom LiveKit TTS plugin for Kokoro FastAPI server with word timestamps."""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass

import aiohttp
from livekit.agents import tts, utils

logger = logging.getLogger("kokoro_tts")

SAMPLE_RATE = 24000

# Safety net: any bracketed cue tag that slipped past the agent's tts_node
# filter must NOT be sent to Kokoro, or it would be spoken aloud.
_BRACKET_TAG_RE = re.compile(r"\[\s*(?:mood|gesture|pose|view)\s*:[^\]]{0,40}\]", re.IGNORECASE)


@dataclass
class KokoroConfig:
    base_url: str = "http://localhost:8880"
    model: str = "kokoro"
    voice: str = "af_heart"
    speed: float = 1.0
    on_timestamps: object = None  # callback(timestamps_list)


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

        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/pcm",
        )

        # Strip any cue tag that survived upstream filtering
        clean_text = _BRACKET_TAG_RE.sub("", self._text).strip()
        if clean_text != self._text.strip():
            logger.warning("Stripped leftover cue tag(s) from TTS input")
        if not clean_text:
            logger.info("TTS skipped: empty after cue strip")
            output_emitter.flush()
            return

        logger.info("TTS request: voice=%s text=%r", config.voice, clean_text[:80])

        # Use captioned_speech for word timestamps
        url = f"{config.base_url}/dev/captioned_speech"
        payload = {
            "model": config.model,
            "input": clean_text,
            "voice": config.voice,
            "response_format": "pcm",
            "speed": config.speed,
            "stream": False,
            "return_timestamps": True,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

                # Decode audio from base64
                audio_b64 = data.get("audio", "")
                audio_bytes = base64.b64decode(audio_b64)
                timestamps = data.get("timestamps", [])

                if audio_bytes:
                    # Send timestamps BEFORE audio so browser has them ready
                    if config.on_timestamps and timestamps:
                        config.on_timestamps(timestamps)

                    output_emitter.push(audio_bytes)
                    logger.info("Got %d bytes audio, %d word timestamps",
                                len(audio_bytes), len(timestamps))
                else:
                    logger.warning("No audio received from Kokoro")

        output_emitter.flush()
