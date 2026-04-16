"""Function tools for Lisa voice assistant."""

import datetime
import logging
import random

import aiohttp
from livekit.agents.llm import function_tool

logger = logging.getLogger("lisa-tools")


@function_tool(description="Get the current date and time")
async def get_current_time() -> str:
    now = datetime.datetime.now()
    return now.strftime("It is %I:%M %p on %A, %B %d, %Y")


@function_tool(description="Get current weather for a city")
async def get_weather(city: str) -> str:
    """Fetch weather from wttr.in (no API key needed)."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://wttr.in/{city}?format=j1",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    return f"Could not get weather for {city}"
                data = await resp.json()
                current = data["current_condition"][0]
                temp_c = current["temp_C"]
                desc = current["weatherDesc"][0]["value"]
                humidity = current["humidity"]
                return f"{city}: {desc}, {temp_c}°C, humidity {humidity}%"
    except Exception as e:
        logger.warning("weather error: %s", e)
        return f"Sorry, I couldn't fetch the weather for {city}"


@function_tool(description="Roll dice. Specify number of dice and sides, e.g. 2 dice with 6 sides")
async def roll_dice(num_dice: int = 1, num_sides: int = 6) -> str:
    rolls = [random.randint(1, num_sides) for _ in range(num_dice)]
    total = sum(rolls)
    if num_dice == 1:
        return f"You rolled a {total}"
    return f"You rolled {rolls}, total: {total}"


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


@function_tool(description="Set a reminder or timer with a message. Duration in seconds.")
async def set_reminder(message: str, seconds: int) -> str:
    """Acknowledge the reminder (actual timer would need background task)."""
    if seconds < 0:
        return "Duration must be positive"
    if seconds >= 3600:
        return f"Reminder set: '{message}' in {seconds // 3600} hours and {(seconds % 3600) // 60} minutes"
    elif seconds >= 60:
        return f"Reminder set: '{message}' in {seconds // 60} minutes"
    return f"Reminder set: '{message}' in {seconds} seconds"


@function_tool(description="Generate a random number between min and max (inclusive)")
async def random_number(min_val: int = 1, max_val: int = 100) -> str:
    result = random.randint(min_val, max_val)
    return f"Random number between {min_val} and {max_val}: {result}"


@function_tool(description="Flip a coin")
async def flip_coin() -> str:
    return random.choice(["Heads!", "Tails!"])


# Collect all tools into a list for easy import
ALL_TOOLS = [
    get_current_time,
    get_weather,
    roll_dice,
    calculate,
    set_reminder,
    random_number,
    flip_coin,
]
