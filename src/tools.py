"""Function tools the LLM can invoke during a session.

Every tool is wrapped with `@_log_tool` so each invocation prints a clear
"▶ name | args=…" entry log and a "◀ name | took=Xms result=…" exit log.
That gives you a tail-the-agent view of which tools the LLM is actually
choosing to use during a conversation, with full visibility into args
and results — useful both for debugging tool prompts and for confirming
the LLM is calling the tool you expected (vs hallucinating an answer).

Decorator order matters: `@_log_tool` is applied INSIDE `@function_tool`
so the tool registered with LiveKit is the logged version, not the bare
function. functools.wraps preserves the signature so livekit-agents'
parameter introspection still works.

LiveKit's own tool-call logging (model_dialect logs at INFO when the
LLM emits a function_call) gives a higher-level "the model wants to
call X" signal; our `_log_tool` then surfaces "X actually executed,
here's what it returned in N ms".
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from collections.abc import Callable
from typing import Any

from livekit.agents.llm import function_tool

# Artificial latency on every tool so the UI's "tool running" pill stays
# on screen long enough to see. The stubs return in <1 ms, which makes
# the badge flash invisibly. Was 10 s — that turned a tool call into a
# DoS amplifier (the LLM can request multiple tools per turn). 1.0 s is
# enough for the UI pill to register without blocking the conversation
# loop; set to 0 once real backends (DuckDuckGo, etc.) are wired and
# naturally take 1-3 s.
_FAKE_TOOL_LATENCY_SEC = 1.0

logger = logging.getLogger("voice-agent-tools")


# Per-session sink for tool start/end/error events. agent.py wires this
# at session start so the UI gets a live "tool activity" pill while a
# function is running. Module-level (not ContextVar): livekit-agents
# spawns the tool-execution task from internal machinery whose Context
# was captured BEFORE we set the sink, so contextvars don't propagate
# in. Single-session-per-worker deployments — concurrent sessions in
# the same process would see this clobber. Revisit when that lands.
_event_sink: Callable[[dict[str, Any]], None] | None = None


def set_event_sink(fn: Callable[[dict[str, Any]], None] | None) -> None:
    """Wire the session sink. agent.py calls this with a closure that
    publishes events on the LiveKit DataChannel. None disables event
    forwarding (e.g. for tests / standalone runs)."""
    global _event_sink
    _event_sink = fn


def _emit(event: dict[str, Any]) -> None:
    """Best-effort send to the active sink. Swallow exceptions so a
    DataChannel hiccup never breaks the tool execution path."""
    if _event_sink is None:
        return
    try:
        _event_sink(event)
    except Exception as e:
        logger.warning("tool event sink failed: %s", e)


def _log_tool(func):
    """Entry/exit logger + timing for an async tool.

    Prints two log lines per call:
      TOOL ▶ <name> | args=(...) kwargs={...}
      TOOL ◀ <name> | took=Xms result='...'   (truncated to 200 chars)

    On exception, the second line becomes:
      TOOL ✗ <name> | took=Xms error=...
    and the exception is logged with full traceback (logger.exception).
    The exception is then re-raised so livekit-agents handles it.
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        name = func.__name__
        # Render args/kwargs compactly. Long inputs (e.g. multi-paragraph
        # search queries) are truncated so a single tool call doesn't
        # spam the log with a screenful of text.
        args_repr = ", ".join(repr(a)[:80] for a in args) if args else ""
        kwargs_repr = (
            ", ".join(f"{k}={repr(v)[:80]}" for k, v in kwargs.items())
            if kwargs
            else ""
        )
        sig = ", ".join(p for p in (args_repr, kwargs_repr) if p)
        logger.info("TOOL ▶ %s(%s)", name, sig)
        _emit({"type": "tool", "op": "start", "name": name, "args": sig[:120]})

        t0 = time.monotonic()
        try:
            result = await func(*args, **kwargs)
        except Exception as e:
            took_ms = round((time.monotonic() - t0) * 1000)
            logger.exception("TOOL ✗ %s | took=%dms error=%s", name, took_ms, e)
            _emit(
                {
                    "type": "tool",
                    "op": "error",
                    "name": name,
                    "took_ms": took_ms,
                    "error": str(e)[:200],
                }
            )
            raise

        took_ms = round((time.monotonic() - t0) * 1000)
        result_preview = repr(result)[:200] if result is not None else "None"
        logger.info("TOOL ◀ %s | took=%dms result=%s", name, took_ms, result_preview)
        _emit({"type": "tool", "op": "end", "name": name, "took_ms": took_ms})
        return result

    return wrapper


@function_tool(
    description="Set a reminder or timer with a message. Duration in seconds."
)
@_log_tool
async def set_reminder(message: str, seconds: int) -> str:
    """Acknowledge the reminder (actual timer would need background task)."""
    await asyncio.sleep(_FAKE_TOOL_LATENCY_SEC)
    if seconds < 0:
        return "Duration must be positive"
    if seconds >= 3600:
        return f"Reminder set: '{message}' in {seconds // 3600} hours and {(seconds % 3600) // 60} minutes"
    elif seconds >= 60:
        return f"Reminder set: '{message}' in {seconds // 60} minutes"
    return f"Reminder set: '{message}' in {seconds} seconds"


@function_tool(
    description="Search the public web for up-to-date information on a topic."
)
@_log_tool
async def online_search(query: str) -> str:
    """Stub — to be wired up to a real web search backend later."""
    await asyncio.sleep(_FAKE_TOOL_LATENCY_SEC)
    return f"(online_search not implemented yet — would search for: {query})"


@function_tool(description="Search internal/private knowledge base or documents.")
@_log_tool
async def internal_search(query: str) -> str:
    """Stub — to be wired up to a real internal search backend later."""
    await asyncio.sleep(_FAKE_TOOL_LATENCY_SEC)
    return f"(internal_search not implemented yet — would search for: {query})"


# Catalog drives both the setup-wizard checkboxes (UI) and the agent's tool
# filter. Keep ids in sync with TOOL_CATALOG in ui/src/data/tools.ts.
TOOL_CATALOG = {
    "set_reminder": {
        "tool": set_reminder,
        "label": "Reminders",
        "description": "Set timers / reminders",
    },
    "online_search": {
        "tool": online_search,
        "label": "Web search",
        "description": "Public web search",
    },
    "internal_search": {
        "tool": internal_search,
        "label": "Internal search",
        "description": "Private docs / knowledge base",
    },
}

ALL_TOOLS = [entry["tool"] for entry in TOOL_CATALOG.values()]
