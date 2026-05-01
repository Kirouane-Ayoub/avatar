"""Chat LLM client + system prompt assembly.

Two concerns: how we talk to the LLM (client.py) and what we send it
(prompt.py). Co-located because they evolve together — adding a new
prompt feature usually touches the model config too, and vice versa.
"""

from .client import (  # noqa: F401
    PatientLLM,
    build_chat_llm,
)
from .prompt import (  # noqa: F401
    ORPHEUS_EMOTION_TAGS,
    build_system_prompt,
    memory_block,
)
