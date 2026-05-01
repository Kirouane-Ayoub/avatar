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
    APIConnectOptions,
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
from orpheus_tts import OrpheusConfig, OrpheusTTS  # noqa: E402
from tools import TOOL_CATALOG  # noqa: E402
from vision_watcher import VisionWatcher, VisionWatcherConfig  # noqa: E402
from voices import (  # noqa: E402
    backend_for,
    is_known_voice,
    stt_language_for,
)

logger = logging.getLogger("voice-agent")

LLM_URL = os.environ["LLM_BASE_URL"]
LLM_API_KEY = os.environ["LLM_API_KEY"]
TTS_URL = os.environ["TTS_BASE_URL"]  # Kokoro server
STT_URL = os.environ["STT_BASE_URL"]
LLM_MODEL = os.environ["LLM_MODEL"]
TTS_MODEL = os.getenv("TTS_MODEL", "kokoro")
STT_MODEL = os.getenv("STT_MODEL", "Systran/faster-whisper-base")

# Optional second TTS backend (llama.cpp + SNAC). Only required when a session
# picks an Orpheus voice; left unset, Orpheus voices simply won't synthesize.
ORPHEUS_URL = os.getenv("ORPHEUS_BASE_URL")
ORPHEUS_MODEL = os.getenv("ORPHEUS_MODEL", "orpheus")

# Optional ambient affect channel. When VLM_BASE_URL is set, a background
# watcher samples camera frames between turns and emits subtle mood cues
# so the avatar reacts to the user's face without waiting for them to speak.
VLM_URL = os.getenv("VLM_BASE_URL")
VLM_MODEL = os.getenv("VLM_MODEL", "mlx-community/Qwen3-VL-2B-Instruct-4bit")

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


# Inline vocal emotion tags supported by Orpheus-FastAPI. Synthesized as
# actual sounds (not spoken words). Only added to the system prompt when the
# session uses an Orpheus voice — Kokoro would speak them literally.
ORPHEUS_EMOTION_TAGS = (
    "laugh",
    "sigh",
    "chuckle",
    "cough",
    "sniffle",
    "groan",
    "yawn",
    "gasp",
)


def _orpheus_emotion_block() -> str:
    tags = ", ".join(f"<{t}>" for t in ORPHEUS_EMOTION_TAGS)
    return (
        "\n\n"
        "You can also weave inline VOCAL EMOTION TAGS into your reply — these "
        "render as actual sounds, not spoken words. Use them sparingly (at "
        "most one per reply, only when it really fits the moment), never "
        "back-to-back, and never in place of the [mood]/[gesture] cues.\n"
        f"Available tags: {tags}.\n"
        'Example: "well, that\'s actually pretty interesting <laugh> i hadn\'t '
        'thought of it that way."'
    )


# Voice TTS engines can only pronounce their own language. If the LLM replies
# in a different language than the voice, output sounds garbled — so we lock
# the reply language to whatever language the voice belongs to.
_LANG_NAMES = {
    "en": "English",
    "ja": "Japanese (日本語)",
    "fr": "French (français)",
    "de": "German (Deutsch)",
    "es": "Spanish (español)",
    "it": "Italian (italiano)",
    "ko": "Korean (한국어)",
    "hi": "Hindi (हिन्दी)",
    "zh": "Mandarin Chinese (中文)",
    "pt": "Portuguese (português)",
}


def _language_block(language: str) -> str:
    name = _LANG_NAMES.get(language)
    if not name:
        return ""
    return (
        "\n\n"
        f"LANGUAGE LOCK: You speak ONLY in {name}. Reply in {name} no matter "
        "what language the user speaks — even if they switch mid-conversation, "
        f"you do NOT switch. The voice you use can only pronounce {name} "
        "correctly; replying in any other language would sound garbled. "
        f"If the user speaks another language, gently respond in {name} anyway."
    )


def build_system_prompt(
    name: str,
    persona: str,
    backend: str = "kokoro",
    language: str = "en",
) -> str:
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
        + (_orpheus_emotion_block() if backend == "orpheus" else "")
        + _language_block(language)
    )


CUE_RE = re.compile(r"\[\s*(mood|gesture|pose)\s*:\s*([a-zA-Z_]+)\s*\]", re.IGNORECASE)
ANY_BRACKET_RE = re.compile(r"\[[^\]]{0,40}\]")


class PatientLLM(openai.LLM):
    """openai.LLM with a wider per-call APIConnectOptions.timeout.

    The 27B VL model with a freshly injected camera frame routinely takes
    5-15 s TTFT on M4 Pro (vision encoding + autoregressive generation).
    The DEFAULT APIConnectOptions.timeout is 10 s, so without overriding
    here, livekit-agents fires the per-attempt timeout BEFORE the model
    starts streaming, then retries — queueing more requests on the serial
    mlx-vlm server and spiraling. Plain `timeout=` kwarg on openai.LLM
    only configures the openai-python httpx client (a different layer)
    and does NOT touch the livekit retry timeout. So we override
    conn_options on every chat() call.
    """

    _PATIENT_CONN = APIConnectOptions(
        max_retry=3, retry_interval=2.0, timeout=60.0
    )

    def chat(self, *args, **kwargs):
        kwargs.setdefault("conn_options", self._PATIENT_CONN)
        return super().chat(*args, **kwargs)


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

    def clear_frame(self):
        """Drop the cached frame. Called when the video track ends so the
        VisionWatcher (and the chat-time image injector) don't keep acting
        on a stale snapshot of the user from before they killed the camera.
        """
        self._last_image_url = None

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
        # Diagnostic: print the exact text about to be sent to the LLM so we
        # can identify phantom turns (Whisper hallucinations, echo, etc.).
        raw_text = (new_message.text_content or "").strip()
        logger.info(
            "USER_TURN -> LLM | text=%r | len=%d | has_image=%s",
            raw_text,
            len(raw_text),
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
    if is_known_voice(requested_voice):
        voice = requested_voice
        language = stt_language_for(voice, fallback="en")
    else:
        language = cfg.get("language") if cfg.get("language") in {"en", "ja"} else "en"
        voice = pick_voice(language, body)

    backend = backend_for(voice)

    logger.info(
        "Session: name=%s language=%s voice=%s backend=%s tools=%s",
        name,
        language,
        voice,
        backend,
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
        instructions=build_system_prompt(
            name, persona, backend=backend, language=language
        ),
        tools=tools,
        publish_cue=_publish_cue,
    )

    def _on_kokoro_timestamps(ts):
        _publish(
            {
                "type": "lipsync",
                "words": [t["word"] for t in ts],
                "wtimes": [int(t["start_time"] * 1000) for t in ts],
                "wdurations": [
                    int((t["end_time"] - t["start_time"]) * 1000) for t in ts
                ],
            }
        )

    if backend == "orpheus":
        if not ORPHEUS_URL:
            raise RuntimeError(
                f"Voice {voice!r} requires the Orpheus backend, but "
                "ORPHEUS_BASE_URL is not set."
            )
        tts_engine = OrpheusTTS(
            OrpheusConfig(
                base_url=ORPHEUS_URL,
                model=ORPHEUS_MODEL,
                voice=voice,
            )
        )
    else:
        tts_engine = KokoroTTS(
            KokoroConfig(
                base_url=TTS_URL,
                model=TTS_MODEL,
                voice=voice,
                on_timestamps=_on_kokoro_timestamps,
            )
        )

    session = AgentSession(
        # Disabled: image injection in on_user_turn_completed mutates the
        # chat context AFTER preemptive generation has already kicked off,
        # so every preemptive call is invalidated and re-issued — wasted
        # round-trips that pile up on the slow 27B VL model and push us
        # past the LLM client timeout. Without preemption, one call per
        # turn, no warning spam ("preemptive generation enabled but chat
        # context or tools have changed after on_user_turn_completed").
        preemptive_generation=False,
        turn_handling={
            "endpointing": {"min_delay": 0.3},
            "interruption": {
                # Echo / room noise typically transcribes to <1 s bursts and
                # 0–1 words. Require sustained speech AND ≥2 words before the
                # avatar yields, so a stray "yeah" leaking from the speakers
                # doesn't cut it off mid-sentence.
                "min_duration": 1.0,
                "min_words": 2,
                # If we DO interrupt and it turns out to be a false alarm
                # (e.g. user transcript ends up empty), let the avatar resume.
                "resume_false_interruption": True,
            },
        },
        # Tightened Silero VAD: defaults (activation_threshold=0.5,
        # min_speech_duration=0.05) trigger on mic-floor noise / brief
        # bumps, which then get fed to Whisper and fitted to high-prior
        # phrases. Raising both gates the entry point.
        vad=silero.VAD.load(
            activation_threshold=0.65,
            min_speech_duration=0.25,
            min_silence_duration=0.7,
        ),
        stt=openai.STT(
            base_url=STT_URL,
            api_key="none",
            model=STT_MODEL,
            language=language,
        ),
        llm=PatientLLM(
            base_url=LLM_URL,
            api_key=LLM_API_KEY,
            model=LLM_MODEL,
            extra_body={
                "think": False,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        ),
        tts=tts_engine,
    )

    # Typed user input — UI publishes JSON {"text": "..."} on topic "user_text".
    # We inject it into the LLM via session.generate_reply, which runs the full
    # LLM → TTS pipeline so the avatar still speaks the answer.
    @ctx.room.on("data_received")
    def on_data_received(packet):
        if getattr(packet, "topic", None) != "user_text":
            return
        try:
            payload = json.loads(packet.data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            logger.warning("Bad user_text payload: %s", e)
            return
        text = (payload.get("text") or "").strip() if isinstance(payload, dict) else ""
        if not text:
            return
        logger.info("USER_TEXT -> LLM | text=%r", text)
        asyncio.ensure_future(session.generate_reply(user_input=text))

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
        finally:
            # Stream ends when the user mutes / unpublishes the camera,
            # disconnects, or the track is unsubscribed for any reason.
            # Drop the cached frame so the watcher and image injector
            # don't act on a stale snapshot.
            agent.clear_frame()
            logger.info("Video stream cleared (camera off / track ended)")

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

    # Ambient affect watcher: sample frames between turns and publish mood
    # cues from a small VLM. Only runs when VLM_BASE_URL is configured;
    # otherwise the avatar's only mood source remains the chat LLM's reply
    # cues. Idle-gated via AgentSession state so it never preempts the LLM.
    watcher: VisionWatcher | None = None
    if VLM_URL:
        # Cache last seen state pair so we only log when it changes — without
        # this we'd spam one log line per 1 s tick when the watcher is gated.
        _state_cache = {"u": None, "a": None}

        # AgentSession state transitions discovered the hard way:
        #   user_state:  "listening" | "speaking" | "away"
        #     ("away" fires after a stretch of mic silence — by far the most
        #      common state during long ambient observation, NOT a blocker)
        #   agent_state: "initializing" | "listening" | "thinking" | "speaking"
        # The watcher should fire whenever the user isn't actively talking
        # AND the agent isn't generating/speaking. Anything else (away,
        # initializing, ...) is fine — treat as idle. Earlier the gate was
        # `both == "listening"` which silently froze the watcher the moment
        # `user_state` flipped to "away" (within ~30 s of silence).
        _USER_ACTIVE = {"speaking"}
        _AGENT_BUSY = {"thinking", "speaking"}

        def _is_idle() -> bool:
            try:
                u_str = str(getattr(session, "user_state", "listening"))
                a_str = str(getattr(session, "agent_state", "listening"))
                idle = u_str not in _USER_ACTIVE and a_str not in _AGENT_BUSY
                if (u_str, a_str) != (_state_cache["u"], _state_cache["a"]):
                    logger.info(
                        "session state: user=%s agent=%s -> idle=%s",
                        u_str, a_str, idle,
                    )
                    _state_cache["u"] = u_str
                    _state_cache["a"] = a_str
                return idle
            except Exception as e:
                logger.warning("_is_idle exception: %s", e)
                return False

        watcher = VisionWatcher(
            config=VisionWatcherConfig(base_url=VLM_URL, model=VLM_MODEL),
            get_frame_data_url=lambda: agent._last_image_url,
            is_idle=_is_idle,
            publish_cue=_publish_cue,
        )
        await watcher.start()

        async def _shutdown_watcher():
            await watcher.stop()

        ctx.add_shutdown_callback(_shutdown_watcher)

    await session.generate_reply(
        user_input="(greet your friend casually in one short line, like you just walked into the room — no 'how can I help')"
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
