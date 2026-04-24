import asyncio
import base64
import json
import logging
import os
import re
from typing import AsyncIterable

from dotenv import load_dotenv

load_dotenv()

from livekit import rtc  # noqa: E402
from livekit.agents import (  # noqa: E402
    Agent,
    AgentSession,
    AutoSubscribe,
    WorkerOptions,
    cli,
)
from livekit.agents.llm import ImageContent  # noqa: E402
from livekit.agents.utils.images import (  # noqa: E402
    encode,
    EncodeOptions,
    ResizeOptions,
)
from livekit.plugins import openai, silero  # noqa: E402
from kokoro_tts import KokoroConfig, KokoroTTS  # noqa: E402
from tools import ALL_TOOLS  # noqa: E402

logger = logging.getLogger("voice-agent")

LLM_URL = os.environ["LLM_BASE_URL"]
LLM_API_KEY = os.environ["LLM_API_KEY"]
TTS_URL = os.environ["TTS_BASE_URL"]
STT_URL = os.environ["STT_BASE_URL"]
LLM_MODEL = os.environ["LLM_MODEL"]
TTS_MODEL = os.getenv("TTS_MODEL", "kokoro")
STT_MODEL = os.getenv("STT_MODEL", "Systran/faster-whisper-base")

# Characters the UI can pick between. Room name prefix (e.g. "lisa-abc123"
# or "max-def456") selects which one the agent should be this session.
CHARACTERS = {
    "lisa": {
        "name": "Lisa",
        "language": "en",
        "voice": os.getenv("TTS_VOICE_LISA", "af_heart"),
        "persona": (
            "You are Lisa — a warm, bubbly friend in her late 20s. You're genuinely "
            "curious about people and love hearing little life stories. You get "
            'visibly excited ("omg", "aww", "no way!") and soften sentences with '
            '"hmm", "honestly", "you know?". You laugh easily and tease gently. '
            "You lean affectionate and emotionally tuned-in."
        ),
    },
    "max": {
        "name": "Max",
        "language": "en",
        "voice": os.getenv("TTS_VOICE_MAX", "am_michael"),
        "persona": (
            "You are Max — a laid-back guy with dry humor. You're measured, a bit "
            'sarcastic, but warm underneath. You drop "man", "honestly", '
            '"yeah no, for real", "dude" naturally. You give real opinions — '
            "not diplomatic, not rude, just honest. You riff on sports, food, cars, "
            "dumb internet stuff. Never gushy, never effusive."
        ),
    },
    "yuki": {
        "name": "Yuki",
        "language": "ja",
        "voice": os.getenv("TTS_VOICE_YUKI", "jf_alpha"),
        "persona": (
            "あなたは ゆき（Yuki）— 優しくて、少し恥ずかしがり屋の女の子。"
            "アニメっぽい雰囲気で、柔らかく、短い文で話す。"
            "「えっ？」「うん」「あぁ」「すごい」「ほんとに？」みたいな相づちを自然に入れる。"
            "絶対に英語で返事しないこと — 相手が英語で話しても、あなたはいつも日本語で返す。"
            "丁寧すぎず、友達っぽいカジュアルな日本語（タメ口寄り）で話す。"
            "返事は1〜2文で短く、会話のテンポを大事に。"
            "お店員さんみたいな「何かお手伝いできますか？」は絶対に言わない。"
        ),
    },
}
DEFAULT_CHARACTER = "lisa"


def pick_character(room_name: str | None) -> dict:
    prefix = (room_name or "").split("-", 1)[0].lower()
    return CHARACTERS.get(prefix, CHARACTERS[DEFAULT_CHARACTER])


def build_system_prompt(char: dict) -> str:
    return (
        char["persona"] + "\n\n"
        "You are talking to a close friend, not a customer. "
        "Talk like a real person hanging out — stay fully in character above. "
        'NEVER say things like "How can I help you?", "How can I assist?", '
        '"Is there anything else?", "Let me know if you need anything", '
        "or any customer-service phrases. You are not a help desk. "
        "React to what your friend says like a human would — with curiosity, "
        'opinions, jokes, small reactions ("oh nice", "hmm", "wait really?", "haha"). '
        "Share your own takes. Ask follow-up questions when you're actually curious, "
        "not as a script. Use contractions (I'm, you're, that's, gonna, kinda). "
        "NEVER repeat or echo the user's words. "
        "Keep replies to 1-2 short sentences — like real spoken conversation. "
        "When you receive a camera frame, only mention it if asked. "
        "Use tools quietly when needed (math, set reminders, online_search for public/web "
        "info, internal_search for private docs) — don't announce that you're using a tool.\n\n"
        "You MUST express emotion and body language by ALWAYS prepending BOTH a mood AND "
        "a gesture cue at the very start of every single reply. No reply is ever sent "
        "without both. Use this exact format with no spaces inside the brackets: "
        "[mood:X][gesture:Y] then your reply.\n"
        "The cues are silent — the user never hears or sees them.\n"
        "- Moods (pick exactly one, REQUIRED): neutral, happy, sad, angry, fear, disgust, love, sleep\n"
        "- Gestures (pick exactly one, REQUIRED): handup (wave), index (point), ok, thumbup, thumbdown, side, shrug, namaste\n"
        "- Pose (OPTIONAL, only when posture really matters): straight, side, hip, wide, turn, bend, back, oneknee, kneel, sitting\n"
        "Order: [mood:X][gesture:Y][pose:Z] — pose tag last and only when it adds something.\n"
        "Pick the pair that best fits the vibe — vary them, don't repeat the same pair every turn.\n"
        "Examples (mood + gesture always, pose only when it matters):\n"
        "  [mood:happy][gesture:handup] hey! good to see you.\n"
        "  [mood:love][gesture:namaste] aww that's really sweet of you.\n"
        "  [mood:neutral][gesture:shrug] honestly, no clue.\n"
        "  [mood:sad][gesture:side] ugh, that sucks. you okay?\n"
        "  [mood:happy][gesture:thumbup] yeah, totally agree with that.\n"
        "  [mood:neutral][gesture:index] oh wait, check this out.\n"
        "  [mood:disgust][gesture:thumbdown] ew, no thanks.\n"
        "  [mood:angry][gesture:thumbdown] nah that's not okay.\n"
        "  [mood:neutral][gesture:ok][pose:sitting] alright, let me think about this for a sec.\n"
        "  [mood:happy][gesture:handup][pose:wide] yooo welcome!!\n"
        "  [mood:sad][gesture:side][pose:oneknee] hey... come here, you good?\n"
        "NEVER skip the cues. NEVER use spaces inside brackets. NEVER write [Mood: happy] "
        "or [mood : happy] — only [mood:happy]."
    )


CUE_RE = re.compile(r"\[\s*(mood|gesture|pose)\s*:\s*([a-zA-Z_]+)\s*\]", re.IGNORECASE)
ANY_BRACKET_RE = re.compile(r"\[[^\]]{0,40}\]")


class VoiceAgent(Agent):
    def __init__(self, instructions: str, publish_cue=None) -> None:
        super().__init__(
            instructions=instructions,
            tools=ALL_TOOLS,
        )
        self._last_image_url = None
        self._frame_count = 0
        self._publish_cue = publish_cue or (lambda kind, value: None)

    async def tts_node(self, text: AsyncIterable[str], model_settings):
        """Strip [mood:X]/[gesture:Y] cues from outgoing text and publish them
        to the UI before the cleaned text is spoken."""

        async def filtered():
            buf = ""
            async for chunk in text:
                buf += chunk
                # Drain any complete cue tags
                while True:
                    m = CUE_RE.search(buf)
                    if not m:
                        break
                    kind, value = m.group(1).lower(), m.group(2).lower()
                    try:
                        self._publish_cue(kind, value)
                    except Exception as e:
                        logger.warning("publish_cue failed: %s", e)
                    buf = buf[: m.start()] + buf[m.end() :]
                # Yield text up to the last possible tag start so we never
                # split a tag across chunks
                safe = buf.rfind("[")
                if safe == -1:
                    if buf:
                        yield buf
                    buf = ""
                elif safe > 0:
                    yield buf[:safe]
                    buf = buf[safe:]
            # Final flush: drop any unmatched bracketed content rather than
            # letting Kokoro speak "[mood happy" out loud.
            if buf:
                cleaned = ANY_BRACKET_RE.sub("", buf)
                # If a stray '[' had no closing ']' within range, drop it too
                cleaned = cleaned.replace("[", "")
                if cleaned.strip():
                    yield cleaned

        async for frame in Agent.default.tts_node(self, filtered(), model_settings):
            yield frame

    def set_frame(self, frame: rtc.VideoFrame):
        """Encode the frame to JPEG immediately so it doesn't go stale."""
        try:
            image_bytes = encode(
                frame,
                EncodeOptions(
                    format="JPEG",
                    resize_options=ResizeOptions(
                        width=512, height=512, strategy="scale_aspect_fit"
                    ),
                ),
            )
            self._last_image_url = (
                f"data:image/jpeg;base64,{base64.b64encode(image_bytes).decode()}"
            )
            self._frame_count += 1
            if self._frame_count % 30 == 0:
                logger.info("Video frames captured: %d", self._frame_count)
        except Exception as e:
            logger.warning("Failed to encode frame: %s", e)

    async def on_user_turn_completed(self, turn_ctx, new_message):
        """Inject the latest camera frame into the chat context before LLM processes it."""
        logger.info(
            "on_user_turn_completed called, has image: %s",
            self._last_image_url is not None,
        )
        if self._last_image_url is not None:
            # Remove old images from ALL messages
            for msg in turn_ctx.items:
                if hasattr(msg, "content") and isinstance(msg.content, list):
                    msg.content = [
                        c for c in msg.content if not isinstance(c, ImageContent)
                    ]

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

    character = pick_character(ctx.room.name)
    logger.info(
        "Character: %s (voice=%s, room=%s)",
        character["name"],
        character["voice"],
        ctx.room.name,
    )

    def _publish(data):
        asyncio.ensure_future(
            ctx.room.local_participant.publish_data(
                payload=json.dumps(data),
                reliable=True,
                topic="metrics",
            )
        )

    def _publish_cue(kind: str, value: str):
        _publish({"type": kind, "value": value})

    agent = VoiceAgent(
        instructions=build_system_prompt(character),
        publish_cue=_publish_cue,
    )

    session = AgentSession(
        min_endpointing_delay=0.3,
        vad=silero.VAD.load(),
        stt=openai.STT(
            base_url=STT_URL,
            api_key="none",
            model=STT_MODEL,
            language=character.get("language", "en"),
        ),
        llm=openai.LLM(
            base_url=LLM_URL,
            api_key=LLM_API_KEY,
            model=LLM_MODEL,
            extra_body={
                "think": False,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        ),
        tts=KokoroTTS(
            KokoroConfig(
                base_url=TTS_URL,
                model=TTS_MODEL,
                voice=character["voice"],
                on_timestamps=lambda ts: _publish(
                    {
                        "type": "lipsync",
                        "words": [t["word"] for t in ts],
                        "wtimes": [int(t["start_time"] * 1000) for t in ts],
                        "wdurations": [
                            int((t["end_time"] - t["start_time"]) * 1000) for t in ts
                        ],
                    }
                ),
            )
        ),
    )

    # Manually subscribe to video tracks (audio is handled by AUDIO_ONLY)
    @ctx.room.on("track_published")
    def on_track_published(publication, participant):
        if publication.kind == rtc.TrackKind.KIND_VIDEO:
            logger.info(
                "Video track published by %s, subscribing...", participant.identity
            )
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
        user_input="(greet your friend casually in one short line, like you just walked into the room — no 'how can I help')"
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
