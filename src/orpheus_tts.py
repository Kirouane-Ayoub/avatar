"""Custom LiveKit TTS plugin for Orpheus 3B served via llama.cpp.

Orpheus generates audio as special token IDs via the completions endpoint.
These tokens are decoded into audio using the SNAC neural audio codec.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import numpy as np
import snac
import torch
from livekit.agents import tts, utils

import aiohttp

logger = logging.getLogger("orpheus_tts")

SNAC_SAMPLE_RATE = 24000
AVAILABLE_VOICES = ["tara", "leah", "jess", "leo", "dan", "mia", "zac", "zoe"]


@dataclass
class OrpheusConfig:
    base_url: str = "http://localhost:8080"
    model: str = "orpheus"
    voice: str = "tara"
    temperature: float = 0.6
    top_p: float = 0.9
    max_tokens: int = 8192
    repetition_penalty: float = 1.1


class OrpheusTTS(tts.TTS):
    """LiveKit TTS plugin that calls Orpheus via llama.cpp completions API."""

    def __init__(self, config: OrpheusConfig) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=SNAC_SAMPLE_RATE,
            num_channels=1,
        )
        self._config = config
        self._snac_model: snac.SNAC | None = None
        self._snac_device = "mps" if torch.backends.mps.is_available() else "cpu"

    def _ensure_snac(self) -> snac.SNAC:
        if self._snac_model is None:
            logger.info("Loading SNAC model on %s", self._snac_device)
            self._snac_model = snac.SNAC.from_pretrained("hubertsiuzdak/snac_24khz")
            self._snac_model.eval().to(self._snac_device)
            logger.info("SNAC model loaded")
        return self._snac_model

    def _build_prompt(self, text: str) -> str:
        voice = self._config.voice
        if voice not in AVAILABLE_VOICES:
            voice = "tara"
        return f"<|audio|>{voice}: {text}<|eot_id|>"

    @staticmethod
    def _token_to_id(token_string: str, index: int) -> int | None:
        """Convert a custom token string like '<custom_token_12345>' to a SNAC code ID.

        Matches the standalone orpheus_tts.py logic exactly.
        """
        token_string = token_string.strip()
        prefix = "<custom_token_"
        start = token_string.rfind(prefix)
        if start == -1:
            return None
        token = token_string[start:]
        if not token.endswith(">"):
            return None
        try:
            number = int(token[len(prefix) : -1])
            token_id = number - 10 - ((index % 7) * 4096)
            return token_id if token_id > 0 else None
        except (ValueError, IndexError):
            return None

    def _decode_audio(self, frames: list[int]) -> bytes:
        """Decode SNAC token IDs into raw PCM audio bytes using full output."""
        num_frames = len(frames) // 7
        if num_frames == 0:
            return b""

        frames = frames[: num_frames * 7]
        device = self._snac_device
        ft = torch.tensor(frames, dtype=torch.int32, device=device)

        codes_0 = torch.zeros(num_frames, dtype=torch.int32, device=device)
        codes_1 = torch.zeros(num_frames * 2, dtype=torch.int32, device=device)
        codes_2 = torch.zeros(num_frames * 4, dtype=torch.int32, device=device)

        for j in range(num_frames):
            idx = j * 7
            codes_0[j] = ft[idx]
            codes_1[j * 2] = ft[idx + 1]
            codes_1[j * 2 + 1] = ft[idx + 4]
            codes_2[j * 4] = ft[idx + 2]
            codes_2[j * 4 + 1] = ft[idx + 3]
            codes_2[j * 4 + 2] = ft[idx + 5]
            codes_2[j * 4 + 3] = ft[idx + 6]

        codes = [codes_0.unsqueeze(0), codes_1.unsqueeze(0), codes_2.unsqueeze(0)]

        for c in codes:
            if torch.any(c < 0) or torch.any(c > 4096):
                return b""

        model = self._ensure_snac()
        with torch.inference_mode():
            audio_hat = model.decode(codes)
            audio_np = audio_hat.squeeze().detach().cpu().numpy()
            audio_np = np.clip(audio_np, -1.0, 1.0)
            audio_int16 = (audio_np * 32767).astype(np.int16)
            return audio_int16.tobytes()

    def synthesize(self, text: str, **kwargs) -> "ChunkedStream":
        return ChunkedStream(self, text, **kwargs)

    def stream(self, **kwargs) -> "SynthesizeStream":
        return SynthesizeStream(self, **kwargs)


async def _stream_sse_tokens(url: str, payload: dict) -> tuple[list[int], int]:
    """Stream tokens from llama.cpp SSE and return (buffer, count).

    Exactly mirrors the standalone script's stream_tokens + token_to_id loop.
    """
    buffer: list[int] = []
    count = 0

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=120),
        ) as resp:
            resp.raise_for_status()
            # Read line-by-line for SSE
            while True:
                line_bytes = await resp.content.readline()
                if not line_bytes:
                    break
                line_str = line_bytes.decode("utf-8").strip()
                if not line_str.startswith("data: "):
                    continue
                data_str = line_str[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                if "choices" not in data or not data["choices"]:
                    continue
                text = data["choices"][0].get("text", "")
                if not text:
                    continue

                # A single chunk may contain multiple tokens
                for part in text.split(">"):
                    part = part.strip()
                    if not part:
                        continue
                    part = part + ">"
                    tid = OrpheusTTS._token_to_id(part, count)
                    if tid is not None and tid > 0:
                        buffer.append(tid)
                        count += 1

    logger.info("Received %d valid audio tokens from %d total", count, count)
    return buffer, count


class ChunkedStream(tts.ChunkedStream):
    """Non-streaming synthesis: streams tokens, decodes in 4-frame chunks like standalone."""

    def __init__(self, provider: OrpheusTTS, text: str, **kwargs) -> None:
        super().__init__(tts=provider, input_text=text, **kwargs)
        self._provider = provider
        self._text = text

    async def _run(self, output_emitter) -> None:
        config = self._provider._config
        prompt = self._provider._build_prompt(self._text)

        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=SNAC_SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/pcm",
        )

        url = f"{config.base_url}/v1/completions"
        payload = {
            "prompt": prompt,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
            "top_p": config.top_p,
            "repeat_penalty": config.repetition_penalty,
            "stream": True,
        }

        logger.info("TTS request: voice=%s text=%r", config.voice, self._text[:80])

        # Collect all tokens first (matches standalone approach)
        buffer, count = await _stream_sse_tokens(url, payload)

        if not buffer:
            logger.warning("No audio tokens received")
            output_emitter.flush()
            return

        # Decode all tokens at once using full audio output
        audio_bytes = self._provider._decode_audio(buffer)
        if audio_bytes:
            output_emitter.push(audio_bytes)

        logger.info(
            "Decoded %d tokens into %d bytes of audio",
            count,
            len(audio_bytes) if audio_bytes else 0,
        )

        output_emitter.flush()


class SynthesizeStream(tts.SynthesizeStream):
    """Streaming synthesis: decodes tokens as they arrive in 4-frame windows."""

    def __init__(self, provider: OrpheusTTS, **kwargs) -> None:
        super().__init__(tts=provider, **kwargs)
        self._provider = provider

    async def _run(self, output_emitter) -> None:
        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=SNAC_SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/pcm",
            stream=True,
        )

        # Collect all text chunks into one string, then synthesize as one segment
        full_text = ""
        async for input_ev in self._input_ch:
            if isinstance(input_ev, str):
                full_text += input_ev

        if not full_text.strip():
            return

        segment_id = utils.shortuuid()
        output_emitter.start_segment(segment_id=segment_id)

        config = self._provider._config
        prompt = self._provider._build_prompt(full_text)

        url = f"{config.base_url}/v1/completions"
        payload = {
            "prompt": prompt,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
            "top_p": config.top_p,
            "repeat_penalty": config.repetition_penalty,
            "stream": True,
        }

        buffer, count = await _stream_sse_tokens(url, payload)

        if buffer:
            trimmed = buffer[: (len(buffer) // 7) * 7]
            if trimmed:
                audio_bytes = self._provider._decode_audio(trimmed)
                if audio_bytes:
                    output_emitter.push(audio_bytes)

        output_emitter.end_segment()
