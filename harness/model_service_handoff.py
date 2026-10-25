"""Read-only, explicit attachment of an owned native service to Pi1.4.

Pi models.json uses "$NAME" interpolation for API keys. The runtime nonce is
injected into the child environment, never a literal key or shell resolver in
models.json. Endpoint changes require an explicit rebind with Pi stopped.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from . import home_entry, model_profiles, model_service


SCHEMA = "local-model-service-handoff/v1"
FIELDS = ("home", "storage_root", "specification_sha256", "base_url", "model_id", "context", "max_output", "transport_profile")
LIFETIME = ("pid", "start_ticks", "api_key_file", *FIELDS)


class HandoffError(ValueError):
    pass


def require(value, message):
    if not value:
        raise HandoffError(message)


def _route(value):
    require(isinstance(value, dict), "An explicit owned service binding is required")
    require(all(key in value for key in FIELDS), "Owned service binding is incomplete")
    parsed = urlsplit(value["base_url"])
    require(parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and parsed.path == "/v1"
            and parsed.port is not None and 1024 <= parsed.port <= 65535
            and parsed.username is None and parsed.password is None and not parsed.query and not parsed.fragment,
            "Owned service must use its exact loopback endpoint")
    require(isinstance(value["specification_sha256"], str) and re.fullmatch(r"[a-f0-9]{64}", value["specification_sha256"]),
            "Owned service source selection is missing")
    require(type(value["context"]) is int and type(value["max_output"]) is int
            and 0 < value["max_output"] < value["context"], "Owned service context/output binding differs")
    for key in ("home", "storage_root"):
        require(isinstance(value[key], str) and Path(value[key]).is_absolute()
                and Path(value[key]).resolve() == Path(value[key]), "Owned service path binding differs")
    result = {key: value[key] for key in FIELDS}
    result["transport_profile"] = "generic-local" if result["transport_profile"] == "generic" else result["transport_profile"]
    require(result["transport_profile"] in model_profiles.PROFILES, "Unknown explicit transport profile")
    require(isinstance(result["model_id"], str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}", result["model_id"]), "Invalid owned model ID")
    return result


def _private_read(path, limit):
    require(path.is_absolute() and path.resolve() == path and not path.is_symlink(), "Private service source was redirected")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1,
                "Service source must be an owned single-link regular file")
        require(before.st_size <= limit, "Service source exceeds its read bound")
        raw = os.read(descriptor, limit + 1)
        after = os.fstat(descriptor)
        def identity(item):
            return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns
        require(len(raw) <= limit and identity(before) == identity(after) == identity(path.stat(follow_symlinks=False)),
                "Service source changed while reading")
        return raw, before
    finally:
        os.close(descriptor)


def _home_lease(route, pid):
    """Read the service child's own kernel lease, without acquiring one here."""
    home = Path(route["home"])
    if not home.exists():
        return {"lease_scope": "pre_home"}
    selected, config = home_entry.selected_home(home)
    pin = config.get("lifecycle_guard_sha256")
    require(isinstance(pin, str), "Installed home requires its lifecycle guard; stop the pre-home service before adoption")
    guard = home_entry._load_guard(selected, pin)
    guard.checked_home(selected, expected_sha256=pin)
    require(guard.pending(selected) is None, "Pending home activation blocks model handoff")
    lock = guard.child_path(selected, "state/home-lifecycle.lock", absent=True)
    require(lock.exists(), "Running service lacks its own home lifecycle READ lease; stop the pre-home service before adoption")
    named = lock.stat(follow_symlinks=False)
    process = Path("/proc") / str(pid)
    require(process.stat().st_uid == os.getuid(), "Owned service process user changed")
    for count, descriptor in enumerate((process / "fd").iterdir()):
        require(count <= 4096, "Owned service descriptors exceed their inspection bound")
        try:
            if os.readlink(descriptor) != str(lock):
                continue
            opened = descriptor.stat()
            if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
                continue
            lines = (process / "fdinfo" / descriptor.name).read_text().splitlines()
            shared = any(line.startswith("lock:") and "FLOCK ADVISORY READ" in " ".join(line.split()) for line in lines)
            if not shared:
                continue
            after = lock.stat(follow_symlinks=False)
            require((after.st_dev, after.st_ino) == (named.st_dev, named.st_ino), "Home lifecycle lock changed during handoff")
            return {"lease_scope": "home_shared", "home_guard_sha256": pin,
                    "home_lock_device": named.st_dev, "home_lock_inode": named.st_ino,
                    "home_lock_descriptor": int(descriptor.name), "home_lock_mode": "FLOCK ADVISORY READ"}
        except FileNotFoundError:
            continue
    raise HandoffError("Running service lacks its own home lifecycle READ lease; stop the pre-home service and restart after home creation")


def _snapshot(home):
    initial = model_service.status(home)
    require(initial.get("status") == "running", "The selected owned model service is not ready")
    route = _route(initial)
    root = model_service._home(home)
    require(str(root) == route["storage_root"] and model_service._bound_home(root) == route["home"], "Service belongs to another selected home")
    state_path = root / "state/model-service/service.json"
    state_raw, _ = _private_read(state_path, 1024 ** 2)
    state = json.loads(state_raw)
    require(isinstance(state, dict), "Invalid owned service state")
    expected = {"pid": initial["pid"], "start_ticks": initial["start_ticks"], "key_file": initial["api_key_file"],
                "home": route["home"], "storage_root": route["storage_root"], "specification_sha256": route["specification_sha256"],
                "model": route["model_id"], "port": urlsplit(route["base_url"]).port}
    require(all(state.get(key) == value for key, value in expected.items()), "Service route/state changed during handoff")
    key = Path(initial["api_key_file"])
    require(key.name == "api-key" and re.fullmatch(r"run-[a-f0-9]{32}", key.parent.name)
            and key.parent.parent == root / "state/model-service", "Private key does not belong to this service")
    raw, info = _private_read(key, 65)
    require(info.st_mode & 0o077 == 0 and re.fullmatch(rb"[a-f0-9]{64}\n", raw), "Service key must be a private native nonce file")
    nonce_sha = hashlib.sha256(raw).hexdigest()
    require(nonce_sha == state.get("nonce_sha256"), "Private key differs from its owned source binding")
    lease = _home_lease(route, initial["pid"])
    final = model_service.status(home)
    require(final.get("status") == "running" and all(final.get(key) == initial.get(key) for key in LIFETIME),
            "Service lifetime changed during handoff")
    final_state, _ = _private_read(state_path, 1024 ** 2)
    final_key, _ = _private_read(key, 65)
    require(final_state == state_raw and final_key == raw, "Service source changed during handoff")
    require(_home_lease(route, final["pid"]) == lease, "Service home lifecycle scope changed during handoff")
    receipt = {"service_pid": initial["pid"], "service_start_ticks": initial["start_ticks"],
               "service_state_sha256": hashlib.sha256(state_raw).hexdigest(), "nonce_sha256": nonce_sha,
               "api_key_file": str(key), **lease, "authority": "owned serving route only; no task or hardware-fit acceptance"}
    return route, raw.decode().strip(), receipt


def _variable(home):
    return "AGENT_HOME_MODEL_KEY_" + hashlib.sha256(home.encode()).hexdigest()[:16].upper()


def capture(home):
    """Return serializable factory inputs without a nonce or process action."""
    route, _key, receipt = _snapshot(home)
    name = _variable(route["home"])
    binding = {"schema": SCHEMA, **route, "environment_variable": name}
    provider = {"baseUrl": route["base_url"], "api": "openai-completions", "apiKey": "$" + name,
                "models": [model_profiles.model_definition(route["model_id"], route["context"], route["max_output"], route["transport_profile"])]}
    return {"binding": binding, "provider": provider, "receipt": receipt}


def _binding(value):
    require(isinstance(value, dict) and value.get("schema") == SCHEMA, "Select an explicit stored service binding")
    route = _route(value)
    require(value.get("environment_variable") == _variable(route["home"]), "Owned service environment binding differs")
    return route


@dataclass(frozen=True)
class LaunchEnvironment:
    updates: dict = field(repr=False)
    receipt: dict

    def apply(self, base):
        """Apply to the managed child's environment. Never log this result."""
        result = dict(base)
        require(result.get("HOME", str(Path.home())) == str(Path.home()), "Preserve the operating-system HOME")
        result["HOME"] = str(Path.home())
        result.update(self.updates)
        return result


def launch_environment(home, binding):
    """Read the current nonce only after its running route matches the binding.

    Nonce rotation at the same owned endpoint is allowed. A different port,
    source selection, model, context or transport profile requires rebind.
    """
    expected = _binding(binding)
    current, key, receipt = _snapshot(home)
    require(current == expected, "Owned model service endpoint or source selection changed; explicitly rebind while Pi is stopped")
    return LaunchEnvironment({_variable(current["home"]): key}, receipt)


def restart_options(binding):
    """A caller may explicitly retain this port; no start or takeover occurs."""
    route = _binding(binding)
    return {"port": urlsplit(route["base_url"]).port}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--home", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(capture(args.home), indent=2))
        return 0
    except (OSError, ValueError) as error:
        print(json.dumps({"schema": SCHEMA, "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
