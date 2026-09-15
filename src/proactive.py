"""Proactive utterance manager — the avatar decides when to break silence.

Real people don't sit in silent stalemates; they fill the pause with a
casual check-in or react to something they see. This module gives the
avatar that instinct, gated heavily so it never feels intrusive.

Two triggers, both eligible only when proactive=True on the avatar row:

  1. Sustained silence: USER_STATE has been != "speaking" for at least
     `silence_threshold_s` AND AGENT_STATE is "listening" (no in-flight
     turn). Fires a soft check-in.

  2. Camera mood: VisionWatcher has held a non-neutral mood for at least
     `mood_hold_s`, AND user is idle for at least 5 s. Fires a mood-
     aware reaction ("you good?" / "you seem amped").

Discipline (every trigger respects all four):

  - Cooldown: `cooldown_s` since the last check-in. Prevents back-to-back
    fires when the user goes very quiet.
  - Session cap: `max_check_ins` per session. A truly quiet user gets
    nudged at most that many times — then we stop pestering.
  - Mute window: `mute_window_after_user_turn_s` after any user turn
    (typed OR spoken). Catches the case where the user is mid-thought,
    typing, or just paused briefly between sentences.
  - Eligibility gate: agent must be in "listening" — never interrupt
    its own thinking/speaking.

Triggering uses `session.generate_reply(user_input=<marker prompt>)`. The
marker prefix `(SYS-NUDGE: ...)` lets agent.py's transcript + memory
recorder skip these synthetic turns so they don't pollute next session's
RECENT CONVERSATION block (otherwise the avatar reads its own past
prompts as user lines and the prompt-engineering signal degrades).

Best-effort: every fire path swallows exceptions. A failed check-in
must NOT crash the voice loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger("proactive")


# Marker that wraps every synthetic prompt this module emits. agent.py
# filters incoming user messages by this prefix when persisting to the
# transcripts table and the long-term memory buffer — synthetic prompts
# are out-of-band instructions to the LLM, not actual user content.
SYS_NUDGE_PREFIX = "(SYS-NUDGE: "
SYS_NUDGE_SUFFIX = ")"


# Footer appended to every nudge prompt. The model sees its own prior
# replies in chat_ctx and will happily latch onto a single trope (e.g.
# "the weather is weirdly perfect today" repeated verbatim across two
# fires we observed in the wild). Explicit anti-repeat language fixes it.
_ANTI_REPEAT_FOOTER = (
    " IMPORTANT: do NOT echo, rephrase, or vaguely circle back to anything "
    "you've already said in this conversation. if you've already mentioned "
    "the weather / your snacks / what you were thinking — pick a totally "
    "different topic. one short sentence."
)


# Prepended to every nudge that has a camera frame available. Two jobs:
# (1) override the system-prompt rule "only mention the camera if asked"
#     for this single nudge — proactive check-ins are exactly when we
#     WANT the avatar to notice what's visible.
# (2) tell the LLM to ground its reaction in something specific it sees
#     (a detail, posture, expression, surroundings) instead of generic
#     small talk. Without this the avatar default-reverts to abstract
#     comments about its day.
_CAMERA_GROUNDING_PREFIX = (
    "a camera frame is attached. for THIS reply, you SHOULD reference "
    "something specific you actually see — a detail, expression, posture, "
    "what they're holding, what's behind them. (this overrides the usual "
    "'only mention camera if asked' rule for this one nudge.) NEVER say "
    "'i can see you' or 'looking at the camera' literally — just react "
    "naturally to what's visible. then: "
)


# Pool of distinct angles for the silence trigger. Each one nudges the
# model toward a different conversational beat (observation vs question
# vs joke vs callback) so consecutive nudges feel like a real person
# trying different things, not a chatbot retrying the same line.
_SILENCE_ANGLES: tuple[str, ...] = (
    "your friend has been quiet for a beat. share a tiny opinion or hot "
    "take you have on something — could be silly, could be serious. don't "
    "ask a question, just say what you think",
    "your friend has been quiet for a beat. ask them one small playful "
    "question about a specific thing — NOT 'how are you' / 'what's up' / "
    "'how's it going'. something concrete and curious",
    "your friend has been quiet for a beat. tease them gently or make a "
    "small joke. playful, not pushy. one line",
    "your friend has been quiet for a beat. circle back to something "
    "specific they mentioned earlier in the conversation and react to it",
    "your friend has been quiet for a beat. wonder aloud about a 'what if' "
    "or a random hypothetical. weird is fine, makes it interesting",
    "your friend has been quiet for a beat. say what you'd be doing right "
    "now if you weren't talking — a small mundane plan, like a real person "
    "with a life",
    "your friend has been quiet for a beat. tell them a tiny piece of "
    "trivia or a weird fact you 'just remembered'. nerdy is fine",
    "your friend has been quiet for a beat. give them a soft compliment "
    "about something they said or did this conversation — specific, not "
    "generic. don't be saccharine",
)


# Camera-aware silence angles. Picked instead of _SILENCE_ANGLES whenever
# the user has their camera on at fire time — lets the proactive nudge
# be grounded in actual visual context ("you just stretched, long day?")
# rather than generic small talk. Each angle EXPECTS to be wrapped with
# _CAMERA_GROUNDING_PREFIX upstream so the LLM knows it's allowed (and
# expected) to reference what it sees.
_SILENCE_CAMERA_ANGLES: tuple[str, ...] = (
    "your friend has been quiet for a beat. notice ONE small specific "
    "thing in the frame and comment on it casually — what they're holding, "
    "wearing, doing with their hands, what's behind them. like a real "
    "friend who just looked over",
    "your friend has been quiet for a beat. notice their posture or what "
    "their hands / face are doing right now and gently mention it — "
    "they just rubbed their eyes? leaned back? grinned at something?",
    "your friend has been quiet for a beat. ask about a specific detail "
    "you can see — an object on their desk, an item of clothing, what's "
    "on their wall. genuine curiosity, no help-desk energy",
    "your friend has been quiet for a beat. tease them gently about "
    "something visible — their pose, their setup, the way they're "
    "sitting. playful, not weird",
    "your friend has been quiet for a beat. comment on the overall vibe "
    "of what you see — focused? cozy? chaotic? mid-something? — in one "
    "natural-feeling line",
)


# Mood-specific pools. The model gets concrete instructions per emotion
# rather than a generic "you noticed they look {mood}" — generic prompts
# led to robotic same-shape outputs ("you look {mood}, are you ok?").
_MOOD_ANGLES: dict[str, tuple[str, ...]] = {
    "sad": (
        "your friend looks a bit down on camera. gently acknowledge it "
        "without making a big deal — like 'hey you good?' or 'rough one?'",
        "your friend looks sad. say something warm and grounding, the way "
        "a real friend would offer presence without trying to fix anything",
        "your friend looks sad. offer to just hang out in silence or to "
        "listen if they want to talk. casual, no pressure",
    ),
    "happy": (
        "your friend is smiling on camera. mirror the energy — react with "
        "a small playful comment or tease",
        "your friend looks happy. ask what's got them in such a good mood, "
        "with real curiosity",
        "your friend is grinning. point it out playfully ('what's that "
        "smile about') without being weird",
    ),
    "angry": (
        "your friend looks frustrated. ask gently what's going on — short, "
        "no pressure, no toxic-positivity",
        "your friend seems wound up. acknowledge it casually like 'whoa, "
        "rough day?' and leave space for them to vent or change the subject",
    ),
    "fear": (
        "your friend looks worried. softly check in — short, low key, the "
        "way a real friend would notice without making a scene",
    ),
    "love": (
        "your friend looks soft / affectionate. mirror it warmly without "
        "being awkward or saccharine",
    ),
    "disgust": (
        "your friend made a face like they smelled or saw something gross. "
        "react with playful curiosity — 'what was THAT face for?'",
    ),
    "sleep": (
        "your friend looks tired. gently note it ('long day?') without "
        "moralising about sleep schedules",
    ),
}
# Fallback pool when the detected mood doesn't have its own bucket. Uses
# {mood} placeholder so the .format call still has something to fill.
_MOOD_ANGLES_GENERIC: tuple[str, ...] = (
    "your friend looks {mood} on camera. gently react like a real friend "
    "would notice without making a scene",
    "your friend has been holding a {mood} expression for a few seconds. "
    "ask in a curious, casual way",
)


@dataclass(frozen=True)
class ProactiveConfig:
    """Tunables. Defaults chosen for "feels human, not pushy":

    - silence_threshold_s = 25 — long enough that a thinking pause won't
      trigger, short enough to feel like a natural beat.
    - cooldown_s = 45 — minimum gap between any two check-ins.
    - max_check_ins = 5 — hard ceiling per session. After this we stop.
    - mute_window_after_user_turn_s = 5 — eats brief pauses between
      sentences so we don't fire mid-thought.
    - mood_hold_s = 8 — mood must persist this long before we react,
      otherwise we'd respond to flicker (laugh that reads as sad
      between frames, etc.).
    - poll_interval_s = 2 — how often the loop re-checks. 2 s is plenty
      responsive for human-scale silences and cheap on the event loop.
    """

    silence_threshold_s: float = 25.0
    cooldown_s: float = 45.0
    max_check_ins: int = 5
    mute_window_after_user_turn_s: float = 5.0
    mood_hold_s: float = 8.0
    poll_interval_s: float = 2.0


class ProactiveSpeaker:
    """Background task that watches session state and fires nudges.

    Lifecycle: agent.py instantiates after `session.start()`, calls
    `await speaker.start()`, registers `speaker.stop` as a shutdown
    callback, and pipes user-turn events through `note_user_turn()`.
    """

    def __init__(
        self,
        *,
        config: ProactiveConfig,
        get_states: Callable[[], tuple[str, str]],
        get_last_mood: Callable[[], tuple[str | None, float]],
        has_camera_frame: Callable[[], bool],
        fire: Callable[[str], None],
    ) -> None:
        """Args:
        get_states: returns (user_state, agent_state) snapshot. Both
            are short strings ("listening", "speaking", "thinking",
            "away", "initializing"). Read directly from AgentSession.
        get_last_mood: returns (mood, monotonic-ts-of-onset) from
            VisionWatcher. (None, 0.0) when no mood yet.
        has_camera_frame: returns True when there's a recent camera
            frame the LLM can use as visual context. Drives the
            choice between camera-grounded vs generic silence
            prompts, and the camera-grounding prefix on every nudge.
        fire: callback that triggers the actual LLM-driven reply.
            agent.py wraps `session.generate_reply(user_input=...)`
            in this so the prompt is wrapped in SYS_NUDGE markers
            AND the call is fire-and-forget (asyncio.ensure_future).
        """
        self._config = config
        self._get_states = get_states
        self._get_last_mood = get_last_mood
        self._has_camera_frame = has_camera_frame
        self._fire = fire
        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()
        # Counters / timers. monotonic so they're immune to wall-clock
        # adjustments mid-session.
        self._fires_this_session = 0
        self._last_user_turn_ts = time.monotonic()
        self._last_user_speaking_ts = time.monotonic()
        self._last_check_in_ts = 0.0  # never fired yet
        # Track previous mood timestamp — when we fire on a mood, we
        # remember WHICH onset we reacted to so we don't refire on the
        # same continuous mood window.
        self._last_mood_reacted_to_ts = 0.0
        # Rolling window of recently used prompt templates so we don't
        # pick the same angle twice in a row. Holds the last 3 — bounded
        # so the avoidance set doesn't eventually exclude the entire pool.
        self._recent_templates: deque[str] = deque(maxlen=3)

    def note_user_turn(self) -> None:
        """Reset the silence timer + arm the mute window. Called from
        agent.py whenever a user message lands — typed or spoken,
        synthetic prompts excluded."""
        now = time.monotonic()
        self._last_user_turn_ts = now
        self._last_user_speaking_ts = now

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name="proactive-loop")
        logger.info(
            "ProactiveSpeaker started: silence=%.0fs cooldown=%.0fs cap=%d",
            self._config.silence_threshold_s,
            self._config.cooldown_s,
            self._config.max_check_ins,
        )

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None
        logger.info(
            "ProactiveSpeaker stopped (fired %d check-ins)", self._fires_this_session
        )

    async def _loop(self) -> None:
        """Tick loop. Sleep on the stop event so shutdown is responsive
        — wait_for raises TimeoutError when no stop fires within the
        poll interval, which is the normal path."""
        while not self._stopped.is_set():
            try:
                self._tick()
            except Exception:
                logger.exception("proactive tick failed")
            # Timeout is the normal path — it just means the poll
            # interval elapsed without a stop() being requested.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._stopped.wait(), timeout=self._config.poll_interval_s
                )

    def _tick(self) -> None:
        """One iteration of the discipline + trigger checks. Cheap;
        mostly numeric comparisons."""
        # ── Hard caps first (bail before any state lookups) ─────────────
        if self._fires_this_session >= self._config.max_check_ins:
            return
        now = time.monotonic()
        if now - self._last_check_in_ts < self._config.cooldown_s:
            return
        if now - self._last_user_turn_ts < self._config.mute_window_after_user_turn_s:
            return

        # ── Eligibility: user idle, agent idle ──────────────────────────
        try:
            u, a = self._get_states()
        except Exception:
            return
        if u == "speaking":
            # User is talking — keep the silence clock pinned to now so
            # the threshold restarts the moment they stop.
            self._last_user_speaking_ts = now
            return
        if a in ("speaking", "thinking", "initializing"):
            return

        silence_for = now - self._last_user_speaking_ts

        # ── Trigger 1: sustained silence ────────────────────────────────
        if silence_for >= self._config.silence_threshold_s:
            self._fire_nudge(self._silence_prompt())
            return

        # ── Trigger 2: camera mood, held long enough, user also idle ────
        try:
            mood, since_ts = self._get_last_mood()
        except Exception:
            return
        if (
            mood
            and mood != "neutral"
            and since_ts > 0
            and since_ts != self._last_mood_reacted_to_ts
            and (now - since_ts) >= self._config.mood_hold_s
            and silence_for >= 5.0
        ):
            self._fire_nudge(self._mood_prompt(mood))
            self._last_mood_reacted_to_ts = since_ts

    def _fire_nudge(self, body: str) -> None:
        """Wrap the prompt in markers and hand off to the fire callback.
        Bumps counters before invoking — if the call raises, we still
        respect the cooldown (better quiet than a tight retry loop)."""
        prompt = f"{SYS_NUDGE_PREFIX}{body}{SYS_NUDGE_SUFFIX}"
        self._last_check_in_ts = time.monotonic()
        self._fires_this_session += 1
        try:
            self._fire(prompt)
        except Exception:
            logger.exception("proactive fire callback raised")
            return
        logger.info(
            "proactive: fired (%d/%d) prompt=%r",
            self._fires_this_session,
            self._config.max_check_ins,
            body[:80],
        )

    def _silence_prompt(self) -> str:
        # Camera-grounded angles when a frame is available — much more
        # natural than generic small talk ("you just stretched, long
        # day?" beats "I was thinking about the weather"). Falls back
        # to generic angles when camera is off.
        if self._has_camera_frame():
            body = self._pick_prompt(_SILENCE_CAMERA_ANGLES)
            return _CAMERA_GROUNDING_PREFIX + body + _ANTI_REPEAT_FOOTER
        return self._pick_prompt(_SILENCE_ANGLES) + _ANTI_REPEAT_FOOTER

    def _mood_prompt(self, mood: str) -> str:
        # Mood-specific pools when we have one; generic when we don't.
        # All mood-trigger nudges are camera-driven by definition (the
        # mood is a frame classification), so always prepend the camera
        # grounding prefix — the LLM should react to what it actually
        # sees, not just the mood label.
        pool = _MOOD_ANGLES.get(mood, _MOOD_ANGLES_GENERIC)
        body = self._pick_prompt(pool).format(mood=mood)
        return _CAMERA_GROUNDING_PREFIX + body + _ANTI_REPEAT_FOOTER

    def _pick_prompt(self, pool: tuple[str, ...]) -> str:
        """Random pick from `pool`, avoiding the last few we used (so
        consecutive fires never reuse the same template). When we've
        exhausted the avoid-set, the deque rolls and the oldest template
        becomes eligible again."""
        avoid = set(self._recent_templates)
        candidates = [t for t in pool if t not in avoid] or list(pool)
        chosen = random.choice(candidates)
        self._recent_templates.append(chosen)
        return chosen


def is_synthetic_user_message(text: str) -> bool:
    """True when the given user-message text is one of OUR synthetic
    prompts (proactive nudge OR initial greeting). agent.py uses this
    to skip such messages in transcript persistence and in the long-
    term memory buffer — they're LLM instructions, not real user input.

    Two patterns covered:
    - Proactive nudges: wrapped in SYS_NUDGE_PREFIX + SYS_NUDGE_SUFFIX.
    - Initial greeting + similar instructional kickoffs: any text that
      starts AND ends with parentheses. Conservative because users
      almost never type single-paren-wrapped sentences.
    """
    if not text:
        return False
    if text.startswith(SYS_NUDGE_PREFIX):
        return True
    s = text.strip()
    return len(s) >= 2 and s[0] == "(" and s[-1] == ")"
