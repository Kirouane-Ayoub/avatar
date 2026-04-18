"""LiveKit voice agent: fully local speech-to-speech using Qwen + Kokoro TTS + Faster Whisper."""

import asyncio
import json
import logging
import os

from dotenv import load_dotenv

load_dotenv()

from livekit import rtc
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    WorkerOptions,
    cli,
)
from livekit.agents.llm import ImageContent
from livekit.agents.utils.images import encode, EncodeOptions, ResizeOptions
import base64
from livekit.plugins import openai, silero
from kokoro_tts import KokoroConfig, KokoroTTS
from tools import ALL_TOOLS

logger = logging.getLogger("voice-agent")

LLM_URL = os.environ["LLM_BASE_URL"]
LLM_API_KEY = os.environ["LLM_API_KEY"]
TTS_URL = os.environ["TTS_BASE_URL"]
STT_URL = os.environ["STT_BASE_URL"]
LLM_MODEL = os.environ["LLM_MODEL"]
TTS_MODEL = os.getenv("TTS_MODEL", "kokoro")
TTS_VOICE = os.getenv("TTS_VOICE", "af_heart")
STT_MODEL = os.getenv("STT_MODEL", "Systran/faster-whisper-base")

SYSTEM_PROMPT = """\
Your name is Lisa. You are a friendly voice assistant with vision. \
NEVER repeat or echo the user's words. \
Always respond with your own original answer. \
Keep replies to 1-2 short sentences. Be helpful and direct. \
When you receive an image from the user's camera, describe what you see if asked. \
Only mention the camera/image when the user asks about it. \
You have tools available — use them when the user asks for the time, \
weather, math, dice rolls, coin flips, or random numbers.\
"""


class VoiceAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=SYSTEM_PROMPT,
            tools=ALL_TOOLS,
        )
        self._last_image_url = None
        self._frame_count = 0

    def set_frame(self, frame: rtc.VideoFrame):
        """Encode the frame to JPEG immediately so it doesn't go stale."""
        try:
            image_bytes = encode(
                frame,
                EncodeOptions(
                    format="JPEG",
                    resize_options=ResizeOptions(width=512, height=512, strategy="scale_aspect_fit"),
                ),
            )
            self._last_image_url = f"data:image/jpeg;base64,{base64.b64encode(image_bytes).decode()}"
            self._frame_count += 1
            if self._frame_count % 30 == 0:
                logger.info("Video frames captured: %d", self._frame_count)
        except Exception as e:
            logger.warning("Failed to encode frame: %s", e)

    async def on_user_turn_completed(self, turn_ctx, new_message):
        """Inject the latest camera frame into the chat context before LLM processes it."""
        logger.info("on_user_turn_completed called, has image: %s", self._last_image_url is not None)
        if self._last_image_url is not None:
            # Remove old images from ALL messages
            for msg in turn_ctx.items:
                if hasattr(msg, 'content') and isinstance(msg.content, list):
                    msg.content = [c for c in msg.content if not isinstance(c, ImageContent)]

            # Append image to the user's text in the new message
            image = ImageContent(image=self._last_image_url)
            text = new_message.text_content or ""
            new_message.content = [
                "[Camera frame attached] " + text,
                image,
            ]
            logger.info("Injected image into message, text: %s", text[:50])


async def entrypoint(ctx):
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    def _publish(data):
        asyncio.ensure_future(
            ctx.room.local_participant.publish_data(
                payload=json.dumps(data),
                reliable=True,
                topic="metrics",
            )
        )

    agent = VoiceAgent()

    session = AgentSession(
        min_endpointing_delay=0.3,
        vad=silero.VAD.load(),
        stt=openai.STT(
            base_url=STT_URL,
            api_key="none",
            model=STT_MODEL,
        ),
        llm=openai.LLM(
            base_url=LLM_URL,
            api_key=LLM_API_KEY,
            model=LLM_MODEL,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        ),
        tts=KokoroTTS(
            KokoroConfig(
                base_url=TTS_URL,
                model=TTS_MODEL,
                voice=TTS_VOICE,
                on_timestamps=lambda ts: _publish({
                    "type": "lipsync",
                    "words": [t["word"] for t in ts],
                    "wtimes": [int(t["start_time"] * 1000) for t in ts],
                    "wdurations": [int((t["end_time"] - t["start_time"]) * 1000) for t in ts],
                }),
            )
        ),
    )

    # Manually subscribe to video tracks (audio is handled by AUDIO_ONLY)
    @ctx.room.on("track_published")
    def on_track_published(publication, participant):
        if publication.kind == rtc.TrackKind.KIND_VIDEO:
            logger.info("Video track published by %s, subscribing...", participant.identity)
            publication.set_subscribed(True)

    @ctx.room.on("track_subscribed")
    def on_track_subscribed(track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_VIDEO:
            logger.info("Video track subscribed from %s", participant.identity)
            asyncio.ensure_future(process_video(track))

    async def process_video(track):
        """Continuously capture frames from the user's video track."""
        try:
            async for event in rtc.VideoStream(track):
                agent.set_frame(event.frame)
        except Exception as e:
            logger.warning("Video stream ended: %s", e)

    @session.on("conversation_item_added")
    def on_conversation_item(event):
        msg = event.item
        if not hasattr(msg, "metrics"):
            return
        m = msg.metrics
        if not m:
            return

        data = {"type": "pipeline"}

        if msg.role == "user":
            data["transcription_ms"] = round(m.get("transcription_delay", 0) * 1000)
            data["eot_ms"] = round(m.get("end_of_turn_delay", 0) * 1000)
        elif msg.role == "assistant":
            data["llm_ttft_ms"] = round(m.get("llm_node_ttft", 0) * 1000)
            data["tts_ttfb_ms"] = round(m.get("tts_node_ttfb", 0) * 1000)
            data["e2e_ms"] = round(m.get("e2e_latency", 0) * 1000)
        else:
            return

        logger.info("pipeline: %s", data)
        _publish(data)

    @session.on("metrics_collected")
    def on_metrics(event):
        try:
            m = event.metrics
            cls = type(m).__name__

            if cls == "STTMetrics":
                data = {
                    "type": "stt",
                    "duration_ms": round(m.duration * 1000),
                    "audio_duration_ms": round(m.audio_duration * 1000),
                    "streamed": m.streamed,
                }
                logger.info("stt: %s", data)
                _publish(data)

            elif cls == "TTSMetrics":
                data = {
                    "type": "tts",
                    "ttfb_ms": round(m.ttfb * 1000),
                    "duration_ms": round(m.duration * 1000),
                    "audio_duration_ms": round(m.audio_duration * 1000),
                    "characters": m.characters_count,
                    "cancelled": m.cancelled,
                }
                logger.info("tts: %s", data)
                _publish(data)

        except Exception as e:
            logger.warning("metrics error: %s", e)

    await session.start(agent=agent, room=ctx.room)

    await session.generate_reply(
        user_input="Hello!"
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
