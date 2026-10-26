"""Read current home-owned serving status; never start, stop or reserve it."""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
from pathlib import Path
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from harness.resource_status import main
    raise SystemExit(main())

from . import hardware_probe, home_entry, model_service, model_service_handoff


SCHEMA = "agent-home-resource-status/v1"
SETUP_PHASES = {"validated", "stopping_pre_home", "pre_home_stopped", "installing_packages",
                "home_guard_ready", "starting_after_home", "complete", "failed"}


def _memory():
    try:
        values = hardware_probe.ram_info()
    except (OSError, ValueError, RuntimeError):
        values = {}
    return {key: value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None
            for key, value in (("total_gb", values.get("total_gb")), ("available_gb", values.get("available_gb")))}


def _cpu_count():
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count()


def _rss(pid):
    try:
        text = (Path("/proc") / str(pid) / "status").read_text(encoding="utf-8")
        value = re.search(r"^VmRSS:\s+(\d+) kB$", text, re.M)
        return int(value.group(1)) * 1024 if value else None
    except OSError:
        return None


def _setup(root):
    path = model_service._within(root, "state/model-service/setup.json")
    if not path.exists():
        return {"state": "not_recorded"}
    value = model_service._read(path)
    phase = value.get("phase")
    return {"state": "retained_record", "phase": phase if phase in SETUP_PHASES else "unknown",
            "failed_stage": value.get("failed_stage") if value.get("failed_stage") in SETUP_PHASES else None,
            "historical_record": True, "current_job_or_recovery_success": "not_established"}


def read_status(value):
    """A point-in-time observation, never resource admission or task acceptance.

    model_service.status owns nonce/process/listener validation and bounded local
    GETs. Its raw response and errors must never become model-visible output.
    """
    home, config = home_entry.selected_home(value)
    report = {"schema": SCHEMA, "home": str(home), "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "authority": "none", "generative_requests": 0,
              "queue": {"state": "unknown", "busy": None, "waiting_requests": None,
                        "reason": "No qualified request occupancy or queue observation is available."},
              "fit": "not_probed", "task_capability": "not_probed",
              "new_owned_gpu_start_admission": "held_no_qualified_atomic_owner_route",
              "limits": "Snapshot only; no reservation, foreign inventory, polling, start, stop or task progress."}
    # Share the existing lifecycle boundary. This never bypasses a pending update.
    with home_entry.consumer(home):
        report["host_snapshot"] = {"ram": _memory(), "available_cpu_affinity_or_logical": _cpu_count(),
                                   "capacity_for_this_model": "not_established", "exclusive_allocation": False}
        binding = config.get("owned_model_service")
        if binding is None:
            report["service"] = {"mode": "attached_or_unmanaged", "status": "unknown",
                                 "reason": "Endpoint configuration does not establish process, resource or inference ownership."}
            return report
        try:
            expected = model_service_handoff._binding(binding)
            if expected["home"] != str(home):
                raise ValueError("Home binding differs")
            root = model_service._home(home)
            if str(root) != expected["storage_root"]:
                raise ValueError("Storage binding differs")
            report["setup"] = _setup(root)
            status = model_service.status(home)
            if status.get("status") == "stopped":
                phase = status.get("last_phase")
                phase = phase if phase in ("starting", "running", "stopped", "recovery_required") else None
                report["service"] = {"mode": "owned_binding", "status": "stopped", "live_process_verified": False,
                                     "last_recorded_phase": phase, "needs_owner_inspection": phase not in (None, "stopped")}
            else:
                route = model_service_handoff._route(status)
                if route != expected or status.get("status") not in ("starting", "running"):
                    raise ValueError("Selected route differs")
                lease = model_service_handoff._home_lease(route, status["pid"])
                if lease.get("lease_scope") != "home_shared":
                    raise ValueError("Missing child home lease")
                current = model_service._read(model_service._within(root, "state/model-service/service.json"))
                if current.get("pid") != status["pid"] or current.get("start_ticks") != status["start_ticks"]:
                    raise ValueError("Service lifetime changed")
                if current.get("phase") not in ("starting", "running"):
                    raise ValueError("Retained service recovery is unresolved")
                model_service._identity(root, current, status["pid"])
                rss = _rss(status["pid"])
                model_service._identity(root, current, status["pid"])
                report["service"] = {"mode": "owned", "status": status["status"], "live_process_verified": True,
                                     "pid": status["pid"], "start_ticks": status["start_ticks"],
                                     "model_id": route["model_id"], "context": route["context"], "max_output": route["max_output"],
                                     "base_url": route["base_url"], "transport_profile": route["transport_profile"],
                                     "specification_sha256": route["specification_sha256"], "lease_scope": "home_shared",
                                     "rss_bytes": rss, "parallelism_argument": 1, "last_recorded_phase": current["phase"],
                                     "readiness": "ready" if status["status"] == "running" else "not_ready"}
            # Return argv data, never execute it. The existing service CLI owns
            # exact PIDFD stop and will independently revalidate its lifetime.
            report["operator_release"] = {"executes": False, "scope": "this_owned_service_only",
                                           "cwd": str(home / "runtime"), "program": sys.executable,
                                           "arguments": ["-B", "-m", "harness.model_service", "--home", str(home), "stop"],
                                           "requires": "Explicit operator instruction; preserve active task and inspect uncertain effects."}
        except (OSError, ValueError, KeyError, TypeError):
            report["service"] = {"mode": "owned_binding", "status": "held", "live_process_verified": False,
                                 "reason": "Owned service identity, lifecycle, route or readiness could not be verified. Inspect existing owned service/setup evidence; no automatic retry or release."}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--home", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = read_status(args.home)
        print(json.dumps(report))
        return 0
    except (OSError, ValueError, TypeError):
        print(json.dumps({"schema": SCHEMA, "status": "unavailable", "authority": "none", "generative_requests": 0,
                          "error": "Managed home resource status is unavailable; inspect its lifecycle and identity."}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
