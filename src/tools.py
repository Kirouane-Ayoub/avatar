import logging

from livekit.agents.llm import function_tool

logger = logging.getLogger("voice-agent-tools")


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


# Catalog drives both the setup-wizard checkboxes (UI) and the agent's tool
# filter. Keep ids in sync with TOOL_CATALOG in ui/index.html.
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
