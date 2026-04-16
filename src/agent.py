"""LiveKit voice agent: fully local speech-to-speech using Qwen + Kokoro TTS + Faster Whisper."""

import asyncio
import json
import logging
import os

from dotenv import load_dotenv

load_dotenv()

from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    WorkerOptions,
    cli,
)
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
Your name is Lisa. You are a friendly voice assistant. \
NEVER repeat or echo the user's words. \
Always respond with your own original answer. \
Keep replies to 1-2 short sentences. Be helpful and direct. \
You have tools available — use them when the user asks for the time, \
weather, math, dice rolls, coin flips, or random numbers.\
"""


class VoiceAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=SYSTEM_PROMPT,
            tools=ALL_TOOLS,
        )


async def entrypoint(ctx):
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    session = AgentSession(
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
            )
        ),
    )

    def _publish(data):
        asyncio.ensure_future(
            ctx.room.local_participant.publish_data(
                payload=json.dumps(data),
                reliable=True,
                topic="metrics",
            )
        )

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

    await session.start(agent=VoiceAgent(), room=ctx.room)

    await session.generate_reply(
        user_input="Hello!"
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
