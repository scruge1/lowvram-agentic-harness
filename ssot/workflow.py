"""Onboarding and host-runner layer for the portable SSOT controller."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .control import (
    SCHEMA_VERSION,
    STATE_DIR,
    SSOTError,
    _content_projection,
    _file_records,
    _load_project,
    _mutating,
    _read_json,
    _safe_path,
    _sha_file,
    _stage_map,
    _utc_now,
    _write_new_json,
    abandon_work,
    prepare_work,
    project_status,
    submit_outputs,
    verify_stage,
)


@_mutating
def init_project(root: Union[Path, str], prd: str, project_id: str) -> Dict[str, Any]:
    """Create a source-bound, deliberately non-runnable project scaffold."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise SSOTError(f"project root does not exist: {root}")
    if not project_id.strip():
        raise SSOTError("project_id is required")
    prd_path = _safe_path(root, prd, must_exist=True)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "authority_cap": "tested",
        "initialization": {
            "state": "scaffolded",
            "created_at": _utc_now(),
            "instruction": (
                "Replace the unresolved whole-source row with a reviewed, lossless "
                "requirement inventory. Then define stages, verifiers, negative "
                "controls, and independent acceptance. Run doctor before work."
            ),
        },
        "target": {"files": [prd]},
        "requirements": [
            {
                "id": "REQ-UNRESOLVED-001",
                "text": f"Decompose and review every normative requirement in {prd}.",
                "scope_class": "not_yet_understood",
                "source": {
                    "path": prd,
                    "locator": "entire-file",
                    "sha256": _sha_file(prd_path),
                },
                "disposition": "unresolved",
            }
        ],
        "stages": [],
        "acceptance": None,
    }
    manifest_path = root / "ssot-project.json"
    _write_new_json(manifest_path, manifest)
    return {
        "state": "scaffolded",
        "project_id": project_id,
        "manifest": str(manifest_path),
        "source": manifest["requirements"][0]["source"],
        "ready": False,
        "next": "Review the PRD inventory and run `python -m ssot.cli --root . doctor`.",
    }


def doctor_project(root: Union[Path, str]) -> Dict[str, Any]:
    """Explain whether a scaffold is safe to admit to the work frontier."""
    root = Path(root).resolve()
    manifest_path = root / "ssot-project.json"
    project = _read_json(manifest_path)
    issues: List[str] = []
    requirements = project.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        issues.append("requirement inventory is absent")
        unresolved: List[str] = []
    else:
        unresolved = sorted(
            row.get("id", "<missing-id>")
            for row in requirements
            if isinstance(row, dict) and row.get("disposition") == "unresolved"
        )
        if unresolved:
            issues.append(f"unresolved requirements: {', '.join(unresolved)}")
    if not project.get("stages"):
        issues.append("no configured stages")
    if not isinstance(project.get("acceptance"), dict):
        issues.append("independent acceptance is not configured")

    status: Optional[Dict[str, Any]] = None
    try:
        status = project_status(root)
    except SSOTError as exc:
        issues.append(f"contract validation: {exc}")
    issues = list(dict.fromkeys(issues))
    ready = not issues and status is not None
    return {
        "project_id": project.get("project_id"),
        "state": status["authority_state"] if ready else "scaffolded",
        "ready": ready,
        "issues": issues,
        "unresolved_requirements": unresolved,
        "status": status,
        "next": (
            "Use `next` or `prepare` on the current frontier."
            if ready
            else "Resolve every issue; do not issue work yet."
        ),
    }


def next_work(root: Union[Path, str]) -> Dict[str, Any]:
    """Return read-only, agent-ready previews for all current frontier stages."""
    root = Path(root).resolve()
    diagnosis = doctor_project(root)
    if not diagnosis["ready"]:
        raise SSOTError("project is not ready; run doctor and resolve its issues")
    project, _, manifest_hash = _load_project(root)
    status = project_status(root)
    requirement_map = {row["id"]: row for row in project["requirements"]}
    stages = _stage_map(project)
    packets = []
    for row in status["stages"]:
        if row["state"] != "frontier":
            continue
        stage = stages[row["id"]]
        packets.append(
            {
                "stage_id": stage["id"],
                "objective": stage["objective"],
                "acceptance": stage["acceptance"],
                "requirements": [
                    requirement_map[item] for item in stage["requirements"]
                ],
                "materials": _content_projection(
                    _file_records(root, stage["materials"], require=True)
                ),
                "expected_outputs": list(stage["outputs"]),
                "properties": list(stage["properties"]),
                "verifier_owner": stage["verifier"]["owner"],
                "authority": "preview_only",
            }
        )
    return {
        "project_id": project["project_id"],
        "manifest_sha256": manifest_hash,
        "frontier": packets,
        "count": len(packets),
    }


def _write_trace(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _control_state(root: Path, allowed_telemetry: Path) -> Dict[str, str]:
    state = root / STATE_DIR
    if not state.exists():
        return {}
    records = {}
    for path in state.rglob("*"):
        if path.is_file() and path.resolve() != allowed_telemetry.resolve():
            records[path.relative_to(state).as_posix()] = _sha_file(path)
    return records


def run_stage_command(
    root: Union[Path, str],
    stage_id: str,
    worker: str,
    runtime: Dict[str, Any],
    command: List[str],
    *,
    timeout_seconds: int = 3600,
) -> Dict[str, Any]:
    """Host-launch one frontier stage and produce its execution receipt."""
    root = Path(root).resolve()
    if not command or not all(isinstance(item, str) and item for item in command):
        raise SSOTError("run command must be a non-empty argument list")
    if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 86400:
        raise SSOTError("run timeout_seconds must be 1..86400")
    diagnosis = doctor_project(root)
    if not diagnosis["ready"]:
        raise SSOTError("project is not ready; run doctor and resolve its issues")
    project, _, _ = _load_project(root)
    stage = _stage_map(project).get(stage_id)
    if stage is None:
        raise SSOTError(f"unknown stage: {stage_id}")
    trace_output = stage.get("trace_output")
    if not isinstance(trace_output, str) or trace_output not in stage["outputs"]:
        raise SSOTError(
            f"{stage_id}.trace_output must name a declared output for host-run mode"
        )

    work = prepare_work(root, stage_id, worker, runtime)
    run_id = work["run_id"]
    telemetry_path = root / STATE_DIR / "host-telemetry" / f"{run_id}.json"
    telemetry_path.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "SSOT_PROJECT_ROOT": str(root),
            "SSOT_RUN_ID": run_id,
            "SSOT_STAGE_ID": stage_id,
            "SSOT_EXPECTED_OUTPUTS": json.dumps(stage["outputs"]),
            "SSOT_TELEMETRY_PATH": str(telemetry_path),
        }
    )
    control_before = _control_state(root, telemetry_path)
    started_at = _utc_now()
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            shell=False,
            check=False,
        )
        exit_code = completed.returncode
        outcome = "exited"
        observed_exit_code = exit_code
        stdout = completed.stdout[-65536:]
        stderr = completed.stderr[-65536:]
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        outcome = "timed_out"
        observed_exit_code = None
        stdout = exc.stdout[-65536:] if isinstance(exc.stdout, str) else ""
        stderr = "host runner timed out"
    except OSError as exc:
        exit_code = 127
        outcome = "os_error"
        observed_exit_code = None
        stdout = ""
        stderr = f"host runner could not start command: {exc}"
    duration_ms = max(0, int((time.monotonic() - started) * 1000))
    control_after = _control_state(root, telemetry_path)
    if control_after != control_before:
        raise SSOTError(
            "worker command changed protected .ssot control state; run is held"
        )
    trace_path = _safe_path(root, trace_output)
    _write_trace(
        trace_path,
        {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "stage_id": stage_id,
            "worker": worker,
            "started_at": started_at,
            "finished_at": _utc_now(),
            "duration_ms": duration_ms,
            "process_observation": {
                "outcome": outcome,
                "observed_exit_code": observed_exit_code,
                "duration_ms": duration_ms,
                "descendant_quiescence": "unknown",
            },
            "argv": command,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
        },
    )
    if exit_code != 0:
        abandonment = abandon_work(
            root, run_id, f"host command failed with exit code {exit_code}"
        )
        return {
            "status": "failed",
            "run_id": run_id,
            "exit_code": exit_code,
            "trace": trace_output,
            "abandonment": abandonment,
        }

    execution: Dict[str, Any] = {
        "host_observed": True,
        "status": "completed",
        "duration_ms": duration_ms,
        "trace_file": trace_output,
    }
    if runtime.get("kind") in ("local_model", "remote_model"):
        if not telemetry_path.is_file():
            abandonment = abandon_work(
                root, run_id, "model harness did not write SSOT_TELEMETRY_PATH"
            )
            return {
                "status": "failed",
                "run_id": run_id,
                "exit_code": exit_code,
                "trace": trace_output,
                "error": "missing model telemetry",
                "abandonment": abandonment,
            }
        execution.update(_read_json(telemetry_path))
        execution.update(
            {
                "host_observed": True,
                "status": "completed",
                "duration_ms": duration_ms,
                "trace_file": trace_output,
            }
        )

    producer = submit_outputs(root, run_id, worker, execution)
    verification = verify_stage(root, run_id)
    return {
        "status": "verified" if verification["status"] == "verified" else "failed",
        "run_id": run_id,
        "exit_code": exit_code,
        "trace": trace_output,
        "producer_receipt": producer,
        "verification_receipt": verification,
    }
