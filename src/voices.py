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
    "zm_yunxia": {"language": "Mandarin Chinese", "gender": "M", "grade": "D"},
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
    """Return the Whisper language code that matches a Kokoro voice id."""
    if not voice_id:
        return fallback
    return _LANG_BY_PREFIX.get(voice_id[:1].lower(), fallback)
