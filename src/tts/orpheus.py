from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import aiohttp
from livekit.agents import tts, utils

logger = logging.getLogger("orpheus_tts")

SAMPLE_RATE = 24000
# 100ms at 24kHz mono int16. Coalesce TCP arrivals to this size before
# pushing to LiveKit so the emitter sees consistent frame-aligned writes.
_FRAME_BYTES = 4800

# Safety net: any bracketed cue tag that slipped past the agent's tts_node
# filter must NOT be sent to the TTS, or it would be spoken aloud.
_BRACKET_TAG_RE = re.compile(
    r"\[\s*(?:mood|gesture|pose|view)\s*:[^\]]{0,40}\]", re.IGNORECASE
)


@dataclass
class OrpheusConfig:
    """Config for the host-side mlx-audio server (Blaizzy/mlx-audio).

    Architecture: the agent (in Docker) POSTs to a native macOS
    `mlx_audio.server` process via host.docker.internal. mlx-audio runs the
    Orpheus model on Metal end-to-end — both autoregressive token generation
    and SNAC decoding — and streams int16 PCM back as it's produced.

    Defaults match the Orpheus model card's recommended sampling params; the
    server's own SpeechRequest defaults are different (temperature=0.7,
    top_p=0.95, repetition_penalty=1.0) so we pass these explicitly.
    """

    base_url: str = "http://localhost:5005"
    model: str = "mlx-community/orpheus-3b-0.1-ft-6bit"
    voice: str = "tara"
    temperature: float = 0.6
    top_p: float = 0.8
    repetition_penalty: float = 1.3
    # Seconds of audio mlx-audio buffers before yielding a stream chunk.
    # Larger value = fewer chunk boundaries = fewer SNAC stream-decode
    # artifacts (mlx-audio's streaming decode doesn't use a sliding window
    # across chunks, so words straddling a boundary get a doubled syllable
    # / "echo" feel). 2.0 means most short replies fit in one chunk.
    # Trade-off: TTFB rises to ~the first chunk's wall-clock generation
    # time. On M4 Pro Metal that's still well under the perceived
    # response time of the LLM, so net UX is better.
    streaming_interval: float = 2.0
    max_tokens: int = 1200


class OrpheusTTS(tts.TTS):
    def __init__(self, config: OrpheusConfig) -> None:
        # streaming=False on the capability refers to streaming TEXT INPUT
        # (we get a full text string per utterance from the agent). The
        # AUDIO OUTPUT is streamed inside ChunkedStream._run via the
        # emitter's segment-based stream mode.
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=SAMPLE_RATE,
            num_channels=1,
        )
        self._config = config

    def synthesize(self, text: str, **kwargs) -> "OrpheusChunkedStream":
        return OrpheusChunkedStream(self, text, **kwargs)


class OrpheusChunkedStream(tts.ChunkedStream):
    def __init__(self, provider: OrpheusTTS, text: str, **kwargs) -> None:
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
            stream=True,
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

        url = f"{config.base_url.rstrip('/')}/v1/audio/speech"
        # response_format=pcm gives raw int16 LE — no RIFF header to skip,
        # no per-chunk re-headering as you'd get with stream+wav.
        payload = {
            "model": config.model,
            "input": clean_text,
            "voice": config.voice,
            "response_format": "pcm",
            "stream": True,
            "streaming_interval": config.streaming_interval,
            "temperature": config.temperature,
            "top_p": config.top_p,
            "repetition_penalty": config.repetition_penalty,
            "max_tokens": config.max_tokens,
        }

        segment_id = utils.shortuuid()
        output_emitter.start_segment(segment_id=segment_id)

        carry = bytearray()
        chunks_pushed = 0
        bytes_pushed = 0

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.content.iter_any():
                        if not chunk:
                            continue
                        carry.extend(chunk)
                        # Push whole 100ms frames; keep any trailing bytes
                        # in `carry` so int16 sample alignment is preserved
                        # across iterations.
                        while len(carry) >= _FRAME_BYTES:
                            frame = bytes(carry[:_FRAME_BYTES])
                            output_emitter.push(frame)
                            chunks_pushed += 1
                            bytes_pushed += len(frame)
                            del carry[:_FRAME_BYTES]

            # Tail flush — last partial frame (if any) so the closing
            # syllable isn't truncated.
            if carry:
                output_emitter.push(bytes(carry))
                chunks_pushed += 1
                bytes_pushed += len(carry)
        finally:
            output_emitter.end_segment()

        logger.info(
            "Streamed %d frames / %d bytes of PCM",
            chunks_pushed,
            bytes_pushed,
        )

        output_emitter.flush()
