"""Persistent per-user memory for the voice agent.

Why this exists: between sessions the agent currently forgets everything.
This module gives the avatar a long-term memory keyed by avatar identity,
so it can remember names, prior conversations, preferences, ongoing topics.

Architecture:
  - Single seam (`MemoryProvider` Protocol) so the backend is swappable
    without touching agent.py. Today: Mem0Provider. Future candidates:
    ZepProvider (if their OSS comes back), CloudProvider, etc.
  - Mem0 runs EMBEDDED inside the agent process (not a separate REST
    service) — one fewer container to manage and the SDK call surface
    is simpler than HTTP.
  - Storage: postgres-memory (pgvector image) — see docker-compose.yml.
  - Fact-extraction LLM: any OpenAI-compatible endpoint (default: the
    chat LLM at LLM_BASE_URL). Mem0 invokes this asynchronously when
    `record_turn()` is called, so the conversation latency path is
    NOT blocked by extraction.
  - Embeddings: local sentence-transformers (BAAI/bge-small-en-v1.5,
    ~130 MB) — no external API calls, no per-token cost.

Multi-user note: every method takes user_id. Today the token server
hardcodes "user", so all sessions share one memory bag — that's fine for
single-user dev. When real auth lands, the token server starts issuing
per-user identities and this module needs zero changes.

Best-effort semantics: every public method swallows exceptions and logs
them. Memory is a quality-of-life feature, NOT a hard dependency — a
broken Mem0 or down Postgres must NOT crash the conversation pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Protocol

from config import Config

logger = logging.getLogger("memory")


class MemoryProvider(Protocol):
    """The seam. Methods:

    - `record_batch` is the primary write path. agent.py buffers user
      messages and flushes a batch every N turns (and at session end);
      the provider then runs ONE LLM-driven extraction over the whole
      batch instead of N. Cuts extraction-LLM load by ~10x and lets
      the LLM reason over multiple turns at once for better facts.

    - `record_turn` is the legacy single-turn variant — kept for tests
      / one-off use. Default impl just wraps record_batch with a
      one-element list.

    - `recall` returns a SHORT prose summary of relevant prior context
      to inject into the system prompt. Returns "" when nothing is
      recalled (or anything goes wrong).

    - `forget` removes EVERY memory belonging to that owner_id. Used
      by delete-avatar (and cascade through delete-account).
    """

    async def record_batch(self, user_id: str, messages: list[dict]) -> None: ...

    async def record_turn(self, user_id: str, role: str, text: str) -> None: ...

    async def recall(self, user_id: str, query: str = "") -> str: ...

    async def forget(self, owner_id: str) -> None: ...


class NullProvider:
    """No-op. Used when memory is disabled (MEM0 env vars not set).

    Lets agent.py treat memory as always-present without an `if` guard
    on every call site.
    """

    async def record_batch(self, user_id: str, messages: list[dict]) -> None:
        return

    async def record_turn(self, user_id: str, role: str, text: str) -> None:
        return

    async def recall(self, user_id: str, query: str = "") -> str:
        return ""

    async def forget(self, owner_id: str) -> None:
        return


class Mem0Provider:
    """Mem0 SDK wrapper.

    The SDK is synchronous — we run its calls in a thread pool so the
    asyncio event loop (LiveKit, TTS, watcher) isn't blocked on disk /
    network I/O during memory operations.
    """

    def __init__(
        self,
        pg_host: str,
        pg_port: int,
        pg_user: str,
        pg_password: str,
        pg_dbname: str,
        llm_base_url: str,
        llm_api_key: str,
        llm_model: str,
        embedder_provider: str = "huggingface",
        embedder_model: str = "BAAI/bge-small-en-v1.5",
        embedder_base_url: str | None = None,
        embedder_api_key: str | None = None,
        embedder_dims: int | None = None,
    ) -> None:
        # Imported lazily so `import memory` works even when mem0ai isn't
        # installed (e.g. early dev / CI), and so the heavy import cost
        # is only paid when memory is actually enabled.
        from mem0 import Memory

        # Embedder config branches on provider:
        #   "huggingface" — local sentence-transformers, runs in-process
        #     on CPU inside the agent container. Default ~130 MB cold
        #     download to the hf-cache volume, then 10-50 ms per encode.
        #   "openai"      — any OpenAI-compatible /v1/embeddings endpoint.
        #     Default config in .env points at Ollama on the host
        #     (host.docker.internal:11434). Also works with hosted
        #     OpenAI, vLLM, anything that speaks the OpenAI shape.
        #
        # IMPORTANT: pgvector stores vectors with a fixed dimension. If
        # you switch embedder to a model with different dims (e.g. bge-
        # small=384 → text-embedding-3-small=1536) you MUST drop the
        # existing collection or use a fresh `collection_name` — old
        # rows are unreadable to the new model.
        if embedder_provider == "openai":
            embedder_cfg: dict = {
                "model": embedder_model,
                "api_key": embedder_api_key or "none",
            }
            if embedder_base_url:
                embedder_cfg["openai_base_url"] = embedder_base_url.rstrip("/")
            if embedder_dims:
                embedder_cfg["embedding_dims"] = embedder_dims
            embedder_block = {"provider": "openai", "config": embedder_cfg}
        else:
            embedder_block = {
                "provider": "huggingface",
                "config": {"model": embedder_model},
            }

        config = {
            "llm": {
                "provider": "openai",
                "config": {
                    "model": llm_model,
                    "openai_base_url": llm_base_url.rstrip("/"),
                    "api_key": llm_api_key or "none",
                    # Keep extraction cheap — Mem0's default temperature
                    # is 0.0 anyway but we set it explicitly. Short
                    # max_tokens because fact lists are short.
                    "temperature": 0.0,
                    "max_tokens": 500,
                },
            },
            "embedder": embedder_block,
            "vector_store": {
                "provider": "pgvector",
                "config": {
                    "host": pg_host,
                    "port": pg_port,
                    "user": pg_user,
                    "password": pg_password,
                    "dbname": pg_dbname,
                    # Mem0 collection name; explicit so future multi-tenant
                    # deployments can namespace this.
                    "collection_name": "memories",
                },
            },
        }
        self._memory = Memory.from_config(config)
        logger.info(
            "Mem0Provider initialized: pg=%s:%d/%s, llm=%s, embed=%s/%s%s",
            pg_host,
            pg_port,
            pg_dbname,
            llm_model,
            embedder_provider,
            embedder_model,
            f" @ {embedder_base_url}" if embedder_base_url else "",
        )

    async def record_batch(self, user_id: str, messages: list[dict]) -> None:
        """Send a batch of conversation messages to Mem0 for ONE
        extraction pass. agent.py buffers user turns and calls this
        every N turns (and at session end) — far cheaper than calling
        the extraction LLM per turn, and the LLM gets to reason over
        multiple turns at once for better facts.

        `messages` is a list of `{"role": "user"|"assistant", "content": "..."}`
        in chronological order.
        """
        # Filter empties + cap content to keep the extraction prompt
        # sane. A pathological 50 KB message could blow the context.
        cleaned = [
            {"role": m["role"], "content": m["content"][:2000].strip()}
            for m in messages
            if m.get("content") and m["content"].strip()
        ]
        if not cleaned:
            return

        # Don't log message content by default — it's PII (relationships,
        # health, etc.). LOG_USER_TEXT=1 inlines for local debugging only.
        if os.getenv("LOG_USER_TEXT") == "1":
            logger.info(
                "memory.batch: user=%s messages=%d (first=%r)",
                user_id,
                len(cleaned),
                cleaned[0]["content"][:80],
            )
        else:
            logger.info(
                "memory.batch: user=%s messages=%d (first_len=%d)",
                user_id,
                len(cleaned),
                len(cleaned[0]["content"]),
            )
        try:
            result = await asyncio.to_thread(
                self._memory.add,
                messages=cleaned,
                user_id=user_id,
            )
        except Exception:
            logger.exception("memory.batch FAILED user=%s", user_id)
            return

        # Same response-shape handling as before — log per-fact so you
        # see what Mem0 actually extracted from the batch.
        try:
            items = (
                result.get("results", [])
                if isinstance(result, dict)
                else (result or [])
            )
            if not items:
                logger.info("memory.batch -> no facts extracted user=%s", user_id)
            else:
                # Same redaction policy: opt-in LOG_USER_TEXT=1 to see the
                # actual extracted facts. By default emit count + event
                # types only so log shippers don't carry distilled PII.
                if os.getenv("LOG_USER_TEXT") == "1":
                    for it in items:
                        event = it.get("event", "?")
                        mem = (it.get("memory") or "").strip()
                        logger.info(
                            "memory.batch -> %s: %r user=%s", event, mem[:120], user_id
                        )
                else:
                    events: dict[str, int] = {}
                    for it in items:
                        evt = it.get("event", "?")
                        events[evt] = events.get(evt, 0) + 1
                    logger.info(
                        "memory.batch -> %d facts user=%s by_event=%s",
                        len(items),
                        user_id,
                        events,
                    )
        except Exception:
            logger.info("memory.batch -> raw=%s user=%s", str(result)[:200], user_id)

    async def record_turn(self, user_id: str, role: str, text: str) -> None:
        """Legacy single-turn write — wraps record_batch with a one-element
        list. Kept so any call site that still uses it (tests, etc.)
        doesn't break."""
        if not text or not text.strip():
            return
        await self.record_batch(user_id, [{"role": role, "content": text}])

    async def recall(self, user_id: str, query: str = "") -> str:
        # Empty query = "give me whatever's relevant to this user"; we
        # use the most recent user turn as the query when available, but
        # for session-start recall we just ask for everything pinned.
        mode = "get_all" if not query else "search"
        logger.info("memory.read: user=%s mode=%s query=%r", user_id, mode, query[:80])
        # Mem0 API gotcha: top-level entity kwargs (`user_id=`, `agent_id=`,
        # `run_id=`) were rejected starting with the version we're on now —
        # they raise `ValueError: Top-level entity parameters frozenset(...)
        # are not supported in get_all(). Use filters={'user_id': '...'}
        # instead.` Both `get_all` and `search` need the new shape.
        filters = {"user_id": user_id}
        try:
            if not query:
                results = await asyncio.to_thread(
                    self._memory.get_all,
                    filters=filters,
                    top_k=20,  # was `limit=` — also renamed in this Mem0 version
                )
            else:
                results = await asyncio.to_thread(
                    self._memory.search,
                    query=query,
                    filters=filters,
                    top_k=10,
                )
        except Exception:
            logger.exception("memory.read FAILED user=%s mode=%s", user_id, mode)
            return ""

        # Mem0 returns either a list[dict] or {"results": list[dict]}
        # depending on version. Normalize.
        items = results if isinstance(results, list) else results.get("results", [])
        if not items:
            logger.info("memory.read -> 0 hits user=%s", user_id)
            return ""
        lines = []
        for it in items:
            mem = it.get("memory") or it.get("text") or ""
            if mem:
                lines.append(f"- {mem.strip()}")
        if not lines:
            logger.info(
                "memory.read -> 0 usable hits (raw=%d) user=%s", len(items), user_id
            )
            return ""
        # Per-item log so you can see exactly what got injected into the
        # system prompt. Truncated so a session with 20 long memories
        # doesn't blow out the log.
        for line in lines:
            logger.info("memory.read -> hit: %s", line[:140])
        logger.info("memory.read -> %d hits user=%s", len(lines), user_id)
        return "\n".join(lines)

    async def forget(self, owner_id: str) -> None:
        """Wipe every memory for this owner_id. Used by both
        delete-avatar (owner_id = avatar_id) and delete-account
        (cascades through avatars).

        Mem0's SDK exposes `delete_all(user_id=...)` which handles its
        own pgvector schema correctly (the table layout isn't ours to
        DELETE FROM directly — it has metadata columns we shouldn't
        assume the shape of). Despite the SDK's `user_id` kwarg name,
        the value is opaque to Mem0 — it's just the string handle that
        keys retrieval.

        Best-effort: any failure is logged. The HTTP layer will still
        return 200 to the user even if memory wipe partially failed,
        because the owning row is the source of truth for "exists" —
        orphaned memory rows are inaccessible anyway since nothing else
        references the deleted id.
        """
        logger.info("memory.forget: owner=%s", owner_id)
        try:
            await asyncio.to_thread(self._memory.delete_all, user_id=owner_id)
            logger.info("memory.forget -> done owner=%s", owner_id)
        except Exception:
            logger.exception("memory.forget FAILED owner=%s", owner_id)


def build_provider(config: Config) -> MemoryProvider:
    """Factory. Returns a real provider if memory is enabled in config,
    NullProvider otherwise. Single call site in agent.py — keeps the
    enable/disable decision out of the entrypoint.

    All env reading happens in config.py — this function just consumes
    the typed Config dataclass.
    """
    if not config.memory_enabled:
        logger.info("memory disabled: MEM0_PG_HOST not set in config")
        return NullProvider()
    try:
        return Mem0Provider(
            pg_host=config.mem0_pg_host,
            pg_port=config.mem0_pg_port,
            pg_user=config.mem0_pg_user,
            pg_password=config.mem0_pg_password,
            pg_dbname=config.mem0_pg_dbname,
            llm_base_url=config.mem0_llm_base_url,
            llm_api_key=config.mem0_llm_api_key,
            llm_model=config.mem0_llm_model,
            embedder_provider=config.mem0_embedder_provider,
            embedder_model=config.mem0_embedder,
            embedder_base_url=config.mem0_embedder_base_url,
            embedder_api_key=config.mem0_embedder_api_key,
            embedder_dims=config.mem0_embedder_dims,
        )
    except Exception:
        logger.exception("memory init failed — falling back to NullProvider")
        return NullProvider()


# Note: memory_block() lives in llm.prompt now — it's about prompt
# formatting, not memory storage. Importers should now do:
#   from llm import memory_block
