"""LiveKit voice agent: fully local speech-to-speech using Qwen + Kokoro TTS + Faster Whisper."""

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

LLM_URL = os.environ["LLM_BASE_URL"]
LLM_API_KEY = os.environ["LLM_API_KEY"]
TTS_URL = os.environ["TTS_BASE_URL"]
STT_URL = os.environ["STT_BASE_URL"]
LLM_MODEL = os.environ["LLM_MODEL"]
TTS_MODEL = os.getenv("TTS_MODEL", "kokoro")
TTS_VOICE = os.getenv("TTS_VOICE", "af_heart")
STT_MODEL = os.getenv("STT_MODEL", "Systran/faster-whisper-base")

SYSTEM_PROMPT = """\
You are a friendly, helpful voice assistant. Use very short sentences — \
no more than 5-8 words each. Reply in 1-2 sentences max. Be direct and punchy. \
This is a real-time voice conversation, so keep it snappy.\
"""


class VoiceAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=SYSTEM_PROMPT,
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
        ),
        tts=KokoroTTS(
            KokoroConfig(
                base_url=TTS_URL,
                model=TTS_MODEL,
                voice=TTS_VOICE,
            )
        ),
    )

    await session.start(agent=VoiceAgent(), room=ctx.room)

    await session.generate_reply(
        user_input="Hello!"
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
