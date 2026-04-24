"""Function tools for Lisa voice assistant."""

import logging

from livekit.agents.llm import function_tool

logger = logging.getLogger("lisa-tools")


@function_tool(description="Do a math calculation. Supports +, -, *, /, **, sqrt, etc.")
async def calculate(expression: str) -> str:
    """Evaluate a math expression safely."""
    allowed = set("0123456789+-*/.() ")
    if not all(c in allowed for c in expression):
        return "I can only calculate simple math expressions"
    try:
        result = eval(expression, {"__builtins__": {}}, {})
        return f"{expression} = {result}"
    except Exception:
        return f"Could not calculate: {expression}"


@function_tool(
    description="Set a reminder or timer with a message. Duration in seconds."
)
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
async def online_search(query: str) -> str:
    """Stub — to be wired up to a real web search backend later."""
    logger.info("online_search stub called with query=%r", query)
    return f"(online_search not implemented yet — would search for: {query})"


@function_tool(description="Search internal/private knowledge base or documents.")
async def internal_search(query: str) -> str:
    """Stub — to be wired up to a real internal search backend later."""
    logger.info("internal_search stub called with query=%r", query)
    return f"(internal_search not implemented yet — would search for: {query})"


# Collect all tools into a list for easy import
ALL_TOOLS = [
    calculate,
    set_reminder,
    online_search,
    internal_search,
]
