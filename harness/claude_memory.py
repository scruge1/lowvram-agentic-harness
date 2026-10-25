"""Use a home-owned, explicitly local Claude-mem worker without global hooks."""
from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
import hmac
import http.client
import json
import os
from pathlib import Path
import platform
import re
import select
import signal
import socket
import stat
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from harness.home import HomeError, check_package, environment, load
from harness import home_entry, model_service, model_service_handoff


# Requiring the exported class avoids upstream CLI daemon spawning and port
# reclamation. The stable home entry execs Bun while retaining its shared lease.
FOREGROUND = "Promise.resolve().then(()=>new (require(process.argv[1]).WorkerService)().start()).catch(()=>{console.error('Claude-mem foreground startup failed');process.exit(1)})"
START_SECONDS = 45
DRAIN_SECONDS = 30
CHILDREN = {}  # Reaping only; native worker.pid remains the upstream identity.


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
    env.pop("CLAUDE_MEM_MANAGED", None)  # Would auto-run the imported module CLI.
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
    for key in ("bun", "claude-mem"):
        record = config["installed"].get(key)
        if not record or check_package(home, key, record):
            raise HomeError("Install and verify this home's exact Bun/Claude-mem packages before use.")
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


@contextmanager
def operation(root):
    """Serialize our startup/delivery/drain/stop operations, never another store."""
    import fcntl
    if root.resolve() != root or root.is_symlink():
        raise HomeError("Observer data directory is redirected.")
    descriptor = os.open(root / "agent-home-operation.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise HomeError("Observer operation lock ownership differs.")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def worker_proof(home, root, config, bun, worker, observed, *, require_lease=False, require_listener=True):
    """Bind the actual source process and kernel listener before any request."""
    pid = observed["pid"]
    process = model_service._process(pid)
    if (process is None or process["uid"] != os.getuid() or process["cwd"] != str(root)
            or process["exe"] != str(bun) or str(worker) not in process["argv"]
            or (require_listener and not model_service._listener(pid, config["claude_memory_port"]))):
        raise HomeError("Observer process/source/listener ownership differs; no request or signal was sent.")
    identity = json.loads((root / "worker.pid").read_text())
    values = (Path("/proc") / str(pid) / "environ").read_bytes().split(b"\0")
    if (identity.get("pid") != pid or identity.get("port") != config["claude_memory_port"]
            or os.fsencode("CLAUDE_MEM_DATA_DIR=" + str(root)) not in values
            or os.fsencode("CLAUDE_MEM_WORKER_PORT=" + str(config["claude_memory_port"])) not in values):
        raise HomeError("Observer PID/data-root/port binding changed.")
    if require_lease:
        lease = model_service_handoff._home_lease({"home": str(home)}, pid)
        if lease.get("lease_scope") != "home_shared":
            raise HomeError("Capture requires the foreground worker's actual home READ lease; stop and restart it explicitly.")
    return {"pid": pid, "process": process, "port": config["claude_memory_port"], "listener_required": require_listener}


def recheck(proof):
    if (model_service._process(proof["pid"]) != proof["process"]
            or (proof["listener_required"] and not model_service._listener(proof["pid"], proof["port"]))):
        raise HomeError("Observer lifetime/listener changed; delivery is held without replay.")


def live_pid(root):
    path = root / "worker.pid"
    if not path.exists():
        return None
    if path.is_symlink():
        raise HomeError("Observer PID file is redirected.")
    pid = json.loads(path.read_text()).get("pid")
    return pid if type(pid) is int and pid > 1 and model_service._process(pid) is not None else None


def request(proof, route, payload=None, *, timeout=10):
    """Native loopback HTTP only: no proxy, redirect, CLI fallback or respawn."""
    connection = http.client.HTTPConnection("127.0.0.1", proof["port"], timeout=timeout)
    try:
        connection.connect()
        recheck(proof)  # Check after connect, before sending a capture body.
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        if body is not None and len(body) > 2 * 1024 * 1024:
            raise HomeError("Capture request exceeds2MiB; original native history is retained.")
        connection.request("GET" if body is None else "POST", route, body=body,
                           headers={"Content-Type": "application/json"} if body is not None else {})
        response = connection.getresponse()
        raw = response.read(2 * 1024 * 1024 + 1)
        if response.status != 200 or len(raw) > 2 * 1024 * 1024:
            raise HomeError("Observer HTTP request failed or exceeded its bound; inspect retained state, never replay automatically.")
        value = json.loads(raw)
        if not isinstance(value, dict) or "error" in value or value.get("stored") is False:
            raise HomeError("Observer returned an error payload; capture was not accepted.")
        recheck(proof)
        return value
    finally:
        connection.close()


def foreground_start(home, root, config, bun, worker, env):
    # A failed health check does not prove an absent process. Do not respawn a
    # live unhealthy worker, or let the upstream CLI reclaim an occupied port.
    if live_pid(root) is not None:
        raise HomeError("An observer process remains alive without healthy ownership; inspect it before recovery.")
    native = model_service._pidfd()
    native.require_support()
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", config["claude_memory_port"]))
        except OSError as error:
            raise HomeError("Selected memory port is occupied; no worker was attached, reclaimed or stopped.") from error
    command = home_entry.guarded_command(home, [str(bun), "--eval", FOREGROUND, str(worker)])
    with home_entry.consumer(home), (root / "foreground.log").open("ab") as log:
        child = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=log, start_new_session=True)
        CHILDREN[child.pid] = child
        descriptor = None
        try:
            descriptor = native.pidfd_open(child.pid, 0)
            deadline = time.monotonic() + START_SECONDS
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise HomeError("Foreground worker exited during startup; inspect its owned log before recovery.")
                observed = health(home, root, config, worker, expected_api_key=env["CLAUDE_MEM_OPENAI_COMPAT_API_KEY"])
                if observed is not None:
                    if observed["pid"] != child.pid:
                        raise HomeError("Another process answered during foreground startup; no worker was adopted.")
                    proof = worker_proof(home, root, config, bun, worker, observed, require_lease=True)
                    try:
                        request(proof, "/api/readiness", timeout=2)
                        return observed
                    except (OSError, ValueError, http.client.HTTPException):
                        pass  # Native background initialization can still be pending.
                time.sleep(0.1)
            raise HomeError("Foreground startup deadline; no capture was dispatched.")
        except BaseException:
            if child.poll() is None:
                if descriptor is None:
                    raise HomeError("Foreground PIDFD acquisition failed; settlement is unknown. Inspect owned status before recovery.")
                try:
                    native.pidfd_send_signal(descriptor, signal.SIGTERM)
                    child.wait(timeout=15)
                except (OSError, subprocess.TimeoutExpired) as error:
                    raise HomeError("Owned foreground startup cleanup is unsettled; inspect the retained worker before recovery.") from error
            CHILDREN.pop(child.pid, None)
            raise
        finally:
            if descriptor is not None:
                os.close(descriptor)


def stop_worker(proof):
    """A stale model nonce cannot prevent stopping this exact owned process."""
    native = model_service._pidfd()
    descriptor = native.pidfd_open(proof["pid"], 0)
    try:
        recheck(proof)
        native.pidfd_send_signal(descriptor, signal.SIGTERM)
        stopped = bool(select.select([descriptor], [], [], 15)[0])
    finally:
        os.close(descriptor)
    child = CHILDREN.get(proof["pid"])
    if stopped and child is not None:
        child.wait(timeout=1)
        CHILDREN.pop(proof["pid"], None)
    return {"status": "stopped" if stopped else "stop_unconfirmed",
            **({} if stopped else {"pending_capture": "not_discarded; inspect native queue before explicit recovery"})}


def drain(home, root, config, worker, proof):
    deadline = time.monotonic() + DRAIN_SECONDS
    while True:
        value = request(proof, "/api/processing-status", timeout=min(3, max(0.1, deadline - time.monotonic())))
        if (type(value.get("isProcessing")) is not bool
                or any(type(value.get(key)) is not int or value[key] < 0 for key in ("queueDepth", "parkedSessions"))):
            raise HomeError("Unknown processing status; no drain completion was inferred.")
        observed = health(home, root, config, worker)
        if observed is None or observed["pid"] != proof["pid"]:
            raise HomeError("Observer lost liveness while draining; pending capture remains unproved.")
        last = observed.get("ai", {}).get("lastInteraction")
        if isinstance(last, dict) and last.get("success") is False:
            return {"status": "failed", "processing": value, "lastInteraction": last, "generation_acceptance": "not_established"}
        if not value["isProcessing"] and value["queueDepth"] == 0 and value["parkedSessions"] == 0:
            return {"status": "drained", "processing": value, "generation_acceptance": "not_established"}
        if time.monotonic() >= deadline:
            return {"status": "pending", "timed_out": True, "processing": value, "generation_acceptance": "not_established"}
        time.sleep(0.1)


def invoke(home, action, payload=None, event=None):
    if action == "hook":
        if event not in {"session-init", "observation", "summarize"}:
            raise HomeError("Only the three installed Pi capture events have a qualified normalized HTTP route.")
        if (not isinstance(payload, dict) or not isinstance(payload.get("sessionId"), str)
                or not payload["sessionId"] or len(payload["sessionId"]) > 512):
            raise HomeError("Hook requires a normalized native session identity.")
        if event == "observation" and (not isinstance(payload.get("toolName"), str) or not payload["toolName"]):
            raise HomeError("Observation requires its native tool name.")
        if len(json.dumps(payload).encode("utf-8")) > 2 * 1024 * 1024:
            raise HomeError("Capture input exceeds2MiB; original native history is retained.")
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
    with operation(root) if action in {"start", "hook", "stop", "drain"} else nullcontext():
        return dispatch(home, root, config, bun, worker, env, expected_key, action, payload, event)


def dispatch(home, root, config, bun, worker, env, expected_key, action, payload, event):
    owned = "owned_model_service" in config
    observed = health(home, root, config, worker, expected_api_key=expected_key)
    alive = live_pid(root) if observed is None else None
    if action == "status":
        if observed is not None:
            worker_proof(home, root, config, bun, worker, observed)
        result = {"status": "running" if observed else "unhealthy" if alive else "stopped", "health": observed,
                  "scope": "owned worker health, not capture freshness or memory quality"}
        if owned:
            result.update(authentication="not_checked", capture_ready=False)
        return result
    if owned and action == "search" and observed is None:
        return {"status": "held", "results": [], "abstained": True,
                "reason": "owned_observer_unhealthy" if alive else "owned_observer_stopped", "authority": "retrieval_only",
                "authentication": "not_checked", "capture_ready": False}
    if action in {"start", "hook"} and observed is None:
        observed = foreground_start(home, root, config, bun, worker, env)
    if observed is None:
        if alive and action == "stop":
            return stop_worker(worker_proof(home, root, config, bun, worker, {"pid": alive}, require_listener=False))
        if alive:
            raise HomeError("Observer process remains alive but unhealthy; no stopped state or automatic respawn was inferred.")
        if action == "stop":
            return {"status": "stopped", "effect": "none"}
        return {"status": "held", "reason": "observer_stopped", "capture_completion": "unknown"}
    proof = worker_proof(home, root, config, bun, worker, observed, require_lease=action in {"start", "hook"})
    if action == "start":
        return {"status": "running", "health": observed, "acceptance": "health_only"}
    if action == "search":
        params = urlencode({"query": event, "format": "json", "type": "observations", "limit": 5})
        value = request(proof, "/api/search?" + params, timeout=15)
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
        return stop_worker(proof)
    if action == "drain":
        return drain(home, root, config, worker, proof)
    if action == "hook":
        content = {"contentSessionId": payload["sessionId"], "platformSource": "raw", "cwd": payload.get("cwd", str(home))}
        if event == "session-init":
            content["prompt"] = payload.get("prompt", "")
            route = "/api/sessions/init"
        elif event == "observation":
            content.update(tool_name=payload["toolName"], tool_input=payload.get("toolInput"), tool_response=payload.get("toolResponse"))
            if "toolUseId" in payload:
                content["tool_use_id"] = payload["toolUseId"]
            route = "/api/sessions/observations"
        else:
            content["last_assistant_message"] = payload.get("last_assistant_message", "")
            route = "/api/sessions/summarize"
        value = request(proof, route, content)
        if event == "session-init":
            accepted = (type(value.get("sessionDbId")) is int and type(value.get("promptNumber")) is int
                        or value.get("skipped") is True and isinstance(value.get("reason"), str))
        else:
            accepted = value.get("status") == "queued" or (value.get("status") == "skipped" and isinstance(value.get("reason"), str))
        if not accepted:
            raise HomeError("Unknown native capture acknowledgement; delivery/generation was not inferred.")
        return {"status": "hook_delivered", "event": event, "response": value,
                "scope": "native HTTP acceptance/enqueue only; not generated observation, drain or semantic acceptance"}
    raise HomeError("Unknown memory operation.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("action", choices=("start", "stop", "status", "hook", "search", "drain"))
    parser.add_argument("event", nargs="?")
    args = parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin) if args.action == "hook" else None
        result = invoke(args.home, args.action, payload, args.event)
        print(json.dumps(result))
        if args.action == "drain":
            return 0 if result.get("status") == "drained" else 1
        return 1 if result.get("status") == "stop_unconfirmed" else 0
    except (OSError, ValueError, HomeError, http.client.HTTPException) as error:
        print(json.dumps({"status": "failed", "error": str(error), "authority": "none"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
