"""Use a home-owned, explicitly local Claude-mem worker without global hooks."""
from __future__ import annotations

import argparse
import hmac
import json
import os
from pathlib import Path
import platform
import re
import socket
import sys
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from harness.home import HomeError, environment, load, run


def settings(home, config):
    """Validate persisted nonsecret settings without resolving service credentials."""
    root = home / "memory/claude-mem"
    value = json.loads((root / "settings.json").read_text(encoding="utf-8"))
    required = {
        "CLAUDE_MEM_DATA_DIR": str(root), "CLAUDE_MEM_PROVIDER": "openai-compatible",
        "CLAUDE_MEM_OPENAI_COMPAT_PRESET": "custom",
        "CLAUDE_MEM_OPENAI_COMPAT_BASE_URL": config["base_url"],
        "CLAUDE_MEM_OPENAI_COMPAT_MODEL": config["model"],
        "CLAUDE_MEM_OPENAI_COMPAT_API_KEY": "local", "CLAUDE_MEM_OPENAI_COMPAT_API_KEYS": "",
        "CLAUDE_MEM_QUOTA_FALLBACK_PROVIDER": "", "CLAUDE_MEM_QUOTA_FALLBACK_MODEL": "",
        "CLAUDE_MEM_CLOUD_SYNC_TOKEN": "", "CLAUDE_MEM_ONLINE_OPTIN": "false",
        "CLAUDE_MEM_CHROMA_ENABLED": "false", "CLAUDE_MEM_TRANSCRIPTS_ENABLED": "false",
        "CLAUDE_MEM_WORKER_HOST": "127.0.0.1", "CLAUDE_MEM_WORKER_PORT": str(config["claude_memory_port"]),
        "CLAUDE_MEM_REDACT_ENABLED": "true",
    }
    if "owned_model_service" in config:
        # Accept the existing scaffold placeholder or an empty key. Neither is
        # an effective credential for the authenticated observer child.
        placeholder = value.get("CLAUDE_MEM_OPENAI_COMPAT_API_KEY")
        if not isinstance(placeholder, str) or placeholder not in {"", "local"}:
            raise HomeError("Keep owned observer credentials out of persisted settings.")
        required["CLAUDE_MEM_OPENAI_COMPAT_API_KEY"] = placeholder
    if any(str(value.get(key)) != expected for key, expected in required.items()):
        raise HomeError("Claude-mem local-provider/ownership configuration changed; hold capture before dispatch.")
    return root, required


def child_environment(home, config, required, *, resolve_owned=True):
    """Build an effective child environment. Never print or persist this result."""
    env = environment(home)
    env.update(required)
    env.update({"CLAUDE_MEM_TELEMETRY": "0", "CLAUDE_MEM_TELEMETRY_ERRORS": "0", "DO_NOT_TRACK": "1"})
    if "owned_model_service" in config and resolve_owned:
        from harness import model_service_handoff
        binding = config["owned_model_service"]
        route = model_service_handoff._binding(binding)
        expected = {"home": str(home), "base_url": config["base_url"], "model_id": config["model"],
                    "context": config["context_window"], "max_output": config["max_output"],
                    "transport_profile": config["model_profile"]}
        if any(route.get(key) != value for key, value in expected.items()):
            raise HomeError("Owned observer route differs from its selected home configuration.")
        launched = model_service_handoff.launch_environment(home, binding)
        env = launched.apply(env)
        key = env.get(binding["environment_variable"])
        if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{64}", key):
            raise HomeError("Owned observer did not receive a valid current service credential.")
        env["CLAUDE_MEM_OPENAI_COMPAT_API_KEY"] = key
    return env


def worker_paths(home):
    base = home / "packages/bun/node_modules"
    _, config = load(home)
    package = config["installed"].get("bun", {}).get("npm_name") or "bun"
    manifest = json.loads((base / package / "package.json").read_text(encoding="utf-8"))
    command = "bin/bun" if package.startswith("@oven/bun-linux-") else manifest["bin"]["bun"] if isinstance(manifest["bin"], dict) else manifest["bin"]
    bun = (base / package / command).resolve(strict=True)
    if not bun.is_relative_to(base.resolve()) or not bun.is_file():
        raise HomeError("Bun executable escaped its home-owned package.")
    worker = home / "packages/claude-mem/node_modules/claude-mem/plugin/scripts/worker-service.cjs"
    if not worker.is_file():
        raise HomeError("Claude-mem worker assets are not installed.")
    return bun, worker.resolve()


def health(home, root, config, worker, *, expected_api_key=None):
    """A responding port is insufficient: bind process, source and data root."""
    port = config["claude_memory_port"]
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise HomeError("Worker health response exceeds its limit.")
        observed = json.loads(raw)
    except (URLError, TimeoutError, ConnectionError):
        return None
    pid_file = root / "worker.pid"
    if not pid_file.is_file() or pid_file.is_symlink():
        raise HomeError("Port responds without this home's owned worker identity.")
    identity = json.loads(pid_file.read_text(encoding="utf-8"))
    pid = identity.get("pid")
    if type(pid) is not int or pid <= 1 or identity.get("port") != port or observed.get("pid") != pid:
        raise HomeError("Worker process/port identity mismatch.")
    if observed.get("version") != "13.29.0" or Path(observed.get("workerPath", "")).resolve() != worker:
        raise HomeError("Worker version or loaded package path mismatch.")
    if observed.get("ai", {}).get("provider") != "openai-compatible":
        raise HomeError("Worker did not select the configured local-compatible provider; capture is held.")
    proc = Path("/proc") / str(pid)
    before = (proc / "stat").read_bytes()
    if (proc / "cwd").resolve(strict=True) != root.resolve():
        raise HomeError("Worker belongs to another data directory.")
    values = (proc / "environ").read_bytes().split(b"\0")
    expected = os.fsencode("CLAUDE_MEM_DATA_DIR=" + str(root))
    if expected not in values:
        raise HomeError("Worker data-directory environment differs.")
    after = (proc / "stat").read_bytes()
    # Start time is field22 after the parenthesized command, whose text can contain spaces.
    if before.rsplit(b")", 1)[1].split()[19] != after.rsplit(b")", 1)[1].split()[19]:
        raise HomeError("Worker lifetime changed during observation.")
    if expected_api_key is not None:
        prefix = b"CLAUDE_MEM_OPENAI_COMPAT_API_KEY="
        keys = [value[len(prefix):] for value in values if value.startswith(prefix)]
        if len(keys) != 1 or not hmac.compare_digest(keys[0], os.fsencode(expected_api_key)):
            raise HomeError("Owned observer credential is stale; stop this exact worker before restarting. No capture was dispatched.")
    return observed


def invoke(home, action, payload=None, event=None):
    home, config = load(home)
    if platform.system() != "Linux":
        raise HomeError("This worker ownership adapter requires Linux.")
    if action == "search":
        if not isinstance(event, str) or not event.strip() or len(event) > 1000:
            raise HomeError("Search requires a nonempty query of at most 1000 characters.")
        if re.search(r"\b(plaintext|password|passcode|access[ -]?code|api[ -]?key|secret|token|credential)\b", event, re.I):
            return {"results": [], "abstained": True, "reason": "sensitive_query", "authority": "retrieval_only"}
    root, required = settings(home, config)
    bun, worker = worker_paths(home)
    # Inspection, existing keyword recall and exact stop do not need inference.
    # Only starting/adopting a capture worker or sending a hook needs fresh auth.
    owned = "owned_model_service" in config
    requires_auth = owned and action in {"start", "hook"}
    env = child_environment(home, config, required, resolve_owned=requires_auth)
    expected_key = env["CLAUDE_MEM_OPENAI_COMPAT_API_KEY"] if requires_auth else None
    observed = health(home, root, config, worker, expected_api_key=expected_key)
    if action == "status":
        result = {"status": "running" if observed else "stopped", "health": observed,
                  "scope": "owned worker health, not capture freshness or memory quality"}
        if owned:
            result.update(authentication="not_checked", capture_ready=False)
        return result
    if owned and action == "search" and observed is None:
        return {"status": "held", "results": [], "abstained": True,
                "reason": "owned_observer_stopped", "authority": "retrieval_only",
                "authentication": "not_checked", "capture_ready": False}
    if action in {"start", "hook", "search"} and observed is None:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", config["claude_memory_port"]))
            except OSError as error:
                raise HomeError("Selected memory port is occupied; do not attach or stop another worker.") from error
        run([bun, worker, "start"], cwd=home, env=env, timeout=45)
        observed = health(home, root, config, worker, expected_api_key=expected_key)
        if observed is None:
            raise HomeError("Worker start returned without owned health. Inspect logs before retry.")
    if action == "start":
        return {"status": "running", "health": observed, "acceptance": "health_only"}
    if action == "search":
        params = urlencode({"query": event, "format": "json", "type": "observations", "limit": 5})
        with urlopen(f"http://127.0.0.1:{config['claude_memory_port']}/api/search?{params}", timeout=15) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise HomeError("Memory search exceeds its delivery bound; no partial body is accepted.")
        value = json.loads(raw)
        results = value.get("observations")
        if not isinstance(results, list) or len(results) > 5 or any(not isinstance(row, dict) or type(row.get("id")) is not int for row in results):
            raise HomeError("Memory search returned an invalid source identity.")
        result = {"results": results, "returned_count": len(results), "corpus_match_total": "unknown",
                  "mode": "sqlite_fts_keyword", "upstream_body_truncation": "not_reported",
                  "transport_truncated": False, "source": str(root / "claude-mem.db"),
                  "authority": "retrieval_only"}
        if owned:
            result.update(authentication="not_checked", capture_ready=False)
        return result
    if action == "stop":
        if observed is None:
            return {"status": "stopped", "effect": "none"}
        run([bun, worker, "stop"], cwd=home, env=env, timeout=30)
        return {"status": "stopped" if health(home, root, config, worker) is None else "stop_unconfirmed"}
    if action == "hook":
        if event not in {"context", "session-init", "observation", "summarize", "user-message"}:
            raise HomeError("Unknown raw Claude-mem hook event.")
        if not isinstance(payload, dict) or not isinstance(payload.get("sessionId"), str):
            raise HomeError("Hook requires a normalized native session identity.")
        output = run([bun, worker, "hook", "raw", event], cwd=home, env=env,
                     input=json.dumps(payload), timeout=45)
        return {"status": "hook_completed", "event": event, "output": output[-4000:],
                "scope": "capture delivery only, not semantic acceptance"}
    raise HomeError("Unknown memory operation.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("action", choices=("start", "stop", "status", "hook", "search"))
    parser.add_argument("event", nargs="?")
    args = parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin) if args.action == "hook" else None
        print(json.dumps(invoke(args.home, args.action, payload, args.event)))
        return 0
    except (OSError, ValueError, HomeError) as error:
        print(json.dumps({"status": "failed", "error": str(error), "authority": "none"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
