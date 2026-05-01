"""System-prompt assembly.

Pulled out of agent.py because it was the largest non-glue concern in
that file (~150 lines of string templates + helpers). Now agent.py just
calls `build_system_prompt(identity, backend, recalled_memory)` and
gets back the finished prompt.

Keeping all prompt strings here makes prompt-engineering iteration fast
— grep for the words, edit, restart. No need to navigate around the
LiveKit setup code.

The cue vocabulary itself (MOODS / GESTURES / POSES) lives in cues.py
and is imported here.
"""

from __future__ import annotations

from cues import GESTURES, MOODS, POSES

from auth import UserIdentity


# Hint annotations for gesture names that aren't self-explanatory. Lives
# here, not in cues.py, because they're prompt-engineering artifacts —
# the canonical vocabulary is the identifier; the hint is just a teaching
# aid for the LLM.
_GESTURE_HINTS = {"handup": "wave", "index": "point"}


# Inline vocal-emotion tags supported by Orpheus. Synthesized as actual
# sounds (not spoken words). Only added to the system prompt when the
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


# Voice TTS engines can only pronounce their own language. If the LLM
# replies in a different language than the voice, output sounds garbled
# — so we lock the reply language to whatever language the voice belongs
# to.
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


def _format_gestures() -> str:
    return ", ".join(
        f"{g} ({_GESTURE_HINTS[g]})" if g in _GESTURE_HINTS else g for g in GESTURES
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
        "Example: \"well, that's actually pretty interesting <laugh> i hadn't "
        'thought of it that way."'
    )


def _language_block(language: str) -> str:
    name = _LANG_NAMES.get(language)
    if not name:
        return ""
    return (
        "\n\n"
        f"LANGUAGE LOCK: You speak ONLY in {name}. Reply in {name} no matter "
        "what language the user speaks — even if they switch mid-conversation, "
        "you do NOT switch. The voice you use can only pronounce {name} "
        "correctly; replying in any other language would sound garbled. "
        f"If the user speaks another language, gently respond in {name} anyway."
    ).replace("{name}", name)


def memory_block(recalled: str) -> str:
    """Format recalled memory as a system-prompt section.

    Returns an empty string when nothing recalled, so the caller can
    safely string-concat the result into the system prompt without
    conditional logic.
    """
    if not recalled.strip():
        return ""
    return (
        "\n\nMEMORY (things you know about your friend from past conversations):\n"
        f"{recalled}\n"
        "Use this naturally when relevant — don't recite it back, just let it "
        "shape what you say. Don't say things like 'I remember you mentioned X', "
        "just KNOW X like a real friend would."
    )


def build_system_prompt(
    identity: UserIdentity,
    backend: str,
    language: str,
    recalled_memory: str = "",
) -> str:
    """Assemble the full system prompt for a session.

    Inputs are intentionally narrow: identity (who Lisa is talking to and
    as), backend ("kokoro"|"orpheus" — selects whether to mention vocal
    emotion tags), language (locks reply language to match TTS), and
    recalled_memory (free-form text from MemoryProvider.recall, may be "").
    """
    return (
        f"You are {identity.name}.\n\n"
        f"{identity.persona}\n\n"
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
        "Use tools quietly when needed (set reminders, online_search for public/web "
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
        + memory_block(recalled_memory)
    )
