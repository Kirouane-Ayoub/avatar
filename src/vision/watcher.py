from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger("vision_watcher")


# Subset of cues.MOODS — only "safe" ambient moods. The high-stakes ones
# (angry, fear, sleep) belong to the LLM at speech time, not to a passive
# observer that could misread a frame.
AMBIENT_MOODS = ("neutral", "happy", "sad", "love", "disgust")


_PROMPT = (
    "You are reading the user's facial expression in this single frame. "
    "Reply with EXACTLY ONE WORD from this list:\n"
    f"  {', '.join(AMBIENT_MOODS)}, pass\n"
    "\n"
    "Rules:\n"
    "- Reply with one word from the list, no punctuation, no explanation.\n"
    "- For any visible face, pick the closest matching mood. Use 'neutral' "
    "for a resting/attentive expression — that is the normal default.\n"
    "- Use 'pass' ONLY if you can't see a face at all (dark frame, looking "
    "away, occluded). Don't use 'pass' just because the expression is mild.\n"
    "- Never invent moods outside the list."
)


@dataclass
class VisionWatcherConfig:
    base_url: str
    model: str
    interval_s: float = 1.0
    # Don't change mood more than once per this many seconds. Prevents
    # twitchy avatar when the VLM flickers between e.g. neutral/happy.
    # 3 s is a balance: fast enough to feel responsive, long enough that
    # TalkingHead's ~1.5 s morph interpolation can settle before the next
    # change kicks in.
    min_hold_s: float = 3.0
    # Per-request timeout. The 2B model on M4 Pro replies in ~200-400 ms;
    # 3 s gives plenty of headroom without stalling the loop.
    request_timeout_s: float = 3.0
    max_tokens: int = 8


class VisionWatcher:
    """Background loop that turns camera frames into ambient mood cues.

    Wire it up:
        watcher = VisionWatcher(
            config=VisionWatcherConfig(base_url=..., model=...),
            get_frame_data_url=lambda: agent._last_image_url,
            is_idle=lambda: ...,  # True only when no one is speaking
            publish_cue=publish_cue,
        )
        await watcher.start()
        ...
        await watcher.stop()
    """

    def __init__(
        self,
        config: VisionWatcherConfig,
        get_frame_data_url: Callable[[], str | None],
        is_idle: Callable[[], bool],
        publish_cue: Callable[[str, str], None],
    ) -> None:
        self._config = config
        self._get_frame = get_frame_data_url
        self._is_idle = is_idle
        self._publish_cue = publish_cue
        self._task: asyncio.Task | None = None
        self._session: aiohttp.ClientSession | None = None
        self._last_mood: str | None = None
        self._last_change_t: float = 0.0

    async def start(self) -> None:
        if self._task is not None:
            return
        self._session = aiohttp.ClientSession()
        self._task = asyncio.create_task(self._run(), name="vision-watcher")
        logger.info(
            "VisionWatcher started: model=%s interval=%.1fs min_hold=%.1fs",
            self._config.model,
            self._config.interval_s,
            self._config.min_hold_s,
        )

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._session is not None:
            await self._session.close()
            self._session = None
        logger.info("VisionWatcher stopped")

    def get_last_mood(self) -> tuple[str | None, float]:
        """Snapshot of the last emitted mood + the monotonic timestamp
        when it was first detected (i.e. how long the user has held
        this mood). Returns (None, 0.0) when no mood has been emitted
        yet — caller should treat that as "no signal".

        Read-only accessor used by ProactiveSpeaker to gate its mood-
        based check-in trigger. Doesn't take the lock — these two
        attributes are written together inside _maybe_emit and a torn
        read just means a one-tick race, which is harmless.
        """
        return (self._last_mood, self._last_change_t)

    async def _run(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._config.interval_s)
                if not self._is_idle():
                    continue
                frame = self._get_frame()
                if not frame:
                    continue
                mood = await self._classify(frame)
                if mood is None:
                    continue
                self._maybe_emit(mood)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("VisionWatcher loop crashed")

    async def _classify(self, frame_data_url: str) -> str | None:
        """Single VLM round-trip. Returns a mood label or None on failure / pass."""
        assert self._session is not None
        payload = {
            "model": self._config.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _PROMPT},
                        {"type": "image_url", "image_url": {"url": frame_data_url}},
                    ],
                }
            ],
            "max_tokens": self._config.max_tokens,
            "temperature": 0.0,
        }
        try:
            async with self._session.post(
                f"{self._config.base_url.rstrip('/')}/v1/chat/completions",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=self._config.request_timeout_s),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning("VLM HTTP %s: %s", resp.status, body[:200])
                    return None
                data = await resp.json()
        except TimeoutError:
            logger.debug("VLM timeout")
            return None
        except Exception as e:
            logger.warning("VLM request failed: %s", e)
            return None

        try:
            raw = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            logger.warning("VLM unexpected response shape: %s", str(data)[:200])
            return None

        word = (raw or "").strip().lower().split()[0:1]
        if not word:
            logger.info("VLM returned empty response")
            return None
        label = word[0].strip(".,!?;:'\"")
        if label == "pass":
            logger.info("VLM -> pass (no face visible)")
            return None
        if label not in AMBIENT_MOODS:
            logger.info("VLM out-of-vocab label: %r (raw=%r)", label, raw[:60])
            return None
        logger.info("VLM read -> %s", label)
        return label

    def _maybe_emit(self, mood: str) -> None:
        now = time.monotonic()
        if mood == self._last_mood:
            logger.info("skip: same as last (%s)", mood)
            return
        if now - self._last_change_t < self._config.min_hold_s:
            logger.info(
                "skip: hysteresis hold (%s -> %s, %.1fs since last change, need %.1fs)",
                self._last_mood,
                mood,
                now - self._last_change_t,
                self._config.min_hold_s,
            )
            return
        self._last_mood = mood
        self._last_change_t = now
        logger.info("ambient mood -> %s", mood)
        try:
            self._publish_cue("mood", mood)
        except Exception:
            logger.exception("publish_cue failed")
