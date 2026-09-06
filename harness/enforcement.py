#!/usr/bin/env python3
"""Harness-neutral task supervision and host-hook enforcement.

The supervisor treats an agent harness as an untrusted command. It admits optional
research, launches bounded attempts, records tool-hook failures when an adapter is
installed, runs an independent negative control and verifier, and writes one final
receipt for SSOT consumption.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


SCHEMA_VERSION = 1
STATE_DIR = ".enforcement"
ZERO_HASH = "0" * 64
RETRY_CLASSES = {"process_failure", "tool_failure", "verification_failure"}


class EnforcementError(RuntimeError):
    """A task contract or execution path failed closed."""


def _engine_record() -> Dict[str, Any]:
    path = Path(__file__).resolve()
    return {
        "module": "harness.enforcement",
        "schema_version": SCHEMA_VERSION,
        "size": path.stat().st_size,
        "sha256": _sha_file(path),
    }


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EnforcementError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EnforcementError(f"JSON object required: {path}")
    return value


def _safe_path(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise EnforcementError("path must be a non-empty relative string")
    candidate = Path(relative)
    if candidate.is_absolute():
        raise EnforcementError(f"absolute path is not allowed: {relative}")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise EnforcementError(f"path escapes task root: {relative}") from exc
    if must_exist and not resolved.is_file():
        raise EnforcementError(f"required file is missing: {relative}")
    return resolved


def _write_json(path: Path, value: Dict[str, Any], *, new: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if new:
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise EnforcementError(
                f"refusing to overwrite immutable record: {path}"
            ) from exc
        return
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _string_list(value: Any, label: str, *, nonempty: bool = True) -> List[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise EnforcementError(
            f"{label} must be a {'non-empty ' if nonempty else ''}list"
        )
    if not all(isinstance(item, str) and item for item in value):
        raise EnforcementError(f"{label} must contain non-empty strings")
    return list(value)


def _validate_command(
    command: Any, label: str, root: Path, *, require_files: bool = False
) -> Dict[str, Any]:
    if not isinstance(command, dict):
        raise EnforcementError(f"{label} must be an object")
    argv = _string_list(command.get("argv"), f"{label}.argv")
    timeout = command.get("timeout_seconds", 600)
    if not isinstance(timeout, int) or not 1 <= timeout <= 86400:
        raise EnforcementError(f"{label}.timeout_seconds must be 1..86400")
    files = _string_list(
        command.get("files", []), f"{label}.files", nonempty=require_files
    )
    for file_name in files:
        _safe_path(root, file_name, must_exist=True)
    return {**command, "argv": argv, "timeout_seconds": timeout, "files": files}


def validate_contract(root: Path, contract: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalize one task contract without changing task state."""
    root = root.resolve()
    if contract.get("schema_version") != SCHEMA_VERSION:
        raise EnforcementError(f"schema_version must be {SCHEMA_VERSION}")
    for field in ("task_id", "objective", "receipt_output"):
        if not isinstance(contract.get(field), str) or not contract[field].strip():
            raise EnforcementError(f"{field} is required")
    receipt_path = _safe_path(root, contract["receipt_output"])
    if STATE_DIR in receipt_path.relative_to(root).parts:
        raise EnforcementError("receipt_output cannot be inside .enforcement")
    outputs = _string_list(contract.get("outputs"), "outputs")
    if len(outputs) != len(set(outputs)):
        raise EnforcementError("outputs must be unique")
    if contract["receipt_output"] in outputs:
        raise EnforcementError("receipt_output must be separate from worker outputs")
    for output in outputs:
        path = _safe_path(root, output)
        if STATE_DIR in path.relative_to(root).parts:
            raise EnforcementError("worker outputs cannot be inside .enforcement")

    worker = _validate_command(contract.get("worker"), "worker", root)
    verifier = _validate_command(
        contract.get("verifier"), "verifier", root, require_files=True
    )
    negative = _validate_command(
        verifier.get("negative_control"), "verifier.negative_control", root
    )
    if negative["argv"] == verifier["argv"]:
        raise EnforcementError(
            "verifier negative control must use a distinct invocation"
        )
    shared = 2 if verifier["argv"][0] == "{python}" else 1
    if negative["argv"][:shared] != verifier["argv"][:shared]:
        raise EnforcementError(
            "negative control must exercise the same verifier program"
        )
    if worker["argv"] == verifier["argv"] or set(worker["files"]) & set(
        verifier["files"]
    ):
        raise EnforcementError("worker and verifier must use separate programs")
    verifier["negative_control"] = negative

    retry = contract.get("retry")
    if not isinstance(retry, dict):
        raise EnforcementError("retry must be an object")
    max_attempts = retry.get("max_attempts")
    if not isinstance(max_attempts, int) or not 1 <= max_attempts <= 10:
        raise EnforcementError("retry.max_attempts must be 1..10")
    retry_on = set(_string_list(retry.get("retry_on"), "retry.retry_on"))
    if not retry_on <= RETRY_CLASSES:
        raise EnforcementError(
            f"unsupported retry classes: {sorted(retry_on - RETRY_CLASSES)}"
        )
    backoff = retry.get("backoff_seconds", [0])
    if not isinstance(backoff, list) or not backoff:
        raise EnforcementError("retry.backoff_seconds must be a non-empty list")
    if not all(isinstance(item, (int, float)) and 0 <= item <= 30 for item in backoff):
        raise EnforcementError("retry backoff values must be 0..30 seconds")
    inner_max = retry.get("inner_tool_max_attempts", 2)
    if not isinstance(inner_max, int) or not 0 <= inner_max <= 10:
        raise EnforcementError("retry.inner_tool_max_attempts must be 0..10")

    research = contract.get("research", {"required": False})
    if not isinstance(research, dict) or not isinstance(research.get("required"), bool):
        raise EnforcementError("research.required must be a boolean")
    if research["required"]:
        research = _validate_command(research, "research", root)
        receipt_output = research.get("receipt_output")
        research_receipt = _safe_path(root, receipt_output)
        if STATE_DIR in research_receipt.relative_to(root).parts:
            raise EnforcementError(
                "research.receipt_output cannot be inside .enforcement"
            )
        if receipt_output == contract["receipt_output"] or receipt_output in outputs:
            raise EnforcementError("research receipt must have a separate output path")
        minimum = research.get("min_sources", 2)
        if not isinstance(minimum, int) or not 1 <= minimum <= 20:
            raise EnforcementError("research.min_sources must be 1..20")
        research["required"] = True
        research["receipt_output"] = receipt_output
        research["min_sources"] = minimum

    side_effecting = retry.get(
        "side_effecting_tools",
        ["Bash", "PowerShell", "terminal", "Edit", "Write", "patch", "write_file"],
    )
    _string_list(side_effecting, "retry.side_effecting_tools", nonempty=False)
    normalized = {
        **contract,
        "outputs": outputs,
        "worker": worker,
        "verifier": verifier,
        "retry": {
            **retry,
            "max_attempts": max_attempts,
            "retry_on": sorted(retry_on),
            "backoff_seconds": backoff,
            "inner_tool_max_attempts": inner_max,
            "side_effecting_tools": side_effecting,
        },
        "research": research,
    }
    return normalized


def doctor(root: Path, spec_path: Path) -> Dict[str, Any]:
    """Return a non-mutating contract diagnosis."""
    root = root.resolve()
    try:
        resolved_spec = spec_path.resolve()
        resolved_spec.relative_to(root)
        contract = validate_contract(root, _read_json(resolved_spec))
    except ValueError:
        return {
            "ready": False,
            "issues": ["spec must be inside task root"],
            "task_id": None,
        }
    except EnforcementError as exc:
        return {"ready": False, "issues": [str(exc)], "task_id": None}
    warnings = []
    if not contract["research"]["required"]:
        warnings.append("research is not required by this task contract")
    return {
        "ready": True,
        "issues": [],
        "warnings": warnings,
        "task_id": contract["task_id"],
        "max_attempts": contract["retry"]["max_attempts"],
        "retry_on": contract["retry"]["retry_on"],
    }


def _expand_argv(argv: Iterable[str], values: Dict[str, str]) -> List[str]:
    expanded = []
    for item in argv:
        result = sys.executable if item == "{python}" else item
        for name, value in values.items():
            result = result.replace("{" + name + "}", value)
        expanded.append(result)
    return expanded


def _run_command(
    root: Path,
    command: Dict[str, Any],
    values: Dict[str, str],
    environment: Dict[str, str],
) -> Dict[str, Any]:
    argv = _expand_argv(command["argv"], values)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=command["timeout_seconds"],
            shell=False,
            check=False,
        )
        code = completed.returncode
        stdout = completed.stdout[-65536:]
        stderr = completed.stderr[-65536:]
    except subprocess.TimeoutExpired as exc:
        code = 124
        stdout = exc.stdout[-65536:] if isinstance(exc.stdout, str) else ""
        stderr = "command timed out"
    except OSError as exc:
        code = 127
        stdout = ""
        stderr = f"command could not start: {exc}"
    return {
        "argv": argv,
        "exit_code": code,
        "duration_ms": max(0, int((time.monotonic() - started) * 1000)),
        "stdout": stdout,
        "stderr": stderr,
    }


def _files(root: Path, names: Iterable[str], *, require: bool) -> List[Dict[str, Any]]:
    records = []
    for name in names:
        path = _safe_path(root, name)
        if not path.is_file():
            if require:
                raise EnforcementError(f"declared output missing: {name}")
            records.append({"path": name, "exists": False})
            continue
        records.append(
            {
                "path": name,
                "exists": True,
                "size": path.stat().st_size,
                "sha256": _sha_file(path),
            }
        )
    return records


def _same_run(
    before: List[Dict[str, Any]], after: List[Dict[str, Any]]
) -> Tuple[bool, str]:
    prior = {row["path"]: row for row in before}
    for row in after:
        old = prior[row["path"]]
        if old.get("exists") and old.get("sha256") == row.get("sha256"):
            return (
                False,
                f"output was not produced or changed in this attempt: {row['path']}",
            )
    return True, "same-run outputs confirmed"


def _project_digest(root: Path) -> Dict[str, str]:
    result = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] == STATE_DIR:
            continue
        result[relative.as_posix()] = _sha_file(path)
    return result


def _validate_research(receipt: Dict[str, Any], minimum: int) -> None:
    if receipt.get("verdict") != "grounded":
        raise EnforcementError("research command did not return verdict=grounded")
    source_records = receipt.get("source_records")
    if not isinstance(source_records, list):
        raise EnforcementError("research receipt has no source_records")
    source_urls = set()
    for index, source in enumerate(source_records):
        if (
            not isinstance(source, dict)
            or not isinstance(source.get("url"), str)
            or not source["url"].strip()
            or not isinstance(source.get("sha256"), str)
            or len(source["sha256"]) != 64
            or any(
                character not in "0123456789abcdef" for character in source["sha256"]
            )
            or not isinstance(source.get("chars"), int)
            or source["chars"] < 1
        ):
            raise EnforcementError(f"research source_records[{index}] is invalid")
        source_urls.add(source["url"])
    if len(source_urls) < minimum:
        raise EnforcementError(
            f"research source records do not meet min_sources={minimum}"
        )
    consensus = receipt.get("consensus")
    if not isinstance(consensus, list) or not consensus:
        raise EnforcementError("research receipt has no consensus claims")
    for index, claim in enumerate(consensus):
        if not isinstance(claim, dict) or not isinstance(claim.get("claim"), str):
            raise EnforcementError(f"research consensus[{index}] is invalid")
        citations = claim.get("citations")
        if not isinstance(citations, list) or len(set(citations)) < minimum:
            raise EnforcementError(
                f"research consensus[{index}] does not meet min_sources={minimum}"
            )
        evidence = claim.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise EnforcementError(f"research consensus[{index}] has no evidence")
        evidence_urls = set()
        for item in evidence:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("url"), str)
                or not isinstance(item.get("quote"), str)
                or not item["quote"].strip()
            ):
                raise EnforcementError(
                    f"research consensus[{index}] has malformed evidence"
                )
            evidence_urls.add(item["url"])
        if not set(citations) <= evidence_urls:
            raise EnforcementError(
                f"research consensus[{index}] citations lack evidence records"
            )
        if not set(citations) <= source_urls:
            raise EnforcementError(
                f"research consensus[{index}] citations lack hashed source records"
            )


def _pinned_files(
    root: Path, spec_path: Path, contract: Dict[str, Any]
) -> List[Dict[str, Any]]:
    names = []
    commands = [
        contract["worker"],
        contract["verifier"],
        contract["verifier"]["negative_control"],
    ]
    if contract["research"]["required"]:
        commands.append(contract["research"])
    for command in commands:
        names.extend(command["files"])
    records = _files(root, sorted(set(names)), require=True)
    records.append(
        {
            "path": spec_path.resolve().relative_to(root).as_posix(),
            "exists": True,
            "size": spec_path.stat().st_size,
            "sha256": _sha_file(spec_path),
        }
    )
    return records


def _assert_pins(root: Path, spec_path: Path, pins: List[Dict[str, Any]]) -> None:
    for record in pins:
        path = _safe_path(root, record["path"], must_exist=True)
        if not path.is_file() or _sha_file(path) != record["sha256"]:
            raise EnforcementError(f"protected control file changed: {record['path']}")


class _EventChain:
    def __init__(self, path: Path):
        self.path = path
        self.previous = ZERO_HASH
        self.count = 0

    def append(self, kind: str, data: Dict[str, Any]) -> Dict[str, Any]:
        event = {
            "sequence": self.count + 1,
            "kind": kind,
            "previous_sha256": self.previous,
            "data": data,
        }
        event["event_sha256"] = _sha_bytes(_canonical(event))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.previous = event["event_sha256"]
        self.count += 1
        return event


def _hook_events(event_dir: Path) -> List[Dict[str, Any]]:
    events = []
    if event_dir.is_dir():
        for path in sorted(event_dir.glob("*.json")):
            try:
                events.append(_read_json(path))
            except EnforcementError:
                events.append({"event_type": "invalid", "path": str(path)})
    return events


def _unresolved_tool_failures(event_dir: Path) -> List[Dict[str, Any]]:
    by_tool: Dict[str, Dict[str, Any]] = {}
    for event in _hook_events(event_dir):
        if event.get("event_type") == "completion_check":
            for pending in by_tool.values():
                pending["completion_checks"] += 1
            continue
        if event.get("event_type") != "tool_result":
            continue
        tool = event.get("tool_name", "unknown")
        if event.get("status") == "success":
            by_tool.pop(tool, None)
        elif event.get("status") == "failed":
            existing = by_tool.setdefault(
                tool,
                {
                    "tool_name": tool,
                    "failures": 0,
                    "completion_checks": 0,
                    "last_error": "tool failed",
                },
            )
            existing["failures"] += 1
            existing["completion_checks"] = 0
            existing["last_error"] = event.get("error_summary", "tool failed")
    return sorted(by_tool.values(), key=lambda row: row["tool_name"])


def _run_verifier(
    root: Path,
    verifier: Dict[str, Any],
    values: Dict[str, str],
    environment: Dict[str, str],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    negative_before = _project_digest(root)
    negative = _run_command(root, verifier["negative_control"], values, environment)
    negative_pure = negative_before == _project_digest(root)
    if negative["exit_code"] != 0 or not negative_pure:
        raise EnforcementError(
            "verifier negative control failed or changed project files"
        )
    positive_before = _project_digest(root)
    positive = _run_command(root, verifier, values, environment)
    positive_pure = positive_before == _project_digest(root)
    if not positive_pure:
        raise EnforcementError("verifier changed project files")
    return negative, positive


def run_task(root: Path, spec_path: Path) -> Dict[str, Any]:
    """Run a complete supervised task and return its host-written receipt."""
    root = root.resolve()
    spec_path = spec_path.resolve()
    try:
        spec_path.relative_to(root)
    except ValueError as exc:
        raise EnforcementError("spec must be inside task root") from exc
    contract = validate_contract(root, _read_json(spec_path))
    run_id = uuid.uuid4().hex
    run_root = root / STATE_DIR / "runs" / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    contract_hash = _sha_bytes(_canonical(contract))
    control_pins = _pinned_files(root, spec_path, contract)
    _write_json(run_root / "contract.json", contract, new=True)
    chain = _EventChain(run_root / "events.jsonl")
    chain.append("run_started", {"run_id": run_id, "contract_sha256": contract_hash})

    research_path: Optional[Path] = None
    research_record: Optional[Dict[str, Any]] = None
    common_values = {"run_id": run_id, "root": str(root)}
    base_environment = os.environ.copy()
    base_environment.update(
        {"ENFORCEMENT_RUN_ID": run_id, "ENFORCEMENT_TASK_ROOT": str(root)}
    )
    if contract["research"]["required"]:
        _assert_pins(root, spec_path, control_pins)
        research = contract["research"]
        result = _run_command(root, research, common_values, base_environment)
        _write_json(run_root / "research-command.json", result, new=True)
        if result["exit_code"] != 0:
            chain.append("research_rejected", {"exit_code": result["exit_code"]})
            return _failed_receipt(
                run_root,
                run_id,
                contract,
                contract_hash,
                chain,
                "research command failed",
            )
        try:
            research_value = json.loads(result["stdout"])
            if not isinstance(research_value, dict):
                raise ValueError("receipt is not an object")
            _validate_research(research_value, research["min_sources"])
        except (json.JSONDecodeError, ValueError, EnforcementError) as exc:
            chain.append("research_rejected", {"reason": str(exc)})
            return _failed_receipt(
                run_root,
                run_id,
                contract,
                contract_hash,
                chain,
                f"research rejected: {exc}",
            )
        research_path = _safe_path(root, research["receipt_output"])
        _write_json(research_path, research_value)
        research_record = {
            "path": research["receipt_output"],
            "sha256": _sha_file(research_path),
            "min_sources": research["min_sources"],
        }
        chain.append("research_admitted", research_record)
        _assert_pins(root, spec_path, control_pins)

    prompt_file = run_root / "prompt.txt"
    feedback_file = run_root / "feedback.txt"
    prompt_file.write_text(
        contract["objective"]
        + "\n\nRead ENFORCEMENT_FEEDBACK_FILE before each attempt."
        + (
            "\nUse only admitted research in ENFORCEMENT_RESEARCH_RECEIPT for external claims."
            if research_path
            else ""
        )
        + "\n",
        encoding="utf-8",
    )
    feedback = "No previous failure."
    attempt_records = []
    for attempt in range(1, contract["retry"]["max_attempts"] + 1):
        feedback_file.write_text(feedback + "\n", encoding="utf-8")
        event_dir = run_root / "hook-events" / f"attempt-{attempt:02d}"
        event_dir.mkdir(parents=True)
        values = {
            **common_values,
            "attempt": str(attempt),
            "prompt_file": str(prompt_file),
            "feedback_file": str(feedback_file),
            "research_receipt": str(research_path or ""),
        }
        environment = base_environment.copy()
        environment.update(
            {
                "ENFORCEMENT_ATTEMPT": str(attempt),
                "ENFORCEMENT_PROMPT_FILE": str(prompt_file),
                "ENFORCEMENT_FEEDBACK_FILE": str(feedback_file),
                "ENFORCEMENT_RESEARCH_RECEIPT": str(research_path or ""),
                "ENFORCEMENT_RESEARCH_SHA256": (
                    research_record["sha256"] if research_record else ""
                ),
                "ENFORCEMENT_HOOK_EVENT_DIR": str(event_dir),
                "ENFORCEMENT_POLICY_FILE": str(spec_path.resolve()),
            }
        )
        before = _files(root, contract["outputs"], require=False)
        chain.append("attempt_started", {"attempt": attempt})
        process = _run_command(root, contract["worker"], values, environment)
        trace_path = run_root / f"attempt-{attempt:02d}.json"
        _write_json(trace_path, process, new=True)
        issue_class: Optional[str] = None
        issue = ""
        if process["exit_code"] != 0:
            issue_class = "process_failure"
            issue = (
                f"worker exit {process['exit_code']}: "
                f"{(process['stderr'] or process['stdout'] or 'no diagnostic')[-1000:]}"
            )
        try:
            _assert_pins(root, spec_path, control_pins)
        except EnforcementError as exc:
            issue_class = "verification_failure"
            issue = str(exc)
        unresolved = _unresolved_tool_failures(event_dir)
        if issue_class is None and unresolved:
            issue_class = "tool_failure"
            issue = "unresolved inner tool failures: " + "; ".join(
                f"{row['tool_name']}: {row['last_error']}" for row in unresolved
            )
        negative: Optional[Dict[str, Any]] = None
        positive: Optional[Dict[str, Any]] = None
        outputs: List[Dict[str, Any]] = []
        if issue_class is None:
            try:
                outputs = _files(root, contract["outputs"], require=True)
                produced, produced_reason = _same_run(before, outputs)
                if not produced:
                    issue_class = "verification_failure"
                    issue = produced_reason
                else:
                    negative, positive = _run_verifier(
                        root, contract["verifier"], values, environment
                    )
                    if positive["exit_code"] != 0:
                        issue_class = "verification_failure"
                        issue = (
                            "independent verifier rejected output: "
                            + (
                                positive["stderr"]
                                or positive["stdout"]
                                or "no diagnostic"
                            )[-1000:]
                        )
            except EnforcementError as exc:
                issue_class = "verification_failure"
                issue = str(exc)

        attempt_record = {
            "attempt": attempt,
            "process_trace": trace_path.relative_to(root).as_posix(),
            "process_trace_sha256": _sha_file(trace_path),
            "tool_event_count": len(_hook_events(event_dir)),
            "unresolved_tool_failures": unresolved,
            "status": "accepted" if issue_class is None else "rejected",
            "issue_class": issue_class,
            "reason": issue,
        }
        if negative is not None:
            attempt_record["negative_control_exit_code"] = negative["exit_code"]
        if positive is not None:
            attempt_record["verifier_exit_code"] = positive["exit_code"]
        attempt_records.append(attempt_record)
        chain.append("attempt_finished", attempt_record)

        if issue_class is None:
            chain.append("run_accepted", {"attempt": attempt})
            receipt = {
                "schema_version": SCHEMA_VERSION,
                "receipt_type": "enforced_task",
                "status": "accepted",
                "authority_cap": "tested",
                "run_id": run_id,
                "task_id": contract["task_id"],
                "contract_sha256": contract_hash,
                "engine": _engine_record(),
                "control_files": control_pins,
                "accepted_attempt": attempt,
                "research": research_record,
                "outputs": outputs,
                "verifier_files": _files(
                    root, contract["verifier"]["files"], require=True
                ),
                "attempts": attempt_records,
                "event_count": chain.count,
                "event_head_sha256": chain.previous,
                "event_log": (run_root / "events.jsonl").relative_to(root).as_posix(),
            }
            receipt_path = _safe_path(root, contract["receipt_output"])
            _write_json(receipt_path, receipt)
            _write_json(run_root / "final.json", receipt, new=True)
            return receipt

        feedback = issue
        if (
            issue_class not in contract["retry"]["retry_on"]
            or attempt == contract["retry"]["max_attempts"]
        ):
            break
        pause = contract["retry"]["backoff_seconds"][
            min(attempt - 1, len(contract["retry"]["backoff_seconds"]) - 1)
        ]
        if pause:
            time.sleep(pause)

    return _failed_receipt(
        run_root,
        run_id,
        contract,
        contract_hash,
        chain,
        attempt_records[-1]["reason"] if attempt_records else "no attempt completed",
        attempt_records,
        research_record,
    )


def _failed_receipt(
    run_root: Path,
    run_id: str,
    contract: Dict[str, Any],
    contract_hash: str,
    chain: _EventChain,
    reason: str,
    attempts: Optional[List[Dict[str, Any]]] = None,
    research: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    chain.append("run_failed", {"reason": reason})
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "receipt_type": "enforced_task",
        "status": "failed",
        "authority_cap": "none",
        "run_id": run_id,
        "task_id": contract["task_id"],
        "contract_sha256": contract_hash,
        "engine": _engine_record(),
        "reason": reason,
        "research": research,
        "attempts": attempts or [],
        "event_count": chain.count,
        "event_head_sha256": chain.previous,
        "event_log": (run_root / "events.jsonl")
        .relative_to(run_root.parents[2])
        .as_posix(),
    }
    _write_json(run_root / "final.json", receipt, new=True)
    return receipt


def _verify_event_chain(path: Path, count: int, head: str) -> None:
    previous = ZERO_HASH
    seen = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise EnforcementError(f"cannot read event log: {exc}") from exc
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EnforcementError(f"invalid event log JSON: {exc}") from exc
        if not isinstance(event, dict):
            raise EnforcementError("event log row must be an object")
        claimed = event.pop("event_sha256", None)
        if (
            event.get("sequence") != seen + 1
            or event.get("previous_sha256") != previous
        ):
            raise EnforcementError("event log order or previous hash is invalid")
        actual = _sha_bytes(_canonical(event))
        if claimed != actual:
            raise EnforcementError("event log hash is invalid")
        previous = actual
        seen += 1
    if seen != count or previous != head:
        raise EnforcementError("event log count or head does not match receipt")


def verify_receipt(
    root: Path, spec_path: Path, receipt_path: Path, *, negative_control: bool = False
) -> Dict[str, Any]:
    """Independently re-derive a final task receipt against live bytes."""
    root = root.resolve()
    spec_path = spec_path.resolve()
    receipt_path = receipt_path.resolve()
    try:
        spec_path.relative_to(root)
        receipt_path.relative_to(root)
    except ValueError as exc:
        raise EnforcementError("spec and receipt must be inside task root") from exc
    contract = validate_contract(root, _read_json(spec_path))
    receipt = _read_json(receipt_path)
    if negative_control:
        receipt = copy.deepcopy(receipt)
        receipt["contract_sha256"] = ZERO_HASH

    if receipt.get("status") != "accepted" or receipt.get("authority_cap") != "tested":
        raise EnforcementError("receipt is not an accepted tested task")
    if receipt.get("task_id") != contract["task_id"]:
        raise EnforcementError("receipt task_id does not match contract")
    if receipt.get("contract_sha256") != _sha_bytes(_canonical(contract)):
        raise EnforcementError("receipt contract hash does not match live contract")
    if receipt.get("engine") != _engine_record():
        raise EnforcementError("enforcement engine bytes do not match receipt")
    if receipt_path != _safe_path(root, contract["receipt_output"]):
        raise EnforcementError("receipt path does not match contract")

    expected_outputs = {
        row["path"]: row for row in _files(root, contract["outputs"], require=True)
    }
    received_outputs = {
        row.get("path"): row
        for row in receipt.get("outputs", [])
        if isinstance(row, dict)
    }
    if received_outputs != expected_outputs:
        raise EnforcementError("live output bytes do not match receipt")

    expected_pins = _pinned_files(root, spec_path, contract)
    if receipt.get("control_files") != expected_pins:
        raise EnforcementError("live control files do not match receipt")
    research_record = receipt.get("research")
    if contract["research"]["required"]:
        if not isinstance(research_record, dict):
            raise EnforcementError("required research record is missing")
        research_path = _safe_path(
            root, contract["research"]["receipt_output"], must_exist=True
        )
        if research_record.get("sha256") != _sha_file(research_path):
            raise EnforcementError("research receipt bytes changed")
        _validate_research(
            _read_json(research_path), contract["research"]["min_sources"]
        )
    elif research_record is not None:
        raise EnforcementError("receipt claims research not required by contract")

    attempts = receipt.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise EnforcementError("receipt has no attempt trail")
    accepted = receipt.get("accepted_attempt")
    if (
        accepted != attempts[-1].get("attempt")
        or attempts[-1].get("status") != "accepted"
    ):
        raise EnforcementError("accepted attempt does not match attempt trail")
    for attempt in attempts:
        trace = _safe_path(root, attempt.get("process_trace"), must_exist=True)
        if attempt.get("process_trace_sha256") != _sha_file(trace):
            raise EnforcementError("process trace bytes changed")
    event_log = _safe_path(root, receipt.get("event_log"), must_exist=True)
    _verify_event_chain(
        event_log, receipt.get("event_count"), receipt.get("event_head_sha256")
    )
    return {
        "status": "verified",
        "task_id": contract["task_id"],
        "run_id": receipt["run_id"],
        "authority_cap": "tested",
    }


def normalize_hook_event(host: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Translate Claude, Hermes, or already-normalized hook data."""
    if host == "normalized":
        event = dict(payload)
    elif host == "claude":
        kind = payload.get("hook_event_name")
        if kind == "PostToolUseFailure":
            event = {
                "event_type": "tool_result",
                "status": "failed",
                "tool_name": payload.get("tool_name", "unknown"),
                "tool_input": payload.get("tool_input", {}),
                "error_summary": payload.get("error", "tool failed"),
            }
        elif kind == "PostToolUse":
            event = {
                "event_type": "tool_result",
                "status": "success",
                "tool_name": payload.get("tool_name", "unknown"),
                "tool_input": payload.get("tool_input", {}),
            }
        elif kind == "Stop":
            event = {"event_type": "completion_check"}
        else:
            event = {"event_type": "ignored", "host_event": kind}
    elif host == "hermes":
        kind = payload.get("hook_event_name")
        extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
        if kind == "post_tool_call":
            failed = bool(extra.get("error_type")) or extra.get("status") in {
                "error",
                "failed",
                "blocked",
            }
            event = {
                "event_type": "tool_result",
                "status": "failed" if failed else "success",
                "tool_name": payload.get("tool_name", "unknown"),
                "tool_input": payload.get("tool_input", {}),
                "error_summary": extra.get("error_message", "tool failed"),
            }
        elif kind == "pre_verify":
            event = {"event_type": "completion_check"}
        else:
            event = {"event_type": "ignored", "host_event": kind}
    else:
        raise EnforcementError(f"unsupported hook host: {host}")
    if event.get("event_type") == "tool_result":
        event["tool_input_sha256"] = _sha_bytes(_canonical(event.pop("tool_input", {})))
        event["error_summary"] = str(event.get("error_summary", ""))[:500]
    return event


def handle_hook(
    host: str, payload: Dict[str, Any], environment: Dict[str, str]
) -> Dict[str, Any]:
    """Record one host event and return the host-specific completion directive."""
    event_dir_value = environment.get("ENFORCEMENT_HOOK_EVENT_DIR")
    policy_value = environment.get("ENFORCEMENT_POLICY_FILE")
    if not event_dir_value or not policy_value:
        raise EnforcementError("enforcement hook environment is not active")
    event_dir = Path(event_dir_value).resolve()
    contract = validate_contract(
        Path(environment.get("ENFORCEMENT_TASK_ROOT", Path.cwd())).resolve(),
        _read_json(Path(policy_value).resolve()),
    )
    event = normalize_hook_event(host, payload)
    event["recorded_ns"] = time.time_ns()
    event_path = event_dir / f"{event['recorded_ns']:020d}-{uuid.uuid4().hex}.json"
    _write_json(event_path, event, new=True)
    if event["event_type"] != "completion_check":
        return {}
    unresolved = _unresolved_tool_failures(event_dir)
    reasons = []
    if contract["research"]["required"]:
        research_path = Path(environment.get("ENFORCEMENT_RESEARCH_RECEIPT", ""))
        expected_research_hash = environment.get("ENFORCEMENT_RESEARCH_SHA256", "")
        if not research_path.is_file() or len(expected_research_hash) != 64:
            reasons.append("required admitted research receipt is missing")
        elif _sha_file(research_path) != expected_research_hash:
            reasons.append("admitted research receipt bytes changed")
        else:
            try:
                _validate_research(
                    _read_json(research_path), contract["research"]["min_sources"]
                )
            except (EnforcementError, json.JSONDecodeError) as exc:
                reasons.append(f"admitted research receipt is invalid: {exc}")
    inner_max = contract["retry"]["inner_tool_max_attempts"]
    for row in unresolved:
        if row["completion_checks"] <= inner_max:
            prefix = (
                "Inspect state before correcting"
                if row["tool_name"] in contract["retry"]["side_effecting_tools"]
                else "Retry or correct"
            )
            reasons.append(
                f"{prefix} failed tool {row['tool_name']}: {row['last_error']}"
            )
    if not reasons:
        return {}
    reason = "; ".join(reasons)
    if host == "claude":
        return {"decision": "block", "reason": reason}
    if host == "hermes":
        return {"action": "continue", "message": reason}
    return {"allow": False, "action": "continue", "reason": reason}


def _cli() -> int:
    parser = argparse.ArgumentParser(
        description="portable agent enforcement supervisor"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    doctor_parser = sub.add_parser("doctor")
    doctor_parser.add_argument("--root", type=Path, required=True)
    doctor_parser.add_argument("--spec", type=Path, required=True)
    dry_run_parser = sub.add_parser("dry-run")
    dry_run_parser.add_argument("--root", type=Path, required=True)
    dry_run_parser.add_argument("--spec", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--root", type=Path, required=True)
    run_parser.add_argument("--spec", type=Path, required=True)
    verify_parser = sub.add_parser("verify-receipt")
    verify_parser.add_argument("--root", type=Path, required=True)
    verify_parser.add_argument("--spec", type=Path, required=True)
    verify_parser.add_argument("--receipt", type=Path, required=True)
    verify_parser.add_argument("--negative-control", action="store_true")
    hook_parser = sub.add_parser("hook")
    hook_parser.add_argument(
        "--host", choices=["claude", "hermes", "normalized"], required=True
    )
    args = parser.parse_args()
    try:
        if args.command in {"doctor", "dry-run"}:
            result = doctor(args.root, args.spec)
            code = 0 if result["ready"] else 2
        elif args.command == "run":
            result = run_task(args.root, args.spec)
            code = 0 if result["status"] == "accepted" else 1
        elif args.command == "verify-receipt":
            if args.negative_control:
                try:
                    verify_receipt(
                        args.root,
                        args.spec,
                        args.receipt,
                        negative_control=True,
                    )
                except EnforcementError as exc:
                    result = {"status": "negative_control_pass", "reason": str(exc)}
                    code = 0
                else:
                    result = {
                        "status": "negative_control_failed",
                        "reason": "deliberately invalid receipt was accepted",
                    }
                    code = 1
            else:
                result = verify_receipt(args.root, args.spec, args.receipt)
                code = 0
        else:
            try:
                payload = json.load(sys.stdin)
            except (json.JSONDecodeError, OSError) as exc:
                raise EnforcementError(f"invalid hook JSON: {exc}") from exc
            if not isinstance(payload, dict):
                raise EnforcementError("hook payload must be a JSON object")
            result = handle_hook(args.host, payload, os.environ.copy())
            code = 0
    except EnforcementError as exc:
        parser.exit(2, f"ENFORCEMENT HOLD: {exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return code


main = _cli


if __name__ == "__main__":
    raise SystemExit(_cli())
