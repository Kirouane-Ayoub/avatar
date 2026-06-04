"""TTS engines + voice catalog.

Three TTS plugins (Kokoro, Orpheus, Supertonic) plus the voice catalog
that maps voice ids → backend choice. Lives together because the voice
catalog IS the routing table that decides which TTS plugin handles a
session.
"""

from .kokoro import (  # noqa: F401
    KokoroConfig,
    KokoroTTS,
)
from .orpheus import (  # noqa: F401
    OrpheusConfig,
    OrpheusTTS,
)
from .supertonic import (  # noqa: F401
    SupertonicConfig,
    SupertonicTTS,
)
from .voices import (  # noqa: F401
    KOKORO_VOICES,
    ORPHEUS_VOICES,
    SUPERTONIC_VOICES,
    backend_for,
    is_known_voice,
    stt_language_for,
    supertonic_style_for,
)
