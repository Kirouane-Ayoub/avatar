"""Persistent per-user memory. Today: Mem0 SDK wrapper.

Future-proofed as a package so an alternate provider (Zep, custom,
cloud-managed) can drop in alongside provider.py — change the factory,
keep the Protocol surface identical.
"""

from .provider import (  # noqa: F401
    Mem0Provider,
    MemoryProvider,
    NullProvider,
    build_provider,
)
