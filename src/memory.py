"""Persistent per-user memory for the voice agent.

Why this exists: between sessions the agent currently forgets everything.
This module gives Lisa a long-term memory keyed by user identity, so she
can remember names, prior conversations, preferences, ongoing topics.

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
from typing import Optional, Protocol

logger = logging.getLogger("memory")


class MemoryProvider(Protocol):
    """The seam. Two methods is enough for a friend-bot.

    `record_turn` is fire-and-forget; the implementation runs fact
    extraction asynchronously and returns immediately so the voice loop
    isn't blocked.

    `recall` returns a SHORT prose summary of relevant prior context to
    inject into the system prompt. Returns "" when nothing is recalled
    (or anything goes wrong) so the caller can string-concat blindly.
    """

    async def record_turn(self, user_id: str, role: str, text: str) -> None: ...

    async def recall(self, user_id: str, query: str = "") -> str: ...


class NullProvider:
    """No-op. Used when memory is disabled (MEM0 env vars not set).

    Lets agent.py treat memory as always-present without an `if` guard
    on every call site.
    """

    async def record_turn(self, user_id: str, role: str, text: str) -> None:
        return

    async def recall(self, user_id: str, query: str = "") -> str:
        return ""


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
        embedder_base_url: Optional[str] = None,
        embedder_api_key: Optional[str] = None,
        embedder_dims: Optional[int] = None,
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
                    # Default Mem0 collection name; explicit so future
                    # multi-tenant deployments can namespace this.
                    "collection_name": "lisa_memories",
                },
            },
        }
        self._memory = Memory.from_config(config)
        logger.info(
            "Mem0Provider initialized: pg=%s:%d/%s, llm=%s, embed=%s/%s%s",
            pg_host, pg_port, pg_dbname, llm_model,
            embedder_provider, embedder_model,
            f" @ {embedder_base_url}" if embedder_base_url else "",
        )

    async def record_turn(self, user_id: str, role: str, text: str) -> None:
        if not text or not text.strip():
            return
        # mem0.add expects the chat-message shape so it can extract facts
        # from natural conversation. Run off-thread so the voice loop
        # doesn't stall on the synchronous SDK call.
        snippet = text[:80] + ("..." if len(text) > 80 else "")
        logger.info("memory.write: user=%s role=%s text=%r", user_id, role, snippet)
        try:
            result = await asyncio.to_thread(
                self._memory.add,
                messages=[{"role": role, "content": text}],
                user_id=user_id,
            )
        except Exception:
            logger.exception("memory.write FAILED user=%s", user_id)
            return

        # mem0.add returns a dict like {"results": [{"memory": "...", "event": "ADD"|"UPDATE"|"NONE"}, ...]}
        # — surface what was actually extracted so you can see Mem0's
        # judgment in real time. "NONE" means Mem0 decided no new fact
        # was worth recording from this turn (very common for filler).
        try:
            items = result.get("results", []) if isinstance(result, dict) else (result or [])
            if not items:
                logger.info("memory.write -> no facts extracted user=%s", user_id)
            else:
                for it in items:
                    event = it.get("event", "?")
                    mem = (it.get("memory") or "").strip()
                    logger.info("memory.write -> %s: %r user=%s", event, mem[:120], user_id)
        except Exception:
            # Diagnostic logging must never break the call site — if the
            # response shape changes upstream, just log raw and move on.
            logger.info("memory.write -> raw=%s user=%s", str(result)[:200], user_id)

    async def recall(self, user_id: str, query: str = "") -> str:
        # Empty query = "give me whatever's relevant to this user"; we
        # use the most recent user turn as the query when available, but
        # for session-start recall we just ask for everything pinned.
        mode = "get_all" if not query else "search"
        logger.info("memory.read: user=%s mode=%s query=%r", user_id, mode, query[:80])
        try:
            # `get_all` returns ALL memories for the user; for short
            # sessions and small per-user memory this is fine. If we
            # later have users with hundreds of facts, swap to
            # `search(query=..., limit=N)` keyed off the latest turn.
            if not query:
                results = await asyncio.to_thread(
                    self._memory.get_all, user_id=user_id, limit=20,
                )
            else:
                results = await asyncio.to_thread(
                    self._memory.search, query=query, user_id=user_id, limit=10,
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
            logger.info("memory.read -> 0 usable hits (raw=%d) user=%s", len(items), user_id)
            return ""
        # Per-item log so you can see exactly what got injected into the
        # system prompt. Truncated so a session with 20 long memories
        # doesn't blow out the log.
        for line in lines:
            logger.info("memory.read -> hit: %s", line[:140])
        logger.info("memory.read -> %d hits user=%s", len(lines), user_id)
        return "\n".join(lines)


def build_provider() -> MemoryProvider:
    """Factory. Returns a real provider if memory env vars are set,
    NullProvider otherwise. Single call site in agent.py — keeps the
    config decision out of the entrypoint."""
    pg_host = os.getenv("MEM0_PG_HOST")
    if not pg_host:
        logger.info("memory disabled: MEM0_PG_HOST not set")
        return NullProvider()
    try:
        embedder_dims_env = os.getenv("MEM0_EMBEDDER_DIMS")
        return Mem0Provider(
            pg_host=pg_host,
            pg_port=int(os.getenv("MEM0_PG_PORT", "5432")),
            pg_user=os.getenv("MEM0_PG_USER", "mem0"),
            pg_password=os.getenv("MEM0_PG_PASSWORD", "mem0"),
            pg_dbname=os.getenv("MEM0_PG_DBNAME", "mem0"),
            llm_base_url=os.getenv("MEM0_LLM_BASE_URL")
            or os.environ["LLM_BASE_URL"],
            llm_api_key=os.getenv("MEM0_LLM_API_KEY")
            or os.getenv("LLM_API_KEY", "none"),
            llm_model=os.getenv("MEM0_LLM_MODEL")
            or os.environ["LLM_MODEL"],
            embedder_provider=os.getenv("MEM0_EMBEDDER_PROVIDER", "huggingface"),
            embedder_model=os.getenv("MEM0_EMBEDDER", "BAAI/bge-small-en-v1.5"),
            embedder_base_url=os.getenv("MEM0_EMBEDDER_BASE_URL"),
            embedder_api_key=os.getenv("MEM0_EMBEDDER_API_KEY"),
            embedder_dims=int(embedder_dims_env) if embedder_dims_env else None,
        )
    except Exception:
        logger.exception("memory init failed — falling back to NullProvider")
        return NullProvider()


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
