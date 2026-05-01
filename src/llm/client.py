"""Chat LLM client + factory.

Lifted out of agent.py so the customization is grep-able and the
entrypoint stays focused on session orchestration.

Why PatientLLM: the 27B (or any sizable) chat model can take 5-15 s
TTFT on M4 Pro for a vision turn. LiveKit's default
APIConnectOptions.timeout is 10 s, which fires retries before the
model even starts streaming — those retries queue more requests on
the serial mlx-vlm server and spiral. PatientLLM overrides the
per-call conn_options with a 60 s timeout to give the model room to
breathe.

The vanilla `openai.LLM(timeout=...)` kwarg only sets the openai-
python httpx timeout — it does NOT touch livekit's retry layer.
Different layer, different config.
"""

from __future__ import annotations

from livekit.agents import APIConnectOptions
from livekit.plugins import openai

from config import Config


class PatientLLM(openai.LLM):
    """openai.LLM with a wider per-call APIConnectOptions.timeout."""

    _PATIENT_CONN = APIConnectOptions(max_retry=3, retry_interval=2.0, timeout=60.0)

    def chat(self, *args, **kwargs):
        kwargs.setdefault("conn_options", self._PATIENT_CONN)
        return super().chat(*args, **kwargs)


def build_chat_llm(config: Config) -> PatientLLM:
    """Construct the chat LLM client from Config. Centralizes the
    constructor args + the `enable_thinking: false` extra_body that
    Qwen models need to disable chain-of-thought reasoning (critical
    for voice — without it the model generates endless thinking
    tokens before any actual reply).
    """
    return PatientLLM(
        base_url=config.llm_base_url,
        api_key=config.llm_api_key,
        model=config.llm_model,
        extra_body={
            "think": False,
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )
