"""LiveKit voice-agent entrypoint.

Thin glue. Heavy lifting lives in dedicated packages under src/:
  - config       : Config dataclass — single source of truth for env vars
  - cues         : shared mood/gesture/pose vocabulary
  - tools        : @function_tool catalogue
  - auth/        : signup/login/JWT, DB pool + CRUD, SessionIdentity
  - llm/         : PatientLLM client, system_prompt assembly
  - tts/         : Kokoro + Orpheus engines, voice catalog + routing
  - vision/      : ambient affect VLM watcher
  - memory/      : MemoryProvider Protocol + Mem0Provider

This file owns:
  - VoiceAgent class (Agent subclass with frame buffer + cue stripping)
  - entrypoint() coroutine (LiveKit job hookup)
"""

import asyncio
import base64
import json
import logging
import re
import time
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

from auth import SessionIdentity, init_db  # noqa: E402
from config import Config  # noqa: E402
from llm import build_chat_llm, build_system_prompt  # noqa: E402
from memory import build_provider  # noqa: E402
from tools import TOOL_CATALOG  # noqa: E402
from tts import (  # noqa: E402
    KokoroConfig,
    KokoroTTS,
    OrpheusConfig,
    OrpheusTTS,
    backend_for,
    is_known_voice,
    stt_language_for,
)
from vision import VisionWatcher, VisionWatcherConfig  # noqa: E402

logger = logging.getLogger("voice-agent")


# Cue-tag regex used both by VoiceAgent.tts_node (live-stripping cues
# before TTS speaks them) and by the conversation_item_added handler
# (stripping cues from assistant text before it goes into memory).
CUE_RE = re.compile(r"\[\s*(mood|gesture|pose)\s*:\s*([a-zA-Z_]+)\s*\]", re.IGNORECASE)
ANY_BRACKET_RE = re.compile(r"\[[^\]]{0,40}\]")


class VoiceAgent(Agent):
    """Wraps the LiveKit Agent with two extras:
    1. A frame buffer (set_frame/clear_frame/_last_image_url) the
       vision watcher reads from, also injected into the LLM at
       on_user_turn_completed.
    2. A cue-stripping tts_node that pulls [mood:X][gesture:Y]
       tags out of the LLM stream and publishes them as DataChannel
       events instead of letting TTS speak them aloud.
    """

    def __init__(self, instructions: str, tools: list, publish_cue=None) -> None:
        super().__init__(instructions=instructions, tools=tools)
        self._last_image_url = None
        self._frame_count = 0
        self._publish_cue = publish_cue or (lambda kind, value: None)

    async def tts_node(self, text: AsyncIterable[str], model_settings):
        """Strip [mood:X]/[gesture:Y]/[pose:Z] cues from outgoing text
        and publish them via DataChannel before the cleaned text is
        spoken. Without this, Kokoro/Orpheus would speak the brackets."""

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
                # Yield text up to the last possible tag start so we
                # never split a tag across chunks.
                safe = buf.rfind("[")
                if safe == -1:
                    if buf:
                        yield buf
                    buf = ""
                elif safe > 0:
                    yield buf[:safe]
                    buf = buf[safe:]
            # Final flush: drop any unmatched bracketed content rather
            # than letting TTS speak "[mood happy" out loud.
            if buf:
                cleaned = ANY_BRACKET_RE.sub("", buf).replace("[", "")
                if cleaned.strip():
                    yield cleaned

        async for frame in Agent.default.tts_node(self, filtered(), model_settings):
            yield frame

    def clear_frame(self):
        """Drop the cached frame. Called when the video track ends so
        the VisionWatcher (and the chat-time image injector) don't keep
        acting on a stale snapshot of the user from before camera-off."""
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
        """Inject the latest camera frame into the chat context before
        the LLM processes the turn. No-op when camera is off."""
        raw_text = (new_message.text_content or "").strip()
        logger.info(
            "USER_TURN -> LLM | text=%r | len=%d | has_image=%s",
            raw_text,
            len(raw_text),
            self._last_image_url is not None,
        )
        if self._last_image_url is None:
            return

        # Remove old images from ALL prior messages — we only ever want
        # the most recent frame in context.
        for msg in turn_ctx.items:
            if hasattr(msg, "content") and isinstance(msg.content, list):
                msg.content = [
                    c for c in msg.content if not isinstance(c, ImageContent)
                ]

        image = ImageContent(image=self._last_image_url)
        text = new_message.text_content or ""
        new_message.content = ["[Camera frame attached] " + text, image]
        logger.info("Injected image into message, text: %s", text[:50])


async def entrypoint(ctx):
    """LiveKit job entrypoint — one invocation per session."""
    config = Config.from_env()
    # init_db is idempotent — safe to call once per session even though
    # the token server already initialized the same singleton when this
    # container started. The pool is shared.
    db = init_db(config)
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Wait for the user to join so we can read their session config.
    # participant.identity is the avatar_id (token server set it after
    # validating ownership). SessionIdentity does the DB lookup +
    # wizard-fallback merging.
    participant = await ctx.wait_for_participant()
    identity = SessionIdentity.from_participant(participant, db=db)

    # Voice resolution: explicit voice from the wizard wins; otherwise
    # body-based default for the language. stt_language_for derives the
    # STT language from the chosen voice (voice always wins over
    # explicit language).
    if is_known_voice(identity.voice):
        voice = identity.voice
        language = stt_language_for(voice, fallback="en")
    else:
        language = identity.language or "en"
        voice = config.pick_voice(language, identity.body)
    backend = backend_for(voice)

    # Tool catalog filter — keep only tools the wizard requested AND
    # that exist in the catalog. tool_ids mirrors the resolved set so the
    # system prompt can mention exactly the tools that are actually wired
    # (otherwise the LLM hallucinates calls to tools it doesn't have).
    tool_ids = [
        t for t in identity.requested_tool_ids if t in TOOL_CATALOG
    ]
    tools = [TOOL_CATALOG[t]["tool"] for t in tool_ids]

    # Persistent memory: NullProvider when memory is disabled in config.
    # Recall happens once at session start; the result is folded into
    # the system prompt so the avatar "knows" prior facts before its first
    # reply.
    memory = build_provider(config)
    _recall_t0 = time.monotonic()
    recalled = await memory.recall(identity.id)
    _recall_ms = round((time.monotonic() - _recall_t0) * 1000)
    if recalled:
        logger.info("recalled %d chars for user=%s", len(recalled), identity.id)

    # Short-term cross-session recall: pull the last raw turns from the
    # transcripts table so the avatar can pick up where the prior session
    # left off ("we were just talking about X"). This is verbatim history
    # — different from Mem0's distilled facts above. Best-effort: a DB
    # hiccup must NOT block session start, so swallow any exception.
    recent_turns: list = []
    try:
        recent_turns = await asyncio.to_thread(
            db.recent_transcripts, identity.id, 20
        )
        logger.info(
            "recalled %d recent turns for avatar=%s",
            len(recent_turns), identity.id,
        )
    except Exception:
        logger.exception(
            "recent_transcripts failed for avatar=%s — continuing without it",
            identity.id,
        )

    logger.info(
        "Session: name=%s language=%s voice=%s backend=%s tools=%s "
        "user_id=%s memory=%s",
        identity.name,
        language,
        voice,
        backend,
        [t.__name__ for t in tools],
        identity.id,
        type(memory).__name__,
    )

    # ── DataChannel publishing helpers ──────────────────────────────────
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

    # Surface session-start recall latency to the metrics pill.
    _publish({"type": "memory", "op": "read", "ms": _recall_ms})

    # ── Long-term memory write batching ─────────────────────────────────
    # Per-turn fact extraction was firing 2 LLM calls per exchange (one
    # for user, one for assistant) even when most turns carry no new
    # facts. Buffer USER messages only and flush every N turns. Mem0
    # extracts once over the whole batch — fewer LLM calls, and the
    # extractor gets to reason over multiple turns at once for richer
    # facts ("user has been talking about Madrid all session" instead of
    # ten micro-facts each turn).
    USER_TURN_BATCH_SIZE = 10
    user_turn_buffer: list[dict] = []

    async def _flush_memory_batch(reason: str) -> None:
        """Send any buffered user turns to memory in one extraction
        call. Idempotent — if buffer is empty, no-op. Reason string
        is just for the log so we can tell "batch full" from "session
        end" flushes apart."""
        if not user_turn_buffer:
            return
        batch = list(user_turn_buffer)
        user_turn_buffer.clear()
        logger.info("memory.flush(%s): %d user turns", reason, len(batch))
        t0 = time.monotonic()
        await memory.record_batch(identity.id, batch)
        _publish(
            {
                "type": "memory",
                "op": "write",
                "ms": round((time.monotonic() - t0) * 1000),
            }
        )

    # ── Agent + TTS engine ──────────────────────────────────────────────
    agent = VoiceAgent(
        instructions=build_system_prompt(
            identity,
            backend=backend,
            language=language,
            recalled_memory=recalled,
            recent_turns=recent_turns,
            tool_ids=tool_ids,
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
        if not config.orpheus_base_url:
            raise RuntimeError(
                f"Voice {voice!r} requires the Orpheus backend, but "
                "ORPHEUS_BASE_URL is not set."
            )
        tts_engine = OrpheusTTS(
            OrpheusConfig(
                base_url=config.orpheus_base_url,
                model=config.orpheus_model,
                voice=voice,
            )
        )
    else:
        tts_engine = KokoroTTS(
            KokoroConfig(
                base_url=config.tts_base_url,
                model=config.tts_model,
                voice=voice,
                on_timestamps=_on_kokoro_timestamps,
            )
        )

    # ── Session ─────────────────────────────────────────────────────────
    session = AgentSession(
        # See agent docstring history for why preemption is off:
        # image injection in on_user_turn_completed mutates chat context
        # AFTER preemptive generation kicks off, invalidating it. Result:
        # 2 LLM calls per turn, both serialized against the slow chat
        # model. preemption=False = one call per turn, no warning spam.
        preemptive_generation=False,
        turn_handling={
            "endpointing": {"min_delay": 0.3},
            "interruption": {
                # Echo / room noise transcribes to <1 s bursts, 0–1 words.
                # Require sustained speech AND ≥2 words before yielding,
                # so a stray "yeah" leaking from speakers doesn't cut
                # the avatar mid-sentence. Resume on false-positive.
                "min_duration": 1.0,
                "min_words": 2,
                "resume_false_interruption": True,
            },
        },
        # Tightened Silero VAD: defaults trigger on mic-floor noise,
        # which feeds Whisper and gets fitted to high-prior phrases.
        vad=silero.VAD.load(
            activation_threshold=0.65,
            min_speech_duration=0.25,
            min_silence_duration=0.7,
        ),
        stt=openai.STT(
            base_url=config.stt_base_url,
            api_key="none",
            model=config.stt_model,
            language=language,
        ),
        llm=build_chat_llm(config),
        tts=tts_engine,
    )

    # ── Event handlers ──────────────────────────────────────────────────
    @ctx.room.on("data_received")
    def on_data_received(packet):
        """Typed user input — UI publishes JSON {"text": "..."} on
        topic 'user_text'. Inject via session.generate_reply so the
        full LLM → TTS pipeline runs and the avatar speaks the reply."""
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

    @ctx.room.on("track_published")
    def on_track_published(publication, p):
        if publication.kind == rtc.TrackKind.KIND_VIDEO:
            logger.info("Video track published by %s, subscribing...", p.identity)
            publication.set_subscribed(True)

    @ctx.room.on("track_subscribed")
    def on_track_subscribed(track, publication, p):
        if track.kind == rtc.TrackKind.KIND_VIDEO:
            logger.info("Video track subscribed from %s", p.identity)
            asyncio.ensure_future(_process_video(track))

    async def _process_video(track):
        """Continuously capture frames from the user's video track."""
        try:
            async for event in rtc.VideoStream(track):
                agent.set_frame(event.frame)
        except Exception as e:
            logger.warning("Video stream ended: %s", e)
        finally:
            # Stream ends on camera off / mute / disconnect / unsubscribe.
            # Drop the cached frame so the watcher and image injector
            # don't act on a stale snapshot.
            agent.clear_frame()
            logger.info("Video stream cleared (camera off / track ended)")

    @session.on("conversation_item_added")
    def on_conversation_item(event):
        msg = event.item

        # `conversation_item_added` fires for several event types — chat
        # messages (have .role + .text_content), AgentHandoff events
        # (don't), and possibly future event types. Guard against any
        # event that doesn't look like a chat message before reading
        # role/text_content. Without this, AgentHandoff trips an
        # AttributeError on every handoff and spams the log.
        if not hasattr(msg, "role"):
            return

        # Pull text once for both transcript-write and memory-buffer paths.
        text = (msg.text_content or "").strip()

        # Short-term memory: persist BOTH sides verbatim so the next
        # session can recall them. Strip cue tags from assistant text so
        # we don't store "[mood:happy][gesture:handup] hey!" — the user
        # never saw the brackets, the prompt shouldn't either. Off the
        # hot path via to_thread so the DB write never stalls the voice
        # loop. Errors are swallowed inside record_transcript's caller.
        if text and msg.role in ("user", "assistant"):
            stored_text = (
                CUE_RE.sub("", text).strip() if msg.role == "assistant" else text
            )
            if stored_text:

                async def _persist(role=msg.role, body=stored_text):
                    try:
                        await asyncio.to_thread(
                            db.record_transcript, identity.id, role, body
                        )
                    except Exception:
                        logger.exception(
                            "record_transcript failed avatar=%s role=%s",
                            identity.id, role,
                        )

                asyncio.ensure_future(_persist())

        # Long-term memory: USER messages only (assistant turns rarely
        # carry new facts about the user). Buffer per-session and flush
        # every USER_TURN_BATCH_SIZE turns + at session end. Drops the
        # extraction-LLM call rate by ~10× vs per-turn.
        if msg.role == "user" and text:
            user_turn_buffer.append({"role": "user", "content": text})
            if len(user_turn_buffer) >= USER_TURN_BATCH_SIZE:
                asyncio.ensure_future(_flush_memory_batch("batch full"))

        # Pipeline metrics → UI pill
        if not hasattr(msg, "metrics") or not msg.metrics:
            return
        m = msg.metrics
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
        # STTMetrics + TTSMetrics — deprecated by livekit but still fires.
        # We keep them for the per-component breakdown in the UI pill.
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

    # ── Ambient affect watcher ──────────────────────────────────────────
    # Optional: only runs when VLM is configured. Reads frames from
    # agent._last_image_url, idle-gates against AgentSession state.
    if config.vlm_base_url:
        await _start_vision_watcher(config, session, agent, _publish_cue, ctx)

    # Flush any unflushed user-turn batch when the session ends, so we
    # don't lose the tail of the conversation if the user disconnects
    # mid-batch (most sessions probably end with <10 user turns and
    # would otherwise lose ALL their facts to the bin).
    async def _shutdown_flush_memory():
        await _flush_memory_batch("session end")

    ctx.add_shutdown_callback(_shutdown_flush_memory)

    await session.generate_reply(
        user_input=(
            "(greet your friend casually in one short line, like you "
            "just walked into the room — no 'how can I help')"
        )
    )


async def _start_vision_watcher(config, session, agent, publish_cue, ctx):
    """Spin up the ambient affect watcher and register its shutdown.

    Lifted out of entrypoint() because the idle-gate state-tracking is
    chunky and unrelated to the rest of the session setup.
    """
    # Cache last seen state pair so we only log when it changes.
    state_cache = {"u": None, "a": None}

    # AgentSession state transitions discovered the hard way:
    #   user_state:  "listening" | "speaking" | "away"
    #     ("away" fires after a stretch of mic silence — common, NOT a blocker)
    #   agent_state: "initializing" | "listening" | "thinking" | "speaking"
    # The watcher fires whenever the user isn't actively talking AND the
    # agent isn't generating/speaking. Anything else is fine.
    USER_ACTIVE = {"speaking"}
    AGENT_BUSY = {"thinking", "speaking"}

    def _is_idle() -> bool:
        try:
            u = str(getattr(session, "user_state", "listening"))
            a = str(getattr(session, "agent_state", "listening"))
            idle = u not in USER_ACTIVE and a not in AGENT_BUSY
            if (u, a) != (state_cache["u"], state_cache["a"]):
                logger.info(
                    "session state: user=%s agent=%s -> idle=%s",
                    u,
                    a,
                    idle,
                )
                state_cache["u"] = u
                state_cache["a"] = a
            return idle
        except Exception as e:
            logger.warning("_is_idle exception: %s", e)
            return False

    watcher = VisionWatcher(
        config=VisionWatcherConfig(
            base_url=config.vlm_base_url,
            model=config.vlm_model,
        ),
        get_frame_data_url=lambda: agent._last_image_url,
        is_idle=_is_idle,
        publish_cue=publish_cue,
    )
    await watcher.start()

    async def _shutdown_watcher():
        await watcher.stop()

    ctx.add_shutdown_callback(_shutdown_watcher)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
