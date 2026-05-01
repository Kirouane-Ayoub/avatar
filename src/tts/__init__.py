"""TTS engines + voice catalog.

Two TTS plugins (Kokoro, Orpheus) plus the voice catalog that maps
voice ids → backend choice. Lives together because the voice catalog
IS the routing table that decides which TTS plugin handles a session.
"""

from .kokoro import (  # noqa: F401
    KokoroConfig,
    KokoroTTS,
)
from .orpheus import (  # noqa: F401
    OrpheusConfig,
    OrpheusTTS,
)
from .voices import (  # noqa: F401
    KOKORO_VOICES,
    ORPHEUS_VOICES,
    backend_for,
    is_known_voice,
    stt_language_for,
)
