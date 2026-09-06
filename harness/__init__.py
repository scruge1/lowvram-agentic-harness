"""lowvram-agentic-harness: a small, domain-agnostic verify-retry-research harness
for a locally hosted LLM. See README.md."""
from .llm import LocalLLM, load_config          # noqa: F401
from . import verify, paired_gate, dispatch_retry, research_ground  # noqa: F401

__all__ = ["LocalLLM", "load_config", "verify", "paired_gate",
           "dispatch_retry", "research_ground"]
