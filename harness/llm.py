#!/usr/bin/env python3
"""llm.py — the local-model client the whole harness talks through.

One thin adapter over an OpenAI-compatible chat endpoint. That is the wire
format llama.cpp's own `llama-server`, llama-swap, LM Studio, vLLM and Ollama
(`/v1`) all speak, so pointing `base_url` at any of them Just Works — the harness
never assumes a specific engine, only the `/v1/chat/completions` contract.

Config precedence (highest first): environment variables -> config.yaml ->
built-in defaults. So a friend can drop a config file OR just export two env vars.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULTS = {
    "base_url": "http://localhost:8080/v1",   # llama-server default port
    "model": "local-model",                   # llama.cpp ignores this; llama-swap routes on it
    "api_key": "not-needed",                  # local servers ignore it; some clients require a value
    "temperature": 0.2,
    "max_tokens": 1024,
    "timeout_s": 240,
}

_ENV_MAP = {
    "base_url": "HARNESS_BASE_URL",
    "model": "HARNESS_MODEL",
    "api_key": "HARNESS_API_KEY",
}


def load_config(path=None) -> dict:
    """Merge defaults <- YAML file <- environment. Never raises on a missing file."""
    cfg = dict(DEFAULTS)
    p = Path(path) if path else None
    if p and p.exists():
        cfg.update(_read_yaml(p).get("model", {}) or {})
    for key, env in _ENV_MAP.items():
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    return cfg


def _read_yaml(p: Path) -> dict:
    """Load YAML if PyYAML is present; else a tiny flat-ish fallback so a
    zero-dependency install still boots. The example config is deliberately simple
    enough for the fallback to parse."""
    text = p.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        return _mini_yaml(text)


def _mini_yaml(text: str) -> dict:
    """Minimal 2-level YAML: top-level `key:` sections with 2-space-indented
    `key: value` children. Enough for config.example.yaml, not a general parser."""
    root: dict = {}
    section = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw.startswith(" "):
            key = raw.split(":", 1)[0].strip()
            root[key] = {}
            section = root[key]
        elif section is not None and ":" in raw:
            k, v = raw.strip().split(":", 1)
            section[k.strip()] = _coerce(v.strip())
    return root


def _coerce(v: str):
    v = v.strip().strip('"').strip("'")
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


class LocalLLM:
    """A local chat model reached over the OpenAI-compatible `/v1/chat/completions`
    endpoint. `chat()` returns the assistant text, or raises RuntimeError with a
    plain-language reason (an unreachable model is never a silent empty string)."""

    def __init__(self, config: dict | None = None):
        self.cfg = config or load_config()

    def chat(self, messages, temperature=None, max_tokens=None) -> str:
        url = self.cfg["base_url"].rstrip("/") + "/chat/completions"
        body = {
            "model": self.cfg["model"],
            "messages": messages,
            "temperature": self.cfg["temperature"] if temperature is None else temperature,
            "max_tokens": self.cfg["max_tokens"] if max_tokens is None else max_tokens,
            "stream": False,
        }
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.cfg['api_key']}"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.cfg["timeout_s"]) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"local model unreachable at {url} ({e}). Is the server running? "
                f"See SETUP.md / FAQ.md.") from e
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"unexpected response shape from {url}: {data}") from e

    def ask(self, prompt: str, system: str | None = None, **kw) -> str:
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
        return self.chat(msgs, **kw)


def _selftest() -> int:
    cfg = load_config()
    assert cfg["base_url"].endswith("/v1"), cfg
    assert _coerce("0.2") == 0.2 and _coerce("true") is True and _coerce("7") == 7
    mini = _mini_yaml("model:\n  base_url: http://x:1/v1\n  max_tokens: 32\n")
    assert mini["model"]["base_url"] == "http://x:1/v1" and mini["model"]["max_tokens"] == 32
    print("llm selftest OK (config merge + mini-yaml + coerce)")
    return 0


if __name__ == "__main__":
    sys.exit(_selftest())
