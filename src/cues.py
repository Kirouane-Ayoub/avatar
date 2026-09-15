"""Canonical vocabulary for avatar cue tags.

The LLM emits `[mood:X][gesture:Y][pose:Z]` tags at the start of every reply;
the UI reads those tags and drives TalkingHead morph/pose/animation state.
Everything that needs to know what values are valid imports from here:

  - src/agent.py           — renders the values into the system prompt
  - ui/server.py           — validates wizard input against MOODS

The TypeScript side has a parallel definition at ui/src/data/cues.ts that
must be kept in sync when this file changes.
"""

MOODS: tuple[str, ...] = (
    "neutral",
    "happy",
    "sad",
    "angry",
    "fear",
    "disgust",
    "love",
    "sleep",
)

GESTURES: tuple[str, ...] = (
    "handup",
    "index",
    "ok",
    "thumbup",
    "thumbdown",
    "side",
    "shrug",
    "namaste",
)

POSES: tuple[str, ...] = (
    "straight",
    "side",
    "hip",
    "wide",
    "turn",
    "bend",
    "back",
    "oneknee",
    "kneel",
    "sitting",
)
