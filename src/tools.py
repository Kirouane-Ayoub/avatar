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

import functools
import logging
import time

from livekit.agents.llm import function_tool

logger = logging.getLogger("voice-agent-tools")


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
            ", ".join(f"{k}={repr(v)[:80]}" for k, v in kwargs.items()) if kwargs else ""
        )
        sig = ", ".join(p for p in (args_repr, kwargs_repr) if p)
        logger.info("TOOL ▶ %s(%s)", name, sig)

        t0 = time.monotonic()
        try:
            result = await func(*args, **kwargs)
        except Exception as e:
            took_ms = round((time.monotonic() - t0) * 1000)
            logger.exception("TOOL ✗ %s | took=%dms error=%s", name, took_ms, e)
            raise

        took_ms = round((time.monotonic() - t0) * 1000)
        result_preview = repr(result)[:200] if result is not None else "None"
        logger.info("TOOL ◀ %s | took=%dms result=%s", name, took_ms, result_preview)
        return result

    return wrapper


@function_tool(
    description="Set a reminder or timer with a message. Duration in seconds."
)
@_log_tool
async def set_reminder(message: str, seconds: int) -> str:
    """Acknowledge the reminder (actual timer would need background task)."""
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
    return f"(online_search not implemented yet — would search for: {query})"


@function_tool(description="Search internal/private knowledge base or documents.")
@_log_tool
async def internal_search(query: str) -> str:
    """Stub — to be wired up to a real internal search backend later."""
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
