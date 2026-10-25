"""Read-only first-run inventory and bounded local model-service discovery.

Reuse hardware_probe and the managed home's endpoint policy. Model listings
are discovery evidence, never proof of tool capability, local inference or fit.
No model is loaded, downloaded, selected or invoked by this module.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import hardware_probe


DEFAULT_LOCAL_SERVICES = (
    "http://127.0.0.1:8080/v1",  # Existing harness/llm.py default, llama.cpp.
    "http://127.0.0.1:11434/v1",  # Ollama local OpenAI-compatible API.
    "http://127.0.0.1:1234/v1",  # LM Studio local OpenAI-compatible API.
)
MAX_RESPONSE_BYTES = 256 * 1024
MAX_MODELS = 64


class OnboardingError(ValueError):
    pass


def _timeout(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OnboardingError("Use a finite timeout from 0.1 through 60 seconds.")
    if not math.isfinite(value) or not 0.1 <= value <= 60:
        raise OnboardingError("Use a finite timeout from 0.1 through 60 seconds.")
    return float(value)


def inventory(destination):
    """Observe this machine and the selected volume without creating a home."""
    requested = Path(destination).expanduser().absolute()
    existing = requested
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    if not existing.is_dir():
        raise OnboardingError("The selected destination must be a directory or a new child directory.")
    measured = existing.resolve(strict=True)
    space = shutil.disk_usage(measured)
    return {
        "schema": "agent-onboarding-inventory/v1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "system": {"platform": platform.system(), "machine": platform.machine(),
                   "python": platform.python_version()},
        "hardware": hardware_probe.summary(),
        "storage": {"destination": str(requested), "measured_existing_path": str(measured),
                    "total_bytes": space.total, "free_bytes": space.free},
        "changes": [],
        "qualification": "inventory_only",
        "limits": ["GPU facts retain hardware_probe's first-device scope; no GPU was selected.",
                   "No model download size, memory fit, context limit or tool capability is inferred.",
                   "Full managed execution currently requires Linux; other platforms need separate qualification."],
    }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _model_metadata(base_url, timeout):
    """Worker-side GET only; caller enforces the whole-operation deadline."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request(base_url + "/models", headers={"Accept": "application/json"})
    try:
        with opener.open(request, timeout=timeout) as response:
            content_type = response.headers.get_content_type()
            if content_type != "application/json" and not content_type.endswith("+json"):
                return {"status": "invalid_response", "reason": "Model listing is not JSON."}
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                return {"status": "response_too_large", "reason": "Model listing exceeds the byte limit."}
    except urllib.error.HTTPError as error:
        return {"status": "redirect_refused" if 300 <= error.code < 400 else "http_error",
                "http_status": error.code}
    except (OSError, ValueError) as error:
        return {"status": "unavailable", "reason": type(error).__name__}
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError):
        return {"status": "invalid_response", "reason": "Model listing contains invalid JSON."}
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return {"status": "invalid_response", "reason": "Model listing has no data array."}
    if len(data) > MAX_MODELS:
        return {"status": "too_many_models", "count": len(data), "limit": MAX_MODELS}
    models = []
    for item in data:
        name = item.get("id") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name.strip() or len(name) > 2048 or any(c in name for c in "\r\n\x00"):
            return {"status": "invalid_response", "reason": "A model identity is missing or invalid."}
        # A local endpoint can itself proxy remote inference. A name is only a
        # warning signal; even an ordinary name does not prove local execution.
        models.append({"id": name, "remote_name_hint": name.endswith(":cloud"),
                       "capability_acceptance": "not_probed", "inference_locality": "not_verified"})
    return {"status": "discovered" if models else "empty", "models": models,
            "response_sha256": hashlib.sha256(raw).hexdigest(), "response_bytes": len(raw)}


def probe_service(base_url, *, timeout=3.0):
    """Bounded metadata discovery with no keys, proxy fallback or redirects."""
    from harness.home import endpoint

    base_url = endpoint(base_url)
    timeout = _timeout(timeout)
    started = time.monotonic()
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "_probe", base_url, str(timeout)]
    try:
        completed = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                   timeout=timeout, check=False, shell=False)
    except subprocess.TimeoutExpired:
        result = {"status": "timeout", "reason": "Whole model-discovery deadline exceeded."}
    else:
        try:
            result = json.loads(completed.stdout) if completed.returncode == 0 else None
        except (ValueError, UnicodeError):
            result = None
        if not isinstance(result, dict) or not isinstance(result.get("status"), str):
            result = {"status": "probe_failed", "reason": "Metadata probe did not return a valid result."}
    return dict(result, base_url=base_url, elapsed_seconds=round(time.monotonic() - started, 3),
                model_requests=0, authority="discovery_only")


def discover(*, services=None, timeout=3.0, total_timeout=10.0):
    """Inspect only explicit services or three documented loopback defaults."""
    timeout, total_timeout = _timeout(timeout), _timeout(total_timeout)
    services = list(DEFAULT_LOCAL_SERVICES if services is None else services)
    if len(services) > 8:
        raise OnboardingError("Inspect at most eight explicitly selected services.")
    from harness.home import endpoint

    services = list(dict.fromkeys(endpoint(value) for value in services))
    started = time.monotonic()
    results = []
    for service in services:
        remaining = total_timeout - (time.monotonic() - started)
        if remaining < 0.1:
            results.append({"base_url": service, "status": "not_attempted", "reason": "Total discovery deadline reached."})
            continue
        results.append(probe_service(service, timeout=min(timeout, remaining)))
    return {"schema": "agent-local-model-discovery/v1", "services": results,
            "model_requests": 0, "configuration_changes": [],
            "next": "Qualify one owner-selected local runtime and its model/tool path before activation.",
            "limits": ["Listing a model does not load, choose or qualify it.",
                       "A local endpoint may proxy a cloud model; local inference remains unverified.",
                       "No ambient API keys, proxy settings or cloud fallback are used."],
            "elapsed_seconds": round(time.monotonic() - started, 3)}


def main(argv=None):
    from harness.home import HomeError

    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["_probe"]:
        if len(args) != 3:
            return 2
        from harness.home import endpoint
        print(json.dumps(_model_metadata(endpoint(args[1]), _timeout(float(args[2])))))
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Read host and selected-volume facts; create no files.")
    inspect.add_argument("--destination", required=True, type=Path)
    find = commands.add_parser("discover", help="Read local model metadata; make no inference requests.")
    find.add_argument("--base-url", action="append", dest="services")
    find.add_argument("--timeout", type=float, default=3.0)
    find.add_argument("--total-timeout", type=float, default=10.0)
    parsed = parser.parse_args(args)
    try:
        report = inventory(parsed.destination) if parsed.command == "inspect" else discover(
            services=parsed.services, timeout=parsed.timeout, total_timeout=parsed.total_timeout)
    except (ValueError, OSError, HomeError) as error:
        parser.exit(2, f"Onboarding: {error}\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
