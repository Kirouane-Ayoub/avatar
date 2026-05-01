# Canonical Kokoro-82M voice catalog.
# Source: https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md
# Grade is the overall quality tier from the upstream README.
# Keep the UI-side VOICE_CATALOG in ui/index.html in sync (or let it fetch
# /api/voices).

KOKORO_VOICES = {
    # American English — Female
    "af_heart": {"language": "American English", "gender": "F", "grade": "A"},
    "af_alloy": {"language": "American English", "gender": "F", "grade": "C"},
    "af_aoede": {"language": "American English", "gender": "F", "grade": "C+"},
    "af_bella": {"language": "American English", "gender": "F", "grade": "A-"},
    "af_jessica": {"language": "American English", "gender": "F", "grade": "D"},
    "af_kore": {"language": "American English", "gender": "F", "grade": "C+"},
    "af_nicole": {"language": "American English", "gender": "F", "grade": "B-"},
    "af_nova": {"language": "American English", "gender": "F", "grade": "C"},
    "af_river": {"language": "American English", "gender": "F", "grade": "D"},
    "af_sarah": {"language": "American English", "gender": "F", "grade": "C+"},
    "af_sky": {"language": "American English", "gender": "F", "grade": "C-"},
    # American English — Male
    "am_adam": {"language": "American English", "gender": "M", "grade": "F+"},
    "am_echo": {"language": "American English", "gender": "M", "grade": "D"},
    "am_eric": {"language": "American English", "gender": "M", "grade": "D"},
    "am_fenrir": {"language": "American English", "gender": "M", "grade": "C+"},
    "am_liam": {"language": "American English", "gender": "M", "grade": "D"},
    "am_michael": {"language": "American English", "gender": "M", "grade": "C+"},
    "am_onyx": {"language": "American English", "gender": "M", "grade": "D"},
    "am_puck": {"language": "American English", "gender": "M", "grade": "C+"},
    "am_santa": {"language": "American English", "gender": "M", "grade": "D-"},
    # British English — Female
    "bf_alice": {"language": "British English", "gender": "F", "grade": "D"},
    "bf_emma": {"language": "British English", "gender": "F", "grade": "B-"},
    "bf_isabella": {"language": "British English", "gender": "F", "grade": "C"},
    "bf_lily": {"language": "British English", "gender": "F", "grade": "D"},
    # British English — Male
    "bm_daniel": {"language": "British English", "gender": "M", "grade": "D"},
    "bm_fable": {"language": "British English", "gender": "M", "grade": "C"},
    "bm_george": {"language": "British English", "gender": "M", "grade": "C"},
    "bm_lewis": {"language": "British English", "gender": "M", "grade": "D+"},
    # Japanese
    "jf_alpha": {"language": "Japanese", "gender": "F", "grade": "C+"},
    "jf_gongitsune": {"language": "Japanese", "gender": "F", "grade": "C"},
    "jf_nezumi": {"language": "Japanese", "gender": "F", "grade": "C-"},
    "jf_tebukuro": {"language": "Japanese", "gender": "F", "grade": "C"},
    "jm_kumo": {"language": "Japanese", "gender": "M", "grade": "C-"},
    # Mandarin Chinese
    "zf_xiaobei": {"language": "Mandarin Chinese", "gender": "F", "grade": "D"},
    "zf_xiaoni": {"language": "Mandarin Chinese", "gender": "F", "grade": "D"},
    "zf_xiaoxiao": {"language": "Mandarin Chinese", "gender": "F", "grade": "D"},
    "zf_xiaoyi": {"language": "Mandarin Chinese", "gender": "F", "grade": "D"},
    "zm_yunjian": {"language": "Mandarin Chinese", "gender": "M", "grade": "D"},
    "zm_yunxi": {"language": "Mandarin Chinese", "gender": "M", "grade": "D"},
    # Upstream files this under zm_ (male) but the voice is actually female —
    # the name 云霞 (yunxia, "rosy clouds") is overwhelmingly a female given
    # name in Chinese. Listen-confirmed.
    "zm_yunxia": {"language": "Mandarin Chinese", "gender": "F", "grade": "D"},
    "zm_yunyang": {"language": "Mandarin Chinese", "gender": "M", "grade": "D"},
    # Spanish
    "ef_dora": {"language": "Spanish", "gender": "F", "grade": ""},
    "em_alex": {"language": "Spanish", "gender": "M", "grade": ""},
    "em_santa": {"language": "Spanish", "gender": "M", "grade": ""},
    # French
    "ff_siwis": {"language": "French", "gender": "F", "grade": "B-"},
    # Hindi
    "hf_alpha": {"language": "Hindi", "gender": "F", "grade": "C"},
    "hf_beta": {"language": "Hindi", "gender": "F", "grade": "C"},
    "hm_omega": {"language": "Hindi", "gender": "M", "grade": "C"},
    "hm_psi": {"language": "Hindi", "gender": "M", "grade": "C"},
    # Italian
    "if_sara": {"language": "Italian", "gender": "F", "grade": "C"},
    "im_nicola": {"language": "Italian", "gender": "M", "grade": "C"},
    # Brazilian Portuguese
    "pf_dora": {"language": "Brazilian Portuguese", "gender": "F", "grade": ""},
    "pm_alex": {"language": "Brazilian Portuguese", "gender": "M", "grade": ""},
    "pm_santa": {"language": "Brazilian Portuguese", "gender": "M", "grade": ""},
}

# Orpheus voice catalog (Orpheus-FastAPI backend, Lex-au/Orpheus-FastAPI).
# Multilingual. The `stt` field is the Whisper language code that pairs with
# the voice — used by stt_language_for() since Orpheus voice ids don't follow
# the Kokoro single-letter prefix convention. The `description` field is the
# upstream-documented timbre/personality, surfaced in the wizard voice picker.
ORPHEUS_VOICES = {
    # English
    "tara": {"language": "English", "gender": "F", "grade": "", "stt": "en", "description": "conversational, clear"},
    "leah": {"language": "English", "gender": "F", "grade": "", "stt": "en", "description": "warm, gentle"},
    "jess": {"language": "English", "gender": "F", "grade": "", "stt": "en", "description": "energetic, youthful"},
    "mia":  {"language": "English", "gender": "F", "grade": "", "stt": "en", "description": "professional, articulate"},
    "zoe":  {"language": "English", "gender": "F", "grade": "", "stt": "en", "description": "calm, soothing"},
    "leo":  {"language": "English", "gender": "M", "grade": "", "stt": "en", "description": "authoritative, deep"},
    "dan":  {"language": "English", "gender": "M", "grade": "", "stt": "en", "description": "friendly, casual"},
    "zac":  {"language": "English", "gender": "M", "grade": "", "stt": "en", "description": "enthusiastic, dynamic"},
    # French
    "pierre": {"language": "French", "gender": "M", "grade": "", "stt": "fr", "description": "sophisticated"},
    "amelie": {"language": "French", "gender": "F", "grade": "", "stt": "fr", "description": "elegant"},
    "marie":  {"language": "French", "gender": "F", "grade": "", "stt": "fr", "description": "spirited"},
    # German
    "jana":   {"language": "German", "gender": "F", "grade": "", "stt": "de", "description": "clear"},
    "thomas": {"language": "German", "gender": "M", "grade": "", "stt": "de", "description": "authoritative"},
    "max":    {"language": "German", "gender": "M", "grade": "", "stt": "de", "description": "energetic"},
    # Spanish
    "javi":   {"language": "Spanish", "gender": "M", "grade": "", "stt": "es", "description": "warm"},
    "sergio": {"language": "Spanish", "gender": "M", "grade": "", "stt": "es", "description": "professional"},
    "maria":  {"language": "Spanish", "gender": "F", "grade": "", "stt": "es", "description": "friendly"},
    # Italian
    "pietro": {"language": "Italian", "gender": "M", "grade": "", "stt": "it", "description": "passionate"},
    "giulia": {"language": "Italian", "gender": "F", "grade": "", "stt": "it", "description": "expressive"},
    "carlo":  {"language": "Italian", "gender": "M", "grade": "", "stt": "it", "description": "refined"},
    # Korean
    "유나": {"language": "Korean", "gender": "F", "grade": "", "stt": "ko", "description": "melodic"},
    "준서": {"language": "Korean", "gender": "M", "grade": "", "stt": "ko", "description": "confident"},
    # Hindi
    "ऋतिका": {"language": "Hindi", "gender": "F", "grade": "", "stt": "hi", "description": "expressive"},
    # Mandarin Chinese
    "长乐": {"language": "Mandarin Chinese", "gender": "F", "grade": "", "stt": "zh", "description": "gentle"},
    "白芷": {"language": "Mandarin Chinese", "gender": "F", "grade": "", "stt": "zh", "description": "clear"},
}


def backend_for(voice_id: str) -> str:
    """Return 'orpheus' or 'kokoro' for a known voice id; 'kokoro' as a safe
    default. The agent uses this to pick the right TTS implementation."""
    if voice_id in ORPHEUS_VOICES:
        return "orpheus"
    return "kokoro"


def is_known_voice(voice_id: str) -> bool:
    return voice_id in KOKORO_VOICES or voice_id in ORPHEUS_VOICES


# Voice-id prefix → STT/Whisper language code.
# (British → 'en'; multilingual Whisper treats both the same.)
_LANG_BY_PREFIX = {
    "a": "en",
    "b": "en",
    "j": "ja",
    "z": "zh",
    "e": "es",
    "f": "fr",
    "h": "hi",
    "i": "it",
    "p": "pt",
}


def stt_language_for(voice_id: str, fallback: str = "en") -> str:
    """Return the Whisper language code that matches a voice id (Kokoro or
    Orpheus)."""
    if not voice_id:
        return fallback
    if voice_id in ORPHEUS_VOICES:
        return ORPHEUS_VOICES[voice_id].get("stt", fallback)
    return _LANG_BY_PREFIX.get(voice_id[:1].lower(), fallback)
