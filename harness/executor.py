#!/usr/bin/env python3
"""Receipt-gated execution and continuity for a compiled trusted project."""

from __future__ import annotations

import json
import math
import sys
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

import harness.enforcement as enforcement_module
from harness.enforcement import EnforcementError, validate_contract, verify_receipt
from harness.project import (
    ProjectError,
    _append_event,
    _canonical,
    _load_intent,
    _project_lock,
    _sha_bytes,
    _sha_file,
    _target_root,
    _write_new_json,
)
from ssot.control import SSOTError, accept_project, abandon_work
from ssot.control import project_status as ssot_status
from ssot.workflow import run_stage_command


SCHEMA_VERSION = 1
USAGE_FIELDS = (
    "model_tokens",
    "cost_usd",
    "wall_seconds",
    "outer_attempts",
    "research_sources",
    "storage_bytes",
    "external_side_effects",
)
_EXECUTION_LOCKS: Dict[str, threading.Lock] = {}


@contextmanager
def _execution_lock(root: Path, project_id: str):
    """Hold one crash-releasing lock across recovery, launch, and acceptance."""
    key = f"{root}:{project_id}".casefold()
    process_lock = _EXECUTION_LOCKS.setdefault(key, threading.Lock())
    if not process_lock.acquire(blocking=False):
        raise ProjectError("another trusted-project execution is active")
    lock_name = _sha_bytes(f"{root}:{project_id}".encode("utf-8"))
    lock_path = Path(tempfile.gettempdir()) / "trusted-project-locks" / f"{lock_name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.is_symlink():
        process_lock.release()
        raise ProjectError("execution lock cannot be a symlink")
    handle = lock_path.open("a+b")
    try:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            raise ProjectError("another trusted-project execution is active") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()
        process_lock.release()


def _read_object(path: Path, label: str) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProjectError(f"{label} must be a JSON object")
    return value


def _safe_file(root: Path, value: str, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ProjectError(f"{label} path is required")
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ProjectError(f"{label} escapes target root")
    unresolved = root / candidate
    current = unresolved
    while current != root:
        if current.is_symlink():
            raise ProjectError(f"{label} cannot use symlinks")
        current = current.parent
    path = unresolved.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ProjectError(f"{label} escapes target root") from exc
    if not path.is_file():
        raise ProjectError(f"{label} is not an existing regular file")
    return path


def _zero_usage() -> Dict[str, Any]:
    return {name: 0 for name in USAGE_FIELDS}


def _add_usage(left: Mapping[str, Any], right: Mapping[str, Any]) -> Dict[str, Any]:
    return {name: left.get(name, 0) + right.get(name, 0) for name in USAGE_FIELDS}


def _remaining(budgets: Mapping[str, Any], used: Mapping[str, Any]) -> Dict[str, Any]:
    return {name: max(0, budgets[name] - used.get(name, 0)) for name in USAGE_FIELDS}


def _receipt_body(value: Dict[str, Any]) -> Dict[str, Any]:
    return {key: item for key, item in value.items() if key != "record_sha256"}


def _execution_receipts(
    root: Path,
    project_dir: Path,
    project_id: str,
    events: Iterable[Any],
) -> tuple[list[Dict[str, Any]], Dict[str, Any]]:
    receipts = []
    used = _zero_usage()
    seen_stages = set()
    for _path, event in events:
        if event.get("event_type") != "execution_finished":
            continue
        details = event.get("details", {})
        receipt_path = _safe_file(root, details.get("receipt_path"), "execution receipt")
        if details.get("receipt_sha256") != _sha_file(receipt_path):
            raise ProjectError("execution event receipt hash changed")
        receipt = _read_object(receipt_path, "execution receipt")
        if (
            receipt.get("record_sha256")
            != _sha_bytes(_canonical(_receipt_body(receipt)))
            or receipt.get("project_id") != project_id
            or receipt.get("status") != "verified"
        ):
            raise ProjectError("execution receipt is invalid")
        stage_id = receipt.get("stage_id")
        if stage_id in seen_stages:
            raise ProjectError("a stage has more than one finished execution receipt")
        seen_stages.add(stage_id)
        task_receipt = _safe_file(
            root, receipt.get("task_receipt", {}).get("path"), "task receipt"
        )
        if receipt["task_receipt"].get("sha256") != _sha_file(task_receipt):
            raise ProjectError("task receipt changed after project execution")
        contract_path = _safe_file(
            root, receipt.get("contract", {}).get("path"), "execution contract"
        )
        if receipt["contract"].get("sha256") != _sha_file(contract_path):
            raise ProjectError("execution contract changed after project execution")
        try:
            verify_receipt(root, contract_path, task_receipt)
        except EnforcementError as exc:
            raise ProjectError(f"task receipt no longer verifies: {exc}") from exc
        verification = _safe_file(
            root,
            receipt.get("ssot_verification", {}).get("path"),
            "SSOT verification receipt",
        )
        if receipt["ssot_verification"].get("sha256") != _sha_file(verification):
            raise ProjectError("SSOT verification receipt changed")
        authorization = receipt.get("authorization")
        if authorization is not None:
            auth_path = _safe_file(
                root, authorization.get("path"), "effect authorization"
            )
            if authorization.get("sha256") != _sha_file(auth_path):
                raise ProjectError("effect authorization changed after execution")
        usage = receipt.get("usage")
        if not isinstance(usage, dict) or set(usage) != set(USAGE_FIELDS):
            raise ProjectError("execution receipt usage is invalid")
        used = _add_usage(used, usage)
        receipts.append(receipt)
    return receipts, used


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ProjectError(f"{label} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProjectError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise ProjectError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _authorize_effects(
    root: Path,
    project_id: str,
    stage_id: str,
    effects: list[str],
    path: Optional[Path],
) -> Optional[Dict[str, str]]:
    if not effects:
        return None
    if path is None:
        raise ProjectError(f"stage {stage_id} requires fresh effect authorization")
    unresolved = path if path.is_absolute() else root / path
    try:
        relative = unresolved.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise ProjectError("effect authorization escapes target root") from exc
    auth_path = _safe_file(root, relative, "effect authorization")
    auth = _read_object(auth_path, "effect authorization")
    required = {
        "schema_version",
        "project_id",
        "stage_id",
        "effects",
        "authorized_by",
        "issued_at",
        "expires_at",
    }
    if set(auth) != required or auth.get("schema_version") != SCHEMA_VERSION:
        raise ProjectError("effect authorization fields do not match schema version 1")
    if auth.get("project_id") != project_id or auth.get("stage_id") != stage_id:
        raise ProjectError("effect authorization names the wrong project or stage")
    if auth.get("effects") != effects:
        raise ProjectError("effect authorization does not match the declared effects")
    if not isinstance(auth.get("authorized_by"), str) or not auth["authorized_by"].strip():
        raise ProjectError("effect authorization owner is required")
    now = datetime.now(timezone.utc)
    issued = _parse_time(auth.get("issued_at"), "effect authorization issued_at")
    expires = _parse_time(auth.get("expires_at"), "effect authorization expires_at")
    if issued > now or expires <= now or (now - issued).total_seconds() > 3600:
        raise ProjectError("effect authorization is not fresh and live")
    return {"path": relative, "sha256": _sha_file(auth_path)}


def _stage_usage(root: Path, stage: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    action = stage["action"]
    contract_path = _safe_file(root, action["contract"], "execution contract")
    contract = validate_contract(root, _read_object(contract_path, "execution contract"))
    task_receipt_path = _safe_file(root, action["receipt_output"], "task receipt")
    task_receipt = _read_object(task_receipt_path, "task receipt")
    research_sources = 0
    if contract["research"]["required"]:
        research_path = _safe_file(
            root, contract["research"]["receipt_output"], "research receipt"
        )
        research = _read_object(research_path, "research receipt")
        research_sources = len(research.get("source_records", []))
    storage = sum((root / output).stat().st_size for output in stage["outputs"])
    trace = _read_object(root / result["trace"], "controller trace")
    usage = _zero_usage()
    usage.update(
        {
            "wall_seconds": max(1, math.ceil(trace.get("duration_ms", 0) / 1000)),
            "outer_attempts": len(task_receipt.get("attempts", [])),
            "research_sources": research_sources,
            "storage_bytes": storage,
            "external_side_effects": len(action["effects"]),
        }
    )
    return usage


def execution_status(
    root: Path,
    project_dir: Path,
    intent: Dict[str, Any],
    events: Iterable[Any],
) -> Dict[str, Any]:
    """Revalidate execution receipts and derive project-level usage and state."""
    event_rows = list(events)
    receipts, used = _execution_receipts(
        root, project_dir, intent["project_id"], event_rows
    )
    starts = [
        row[1].get("details", {})
        for row in event_rows
        if row[1].get("event_type") == "execution_started"
    ]
    finished_by_stage: Dict[str, int] = {}
    for receipt in receipts:
        stage_id = receipt["stage_id"]
        finished_by_stage[stage_id] = finished_by_stage.get(stage_id, 0) + 1
    for started in reversed(starts):
        stage_id = started.get("stage_id")
        if finished_by_stage.get(stage_id, 0):
            finished_by_stage[stage_id] -= 1
            continue
        reserved = _zero_usage()
        reserved["outer_attempts"] = started.get("reserved_outer_attempts", 0)
        reserved["research_sources"] = started.get(
            "reserved_research_sources", 0
        )
        reserved["external_side_effects"] = started.get(
            "reserved_external_side_effects", 0
        )
        used = _add_usage(used, reserved)
    budgets = intent["budgets"]["values"]
    exceeded = [name for name in USAGE_FIELDS if used[name] > budgets[name]]
    ssot = ssot_status(root)
    started = sum(row[1].get("event_type") == "execution_started" for row in event_rows)
    finished = len(receipts)
    controls = [
        row[1]
        for row in event_rows
        if row[1].get("event_type")
        in {"execution_started", "execution_finished", "execution_held", "execution_recovered", "execution_resumed"}
    ]
    latest_control = controls[-1].get("event_type") if controls else None
    if ssot["accepted"] and len(receipts) != len(ssot["stages"]):
        raise ProjectError("accepted SSOT is missing trusted-project execution receipts")
    if ssot["accepted"] and not exceeded:
        state = "tested"
        next_action = "archive or retain this project's evidence"
    elif exceeded:
        state = "held_budget_exhausted"
        next_action = "start a superseding project with reviewed budgets"
    elif latest_control == "execution_held":
        state = (
            "failed"
            if controls[-1].get("details", {}).get("category") == "failure"
            else "held_execution"
        )
        next_action = controls[-1].get("details", {}).get(
            "next_allowed_action", "review hold evidence"
        )
    elif latest_control == "execution_started" and started > finished:
        state = "running"
        next_action = "resume to recover the interrupted SSOT work order"
    elif ssot["stages_verified"]:
        state = "verified"
        next_action = "run configured independent project acceptance"
    else:
        state = "configured"
        next_action = "execute the verified SSOT frontier"
    return {
        "state": state,
        "authority": "tested" if state == "tested" else "no_project_completion_authority",
        "ready_for_execution": state in {"configured", "verified"},
        "next_allowed_action": next_action,
        "budgets": budgets,
        "usage": used,
        "remaining": _remaining(budgets, used),
        "budget_exceeded": exceeded,
        "execution_receipts": len(receipts),
        "ssot": ssot,
    }


def _hold(
    root: Path,
    project_dir: Path,
    intent_hash: str,
    reason: str,
    next_action: str,
    *,
    category: str = "hold",
) -> None:
    with _project_lock(root, project_dir.name):
        _append_event(
            project_dir,
            intent_hash,
            "execution_held",
            {
                "reason": reason,
                "category": category,
                "next_allowed_action": next_action,
            },
        )


def _recover_interrupted(root: Path, project_dir: Path, intent_hash: str) -> None:
    status = ssot_status(root)
    active = [row for row in status["stages"] if row["state"] == "in_progress"]
    if not active:
        return
    from ssot.control import _latest_work_order

    for stage in active:
        latest = _latest_work_order(root, stage["id"])
        if latest is None:
            raise ProjectError(f"interrupted stage {stage['id']} has no work order")
        run_id = latest[1]["run_id"]
        try:
            abandonment = abandon_work(root, run_id, "trusted-project interruption recovery")
        except SSOTError as exc:
            raise ProjectError(f"cannot recover interrupted stage: {exc}") from exc
        with _project_lock(root, project_dir.name):
            _append_event(
                project_dir,
                intent_hash,
                "execution_recovered",
                {
                    "stage_id": stage["id"],
                    "ssot_run_id": run_id,
                    "abandonment_sha256": _sha_bytes(_canonical(abandonment)),
                },
            )


def _execute_project_locked(
    root: Path,
    project_id: str,
    *,
    authorizations: Optional[Mapping[str, Path]] = None,
) -> Dict[str, Any]:
    """Run every available stage through enforcement and independent acceptance."""
    from harness.project import project_status

    root = _target_root(root)
    project_dir, intent_path, intent = _load_intent(root, project_id)
    intent_hash = _sha_file(intent_path)
    if intent["requested_mode"] != "execute":
        raise ProjectError("plan-mode project requires a new explicit execute intent")
    initial = project_status(root, project_id)
    if initial["state"] == "tested":
        initial["idempotent"] = True
        return initial
    if initial["state"] not in {"ssot_compiled", "configured", "running", "verified"}:
        if initial["state"] not in {"held_execution", "failed"}:
            raise ProjectError(f"project cannot execute from state: {initial['state']}")
    _recover_interrupted(root, project_dir, intent_hash)
    if initial["state"] in {"running", "held_execution", "failed"}:
        with _project_lock(root, project_id):
            _append_event(
                project_dir,
                intent_hash,
                "execution_resumed",
                {"prior_state": initial["state"]},
            )
    auth = dict(authorizations or {})

    while True:
        current = project_status(root, project_id)
        if current["state"] in {"held_budget_exhausted", "held_execution"}:
            return current
        ssot = ssot_status(root)
        frontier = [row for row in ssot["stages"] if row["state"] == "frontier"]
        if not frontier:
            break
        manifest = _read_object(root / "ssot-project.json", "SSOT manifest")
        stage_map = {row["id"]: row for row in manifest["stages"]}
        for frontier_row in frontier:
            stage = stage_map[frontier_row["id"]]
            action = stage["action"]
            contract_path = _safe_file(root, action["contract"], "execution contract")
            contract = validate_contract(root, _read_object(contract_path, "execution contract"))
            remaining = current.get("remaining", intent["budgets"]["values"])
            if action["usage_mode"] != "script_no_model":
                _hold(root, project_dir, intent_hash, "unmetered model usage", "configure a live metered host adapter")
                return project_status(root, project_id)
            if contract["retry"]["max_attempts"] > remaining["outer_attempts"]:
                _hold(root, project_dir, intent_hash, "outer-attempt budget cannot cover the stage contract", "start a superseding project with a sufficient reviewed budget")
                return project_status(root, project_id)
            if len(action["effects"]) > remaining["external_side_effects"]:
                _hold(root, project_dir, intent_hash, "external-side-effect budget cannot cover the stage", "start a superseding project with a sufficient reviewed budget")
                return project_status(root, project_id)
            try:
                authorization = _authorize_effects(
                    root,
                    project_id,
                    stage["id"],
                    action["effects"],
                    auth.get(stage["id"]),
                )
            except ProjectError as exc:
                _hold(
                    root,
                    project_dir,
                    intent_hash,
                    str(exc),
                    "provide a fresh exact authorization and resume",
                )
                return project_status(root, project_id)
            timeout = int(remaining["wall_seconds"])
            if timeout < 1:
                _hold(root, project_dir, intent_hash, "wall-time budget is exhausted", "start a superseding project with a sufficient reviewed budget")
                return project_status(root, project_id)
            runtime = {
                "kind": "script",
                "executor": "trusted-project-e6d",
                "harness": "harness.enforcement",
                "harness_version": "1",
                "host_observed": True,
                "attempt": 1,
                "fallback_from": None,
            }
            with _project_lock(root, project_id):
                _append_event(
                    project_dir,
                    intent_hash,
                    "execution_started",
                    {
                        "stage_id": stage["id"],
                        "contract_sha256": _sha_file(contract_path),
                        "reserved_outer_attempts": contract["retry"]["max_attempts"],
                        "reserved_research_sources": (
                            contract["research"].get("min_sources", 0)
                            if contract["research"]["required"]
                            else 0
                        ),
                        "reserved_external_side_effects": len(action["effects"]),
                    },
                )
            command = [
                sys.executable,
                str(Path(enforcement_module.__file__).resolve()),
                "run",
                "--root",
                str(root),
                "--spec",
                str(contract_path),
            ]
            try:
                result = run_stage_command(
                    root,
                    stage["id"],
                    action["producer"],
                    runtime,
                    command,
                    timeout_seconds=min(timeout, 86400),
                )
            except (SSOTError, OSError) as exc:
                _hold(root, project_dir, intent_hash, f"stage launch failed: {exc}", "fix the recorded failure and resume", category="failure")
                return project_status(root, project_id)
            if result["status"] != "verified":
                _hold(root, project_dir, intent_hash, f"stage {stage['id']} did not verify", "fix the recorded enforcement failure and resume", category="failure")
                return project_status(root, project_id)
            try:
                verify_receipt(root, contract_path, root / action["receipt_output"])
            except EnforcementError as exc:
                _hold(root, project_dir, intent_hash, f"enforcement receipt failed revalidation: {exc}", "repair the task evidence and resume", category="failure")
                return project_status(root, project_id)
            usage = _stage_usage(root, stage, result)
            verification_path = (
                root / ".ssot" / "verification" / f"{result['run_id']}.json"
            )
            body = {
                "schema_version": SCHEMA_VERSION,
                "receipt_type": "trusted_project_execution",
                "status": "verified",
                "project_id": project_id,
                "stage_id": stage["id"],
                "ssot_run_id": result["run_id"],
                "contract": {
                    "path": contract_path.relative_to(root).as_posix(),
                    "sha256": _sha_file(contract_path),
                },
                "task_receipt": {
                    "path": action["receipt_output"],
                    "sha256": _sha_file(root / action["receipt_output"]),
                },
                "ssot_verification": {
                    "path": verification_path.relative_to(root).as_posix(),
                    "sha256": _sha_file(verification_path),
                },
                "authorization": authorization,
                "usage": usage,
            }
            receipt = {**body, "record_sha256": _sha_bytes(_canonical(body))}
            receipt_path = project_dir / "execution" / f"{stage['id']}.json"
            _write_new_json(receipt_path, receipt)
            with _project_lock(root, project_id):
                _append_event(
                    project_dir,
                    intent_hash,
                    "execution_finished",
                    {
                        "stage_id": stage["id"],
                        "receipt_path": receipt_path.relative_to(root).as_posix(),
                        "receipt_sha256": _sha_file(receipt_path),
                    },
                )
            current = project_status(root, project_id)
            if current["state"] == "held_budget_exhausted":
                return current

    final_ssot = ssot_status(root)
    if final_ssot["stages_verified"] and not final_ssot["accepted"]:
        pre_acceptance = project_status(root, project_id)
        if pre_acceptance["execution_receipts"] != len(final_ssot["stages"]):
            _hold(
                root,
                project_dir,
                intent_hash,
                "verified SSOT stage is missing its project execution receipt",
                "recover or independently re-run the missing stage evidence",
                category="failure",
            )
            return project_status(root, project_id)
        manifest = _read_object(root / "ssot-project.json", "SSOT manifest")
        try:
            acceptance = accept_project(root, manifest["acceptance"]["owner"])
        except SSOTError as exc:
            _hold(root, project_dir, intent_hash, f"independent acceptance failed: {exc}", "repair acceptance evidence and resume", category="failure")
            return project_status(root, project_id)
        acceptance_path = Path(ssot_status(root)["acceptance_receipt"])
        with _project_lock(root, project_id):
            _append_event(
                project_dir,
                intent_hash,
                "project_accepted",
                {
                    "ssot_acceptance_path": acceptance_path.relative_to(root).as_posix(),
                    "ssot_acceptance_sha256": _sha_file(acceptance_path),
                    "authority": acceptance["authority"],
                },
            )
    result = project_status(root, project_id)
    result["idempotent"] = False
    return result


def execute_project(
    root: Path,
    project_id: str,
    *,
    authorizations: Optional[Mapping[str, Path]] = None,
) -> Dict[str, Any]:
    """Serialize one full project execution while allowing crash recovery."""
    resolved = _target_root(root)
    with _execution_lock(resolved, project_id):
        return _execute_project_locked(
            resolved, project_id, authorizations=authorizations
        )
