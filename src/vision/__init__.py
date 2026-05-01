"""Vision pipeline. Today: ambient affect watcher.

Future-proofed as a package so additions (gesture recognition, scene
classification, etc.) drop in here without flat-file sprawl in src/.
"""

from .watcher import (  # noqa: F401
    VisionWatcher,
    VisionWatcherConfig,
)
