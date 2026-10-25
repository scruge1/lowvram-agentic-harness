"""Explicit native Pi transport settings, separate from model quality or fit.

The Qwen profile reuses Pi1.4's native qwen-chat-template format. Declaring
thinking off cannot control that server template through a generic model entry.
Do not select this profile solely from a model name or use it for Ollama.
"""
from __future__ import annotations

from copy import deepcopy


PROFILES = {
    "generic-local": {
        "description": "Generic local OpenAI-compatible model; thinking control is not qualified.",
        "fields": {},
    },
    "llama-cpp-qwen": {
        "description": "Qwen served by llama.cpp with native chat_template_kwargs thinking control.",
        "fields": {"reasoning": True,
                   "compat": {"thinkingFormat": "qwen-chat-template", "supportsReasoningEffort": True}},
    },
}


def model_definition(model, context_window, max_output, profile="generic-local"):
    if profile not in PROFILES:
        raise ValueError("Unknown model transport profile: " + str(profile))
    result = {"id": model, "input": ["text"], "contextWindow": context_window, "maxTokens": max_output}
    result.update(deepcopy(PROFILES[profile]["fields"]))
    return result
