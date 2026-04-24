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
from cues import GESTURES, MOODS, POSES  # noqa: E402
from kokoro_tts import KokoroConfig, KokoroTTS  # noqa: E402
from tools import TOOL_CATALOG  # noqa: E402
from voices import KOKORO_VOICES, stt_language_for  # noqa: E402

logger = logging.getLogger("voice-agent")

LLM_URL = os.environ["LLM_BASE_URL"]
LLM_API_KEY = os.environ["LLM_API_KEY"]
TTS_URL = os.environ["TTS_BASE_URL"]
STT_URL = os.environ["STT_BASE_URL"]
LLM_MODEL = os.environ["LLM_MODEL"]
TTS_MODEL = os.getenv("TTS_MODEL", "kokoro")
STT_MODEL = os.getenv("STT_MODEL", "Systran/faster-whisper-base")

DEFAULT_PERSONA = "You are a warm, friendly companion. Chat like a close friend."
DEFAULT_NAME = "Assistant"

# Voice defaults per language + body type. Can be overridden per-session via
# metadata, but UIs currently don't expose voice — we derive a sensible one.
VOICE_DEFAULTS = {
    ("en", "F"): os.getenv("TTS_VOICE_FEMALE_EN", "af_heart"),
    ("en", "M"): os.getenv("TTS_VOICE_MALE_EN", "am_michael"),
    ("ja", "F"): os.getenv("TTS_VOICE_FEMALE_JA", "jf_alpha"),
    ("ja", "M"): os.getenv("TTS_VOICE_MALE_JA", "jm_kumo"),
}


def pick_voice(language: str, body: str) -> str:
    return VOICE_DEFAULTS.get(
        (language, body),
        VOICE_DEFAULTS[("en", "F")],
    )


def parse_metadata(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        logger.warning("Failed to parse participant metadata: %r", raw)
        return {}


# Hint annotations for gesture names that aren't self-explanatory. Kept here,
# not in cues.py, because they're prompt-engineering artifacts — the canonical
# vocabulary is the identifier, the hint is just a teaching aid for the LLM.
_GESTURE_HINTS = {"handup": "wave", "index": "point"}


def _format_gestures() -> str:
    return ", ".join(
        f"{g} ({_GESTURE_HINTS[g]})" if g in _GESTURE_HINTS else g
        for g in GESTURES
    )


def build_system_prompt(name: str, persona: str) -> str:
    return (
        f"You are {name}.\n\n"
        f"{persona}\n\n"
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
        f"- Moods (pick exactly one, REQUIRED): {', '.join(MOODS)}\n"
        f"- Gestures (pick exactly one, REQUIRED): {_format_gestures()}\n"
        f"- Pose (OPTIONAL, only when posture really matters): {', '.join(POSES)}\n"
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
    def __init__(self, instructions: str, tools: list, publish_cue=None) -> None:
        super().__init__(
            instructions=instructions,
            tools=tools,
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

    # Wait for the user to join so we can read their session config from
    # participant metadata (set by the token server from the setup wizard).
    participant = await ctx.wait_for_participant()
    cfg = parse_metadata(participant.metadata)

    name = (cfg.get("name") or DEFAULT_NAME).strip() or DEFAULT_NAME
    persona = (cfg.get("persona") or DEFAULT_PERSONA).strip() or DEFAULT_PERSONA
    body = cfg.get("body") if cfg.get("body") in {"F", "M"} else "F"
    requested_tool_ids = cfg.get("tools") or []
    tools = [TOOL_CATALOG[t]["tool"] for t in requested_tool_ids if t in TOOL_CATALOG]

    # Explicit voice from the wizard wins; otherwise fall back to a body-based
    # default for the avatar's declared language.
    requested_voice = cfg.get("voice")
    if requested_voice in KOKORO_VOICES:
        voice = requested_voice
        language = stt_language_for(voice, fallback="en")
    else:
        language = cfg.get("language") if cfg.get("language") in {"en", "ja"} else "en"
        voice = pick_voice(language, body)

    logger.info(
        "Session: name=%s language=%s voice=%s tools=%s",
        name,
        language,
        voice,
        [t.__name__ for t in tools],
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
        instructions=build_system_prompt(name, persona),
        tools=tools,
        publish_cue=_publish_cue,
    )

    session = AgentSession(
        min_endpointing_delay=0.3,
        vad=silero.VAD.load(),
        stt=openai.STT(
            base_url=STT_URL,
            api_key="none",
            model=STT_MODEL,
            language=language,
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
                voice=voice,
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
