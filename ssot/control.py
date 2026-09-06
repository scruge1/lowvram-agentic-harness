"""Small, harness-neutral blessed-SSOT reference implementation.

The worker can be Pi, Claude, Codex, Qwen, a shell script, or a person. Workers
only create project outputs. This host process owns work orders, byte hashes,
producer receipts, verifier execution, the event chain, and derived status.

This is local tamper evidence, not protection from an administrator who can
rewrite both evidence and code. Put signing or remote custody outside this
module when that stronger trust boundary is required.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple, Union


SCHEMA_VERSION = 1
STATE_DIR = ".ssot"
AUTHORITY = ("scaffolded", "compiled", "configured", "enforced", "tested")
REQUIREMENT_DISPOSITIONS = ("applicable", "unresolved", "waived", "superseded")
REQUIREMENT_SCOPES = ("universal", "project_specific", "not_yet_understood")
WAIVER_TYPES = ("not_applicable", "risk_accepted", "external_replacement")
RUNTIME_KINDS = ("local_model", "remote_model", "script", "person")
VERIFIER_TYPES = ("deterministic_property", "test_suite", "independent_review")
_PROCESS_LOCKS: Dict[str, threading.Lock] = {}


class SSOTError(RuntimeError):
    """A fail-closed SSOT contract error."""


@contextmanager
def _controller_lock(root: Path) -> Iterator[None]:
    """Take one non-blocking process and OS lock for controller mutations."""
    root = root.resolve()
    key = str(root).casefold()
    process_lock = _PROCESS_LOCKS.setdefault(key, threading.Lock())
    if not process_lock.acquire(blocking=False):
        raise SSOTError("another controller mutation is active")
    lock_path = root / STATE_DIR / "controller.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            raise SSOTError("another controller process is active") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()
        process_lock.release()


def _mutating(function: Callable[..., Dict[str, Any]]) -> Callable[..., Dict[str, Any]]:
    @wraps(function)
    def guarded(root: Union[Path, str], *args: Any, **kwargs: Any) -> Dict[str, Any]:
        resolved = Path(root).resolve()
        with _controller_lock(resolved):
            return function(resolved, *args, **kwargs)

    return guarded


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
        raise SSOTError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SSOTError(f"JSON root must be an object: {path}")
    return value


def _write_new_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise SSOTError(f"refusing to overwrite immutable record: {path}") from exc


def _safe_path(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise SSOTError(f"path must be non-empty and relative: {relative!r}")
    unresolved = root / relative
    candidate = unresolved.resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise SSOTError(f"path escapes project root: {relative}") from exc
    if (
        candidate == (root / STATE_DIR).resolve()
        or (root / STATE_DIR).resolve() in candidate.parents
    ):
        raise SSOTError(
            f"project input/output cannot be inside {STATE_DIR}: {relative}"
        )
    if must_exist and not candidate.is_file():
        raise SSOTError(f"required file is absent: {relative}")
    root_resolved = root.resolve()
    current = unresolved
    while current != root_resolved:
        if current.is_symlink():
            raise SSOTError(f"symlinks are not accepted as evidence: {relative}")
        current = current.parent
    if candidate.is_symlink():
        raise SSOTError(f"symlinks are not accepted as evidence: {relative}")
    return candidate


def _file_records(
    root: Path, paths: Iterable[str], *, require: bool = True
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for relative in sorted(set(paths)):
        path = _safe_path(root, relative, must_exist=require)
        if not path.exists():
            records.append({"path": relative, "exists": False})
        elif not path.is_file():
            raise SSOTError(f"only exact files are supported: {relative}")
        else:
            stat = path.stat()
            records.append(
                {
                    "path": relative,
                    "exists": True,
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "sha256": _sha_file(path),
                }
            )
    return records


def _content_projection(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {k: row[k] for k in ("path", "exists", "size", "sha256") if k in row}
        for row in records
    ]


def _records_digest(records: List[Dict[str, Any]]) -> str:
    return _sha_bytes(_canonical(_content_projection(records)))


def _load_project(root: Path) -> Tuple[Dict[str, Any], Path, str]:
    root = root.resolve()
    path = root / "ssot-project.json"
    project = _read_json(path)
    _validate_project(project, root)
    return project, path, _sha_file(path)


def _require_strings(value: Any, label: str, *, nonempty: bool = True) -> List[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise SSOTError(f"{label} must be a {'non-empty ' if nonempty else ''}list")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise SSOTError(f"{label} must contain non-empty strings")
    if len(value) != len(set(value)):
        raise SSOTError(f"{label} contains duplicates")
    return value


def _validate_runtime(runtime: Dict[str, Any]) -> None:
    if not isinstance(runtime, dict):
        raise SSOTError("runtime identity must be an object")
    kind = runtime.get("kind")
    if kind not in RUNTIME_KINDS:
        raise SSOTError(f"runtime.kind must be one of {RUNTIME_KINDS}")
    for field in ("executor", "harness", "harness_version"):
        if not isinstance(runtime.get(field), str) or not runtime[field].strip():
            raise SSOTError(f"runtime.{field} is required")
    if runtime.get("host_observed") is not True:
        raise SSOTError("runtime.host_observed must be true")
    if not isinstance(runtime.get("attempt"), int) or runtime["attempt"] < 1:
        raise SSOTError("runtime.attempt must be a positive integer")
    fallback = runtime.get("fallback_from")
    if fallback is not None and (not isinstance(fallback, str) or not fallback.strip()):
        raise SSOTError("runtime.fallback_from must be null or a non-empty run id")
    if kind not in ("local_model", "remote_model"):
        return
    for field in (
        "provider_family",
        "model_family",
        "checkpoint",
        "served_model_id",
        "backend",
        "quant",
        "endpoint",
        "system_prompt_sha256",
        "context_sha256",
    ):
        if not isinstance(runtime.get(field), str) or not runtime[field].strip():
            raise SSOTError(f"runtime.{field} is required for model calls")
    for field in ("system_prompt_sha256", "context_sha256"):
        value = runtime[field]
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise SSOTError(f"runtime.{field} must be a lowercase SHA-256 digest")
    if not isinstance(runtime.get("sampling"), dict):
        raise SSOTError("runtime.sampling must be an object for model calls")


def _validate_execution(
    root: Path,
    stage: Dict[str, Any],
    runtime: Dict[str, Any],
    execution: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(execution, dict):
        raise SSOTError("execution receipt must be an object")
    if execution.get("host_observed") is not True:
        raise SSOTError("execution.host_observed must be true")
    if execution.get("status") != "completed":
        raise SSOTError("only a completed execution can submit products")
    duration = execution.get("duration_ms")
    if isinstance(duration, bool) or not isinstance(duration, int) or duration < 0:
        raise SSOTError("execution.duration_ms must be a non-negative integer")
    outputs = set(stage["outputs"])

    def bound_file(field: str) -> Dict[str, Any]:
        relative = execution.get(field)
        if not isinstance(relative, str) or relative not in outputs:
            raise SSOTError(f"execution.{field} must name one declared stage output")
        return _content_projection(_file_records(root, [relative], require=True))[0]

    normalized = dict(execution)
    normalized["trace"] = bound_file("trace_file")
    if runtime["kind"] not in ("local_model", "remote_model"):
        return normalized
    call_id = execution.get("model_call_id")
    if not isinstance(call_id, str) or not call_id.strip():
        raise SSOTError("execution.model_call_id is required for model calls")
    for field in (
        "input_bytes",
        "output_bytes",
        "prompt_tokens",
        "completion_tokens",
    ):
        value = execution.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SSOTError(
                f"execution.{field} must be a non-negative integer for model calls"
            )
    if not isinstance(execution.get("tool_calls"), list):
        raise SSOTError("execution.tool_calls must be a list for model calls")
    normalized["raw_output"] = bound_file("raw_output_file")
    normalized["parsed_output"] = bound_file("parsed_output_file")
    return normalized


def _validate_negative_control(
    command: Dict[str, Any], positive_argv: List[str], label: str
) -> None:
    if not isinstance(command, dict):
        raise SSOTError(f"{label}.negative_control is required")
    argv = command.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(arg, str) and arg for arg in argv)
    ):
        raise SSOTError(f"{label}.negative_control.argv must be a string list")
    if argv == positive_argv:
        raise SSOTError(f"{label}.negative_control must use a distinct invocation")
    shared_prefix = 2 if positive_argv[0] == "{python}" else 1
    if argv[:shared_prefix] != positive_argv[:shared_prefix]:
        raise SSOTError(
            f"{label}.negative_control must exercise the same verifier program"
        )
    timeout = command.get("timeout_seconds", 60)
    if not isinstance(timeout, int) or timeout < 1 or timeout > 3600:
        raise SSOTError(f"{label}.negative_control.timeout_seconds must be 1..3600")


def _validate_project(project: Dict[str, Any], root: Path) -> None:
    if project.get("schema_version") != SCHEMA_VERSION:
        raise SSOTError(f"schema_version must be {SCHEMA_VERSION}")
    if (
        not isinstance(project.get("project_id"), str)
        or not project["project_id"].strip()
    ):
        raise SSOTError("project_id is required")
    cap = project.get("authority_cap", "tested")
    if cap == "blessed":
        raise SSOTError(
            "local authority cannot be blessed; use an external trust provider"
        )
    if cap not in AUTHORITY:
        raise SSOTError(f"invalid authority_cap: {cap!r}")
    target = project.get("target")
    if (
        not isinstance(target, dict)
        or not isinstance(target.get("files"), list)
        or not target["files"]
    ):
        raise SSOTError("target.files must contain at least one exact relative file")
    target_files = _require_strings(target["files"], "target.files")
    _file_records(root, target_files, require=True)

    stages = project.get("stages")
    if not isinstance(stages, list) or not stages:
        raise SSOTError("stages must be a non-empty list")
    ids: set[str] = set()
    outputs: set[str] = set()
    verifier_owners: set[str] = set()
    for stage in stages:
        if not isinstance(stage, dict):
            raise SSOTError("every stage must be an object")
        stage_id = stage.get("id")
        if not isinstance(stage_id, str) or not stage_id or stage_id in ids:
            raise SSOTError(f"stage id is missing or duplicated: {stage_id!r}")
        ids.add(stage_id)
        for field in ("objective", "acceptance"):
            if not isinstance(stage.get(field), str) or not stage[field].strip():
                raise SSOTError(f"{stage_id}.{field} is required")
        _require_strings(
            stage.get("depends_on", []), f"{stage_id}.depends_on", nonempty=False
        )
        materials = _require_strings(stage.get("materials"), f"{stage_id}.materials")
        for material in materials:
            _safe_path(root, material)
        _require_strings(stage.get("requirements"), f"{stage_id}.requirements")
        _require_strings(stage.get("properties"), f"{stage_id}.properties")
        stage_outputs = _require_strings(stage.get("outputs"), f"{stage_id}.outputs")
        for output in stage_outputs:
            _safe_path(root, output)
            if output in outputs:
                raise SSOTError(f"output has more than one producer: {output}")
            outputs.add(output)
        verifier = stage.get("verifier")
        if not isinstance(verifier, dict):
            raise SSOTError(f"{stage_id}.verifier is required")
        if not isinstance(verifier.get("owner"), str) or not verifier["owner"].strip():
            raise SSOTError(f"{stage_id}.verifier.owner is required")
        verifier_owners.add(verifier["owner"].casefold())
        if verifier.get("type") not in VERIFIER_TYPES:
            raise SSOTError(f"{stage_id}.verifier.type must be one of {VERIFIER_TYPES}")
        argv = verifier.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(arg, str) and arg for arg in argv)
        ):
            raise SSOTError(f"{stage_id}.verifier.argv must be a non-empty string list")
        files = _require_strings(
            verifier.get("files", []), f"{stage_id}.verifier.files"
        )
        _file_records(root, files, require=True)
        timeout = verifier.get("timeout_seconds", 60)
        if not isinstance(timeout, int) or timeout < 1 or timeout > 3600:
            raise SSOTError(f"{stage_id}.verifier.timeout_seconds must be 1..3600")
        _validate_negative_control(
            verifier.get("negative_control"), argv, f"{stage_id}.verifier"
        )

    for stage in stages:
        for dependency in stage.get("depends_on", []):
            if dependency not in ids or dependency == stage["id"]:
                raise SSOTError(f"invalid dependency {dependency!r} for {stage['id']}")
            dependency_outputs = set(
                next(row["outputs"] for row in stages if row["id"] == dependency)
            )
            if not dependency_outputs <= set(stage["materials"]):
                missing = sorted(dependency_outputs - set(stage["materials"]))
                raise SSOTError(
                    f"{stage['id']}.materials omits dependency products: {missing}"
                )
    _topological_stages(project)

    requirements = project.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        raise SSOTError("requirements must be a non-empty conserved inventory")
    requirement_ids: set[str] = set()
    applicable_owners: Dict[str, str] = {}
    waiver_approvers: set[str] = set()
    target_file_set = set(target_files)
    for requirement in requirements:
        if not isinstance(requirement, dict):
            raise SSOTError("every requirement must be an object")
        requirement_id = requirement.get("id")
        if (
            not isinstance(requirement_id, str)
            or not requirement_id.strip()
            or requirement_id in requirement_ids
        ):
            raise SSOTError(
                f"requirement id is missing or duplicated: {requirement_id!r}"
            )
        requirement_ids.add(requirement_id)
        scope_class = requirement.get("scope_class")
        if scope_class not in REQUIREMENT_SCOPES:
            raise SSOTError(
                f"{requirement_id}.scope_class must be one of {REQUIREMENT_SCOPES}"
            )
        if (
            not isinstance(requirement.get("text"), str)
            or not requirement["text"].strip()
        ):
            raise SSOTError(f"{requirement_id}.text is required")
        source = requirement.get("source")
        if (
            not isinstance(source, dict)
            or source.get("path") not in target_file_set
            or not isinstance(source.get("locator"), str)
            or not source["locator"].strip()
        ):
            raise SSOTError(
                f"{requirement_id}.source must name a target path and stable locator"
            )
        source_hash = source.get("sha256")
        if (
            not isinstance(source_hash, str)
            or len(source_hash) != 64
            or any(char not in "0123456789abcdef" for char in source_hash)
        ):
            raise SSOTError(f"{requirement_id}.source.sha256 must be a SHA-256 digest")
        source_path = _safe_path(root, source["path"], must_exist=True)
        if _sha_file(source_path) != source_hash:
            raise SSOTError(f"source bytes changed for requirement {requirement_id}")
        disposition = requirement.get("disposition")
        if disposition not in REQUIREMENT_DISPOSITIONS:
            raise SSOTError(
                f"invalid disposition for {requirement_id}: {disposition!r}"
            )
        if scope_class == "not_yet_understood" and disposition != "unresolved":
            raise SSOTError(
                f"not-yet-understood requirement {requirement_id} must stay unresolved"
            )
        if disposition == "applicable":
            owner = requirement.get("owner_stage")
            if owner not in ids:
                raise SSOTError(f"{requirement_id}.owner_stage must name one stage")
            applicable_owners[requirement_id] = owner
        elif disposition == "waived":
            if (
                not isinstance(requirement.get("reason"), str)
                or not requirement["reason"].strip()
            ):
                raise SSOTError(f"waived requirement {requirement_id} needs a reason")
            if requirement.get("waiver_type") not in WAIVER_TYPES:
                raise SSOTError(
                    f"waived requirement {requirement_id} needs a typed waiver"
                )
            approver = requirement.get("approved_by")
            if not isinstance(approver, str) or not approver.strip():
                raise SSOTError(
                    f"waived requirement {requirement_id} needs approved_by"
                )
            if approver.casefold() in verifier_owners:
                raise SSOTError(
                    f"waiver approver for {requirement_id} must be independent"
                )
            waiver_approvers.add(approver.casefold())
            evidence = _require_strings(
                requirement.get("evidence"), f"{requirement_id}.evidence"
            )
            _file_records(root, evidence, require=True)
        elif disposition == "superseded":
            if not isinstance(requirement.get("superseded_by"), str):
                raise SSOTError(
                    f"superseded requirement {requirement_id} needs superseded_by"
                )
            for field in ("reason", "approved_by"):
                if (
                    not isinstance(requirement.get(field), str)
                    or not requirement[field].strip()
                ):
                    raise SSOTError(
                        f"superseded requirement {requirement_id} needs {field}"
                    )
            if requirement["approved_by"].casefold() in verifier_owners:
                raise SSOTError(
                    f"supersession approver for {requirement_id} must be independent"
                )
            waiver_approvers.add(requirement["approved_by"].casefold())
            evidence = _require_strings(
                requirement.get("evidence"), f"{requirement_id}.evidence"
            )
            _file_records(root, evidence, require=True)

    for requirement in requirements:
        replacement = requirement.get("superseded_by")
        if replacement is not None and (
            replacement not in requirement_ids or replacement == requirement["id"]
        ):
            raise SSOTError(f"invalid superseded_by for {requirement['id']}")
    superseded = {
        row["id"]: row["superseded_by"]
        for row in requirements
        if row["disposition"] == "superseded"
    }
    for requirement_id in superseded:
        seen: set[str] = set()
        current = requirement_id
        while current in superseded:
            if current in seen:
                raise SSOTError(f"supersession cycle includes {current}")
            seen.add(current)
            current = superseded[current]
    declared: Dict[str, str] = {}
    for stage in stages:
        for requirement_id in stage["requirements"]:
            if requirement_id in declared:
                raise SSOTError(
                    f"requirement has multiple stage owners: {requirement_id}"
                )
            declared[requirement_id] = stage["id"]
    if declared != applicable_owners:
        raise SSOTError(
            "stage requirement declarations must exactly match applicable requirement owners"
        )

    acceptance = project.get("acceptance")
    if not isinstance(acceptance, dict):
        raise SSOTError("acceptance must be an object")
    if acceptance is not None:
        if (
            not isinstance(acceptance.get("owner"), str)
            or not acceptance["owner"].strip()
        ):
            raise SSOTError("acceptance.owner is required")
        if acceptance["owner"].casefold() in verifier_owners:
            raise SSOTError(
                "acceptance owner must be independent from stage verifier owners"
            )
        if acceptance["owner"].casefold() in waiver_approvers:
            raise SSOTError(
                "acceptance owner must differ from waiver and supersession approvers"
            )
        argv = acceptance.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(arg, str) and arg for arg in argv)
        ):
            raise SSOTError("acceptance.argv must be a non-empty string list")
        if acceptance.get("type") not in VERIFIER_TYPES:
            raise SSOTError(f"acceptance.type must be one of {VERIFIER_TYPES}")
        files = _require_strings(acceptance.get("files", []), "acceptance.files")
        _file_records(root, files, require=True)
        timeout = acceptance.get("timeout_seconds", 60)
        if not isinstance(timeout, int) or timeout < 1 or timeout > 3600:
            raise SSOTError("acceptance.timeout_seconds must be 1..3600")
        _validate_negative_control(
            acceptance.get("negative_control"), argv, "acceptance"
        )


def _stage_map(project: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {stage["id"]: stage for stage in project["stages"]}


def _topological_stages(project: Dict[str, Any]) -> List[Dict[str, Any]]:
    stages = _stage_map(project)
    pending = set(stages)
    resolved: set[str] = set()
    ordered: List[Dict[str, Any]] = []
    while pending:
        ready = sorted(
            stage_id
            for stage_id in pending
            if set(stages[stage_id].get("depends_on", [])) <= resolved
        )
        if not ready:
            raise SSOTError("stage dependency graph contains a cycle")
        for stage_id in ready:
            ordered.append(stages[stage_id])
            resolved.add(stage_id)
            pending.remove(stage_id)
    return ordered


def _state_path(root: Path, kind: str, run_id: str) -> Path:
    if not run_id or any(char not in "0123456789abcdef-" for char in run_id.lower()):
        raise SSOTError(f"invalid run id: {run_id!r}")
    return root / STATE_DIR / kind / f"{run_id}.json"


def _append_event(root: Path, event_type: str, body: Dict[str, Any]) -> Dict[str, Any]:
    state = root / STATE_DIR
    state.mkdir(parents=True, exist_ok=True)
    path = state / "events.jsonl"
    previous = "0" * 64
    sequence = 1
    if path.exists():
        events = _verify_event_chain(path)
        if events:
            previous = events[-1]["event_hash"]
            sequence = events[-1]["sequence"] + 1
    event = {
        "sequence": sequence,
        "time": _utc_now(),
        "type": event_type,
        "previous_event_hash": previous,
        "body": body,
    }
    event["event_hash"] = _sha_bytes(_canonical(event))
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return event


def _verify_event_chain(path: Path) -> List[Dict[str, Any]]:
    previous = "0" * 64
    events: List[Dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SSOTError(f"cannot read event chain: {exc}") from exc
    for index, line in enumerate(lines, 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SSOTError(f"invalid event JSON at line {index}") from exc
        claimed = event.pop("event_hash", None)
        actual = _sha_bytes(_canonical(event))
        event["event_hash"] = claimed
        if (
            event.get("sequence") != index
            or event.get("previous_event_hash") != previous
            or claimed != actual
        ):
            raise SSOTError(f"event chain failed at line {index}")
        previous = claimed
        events.append(event)
    return events


def _project_digest(root: Path) -> str:
    rows: List[Dict[str, Any]] = []
    state_root = (root / STATE_DIR).resolve()
    for path in sorted(root.rglob("*")):
        resolved = path.resolve()
        if resolved == state_root or state_root in resolved.parents:
            continue
        if path.is_symlink():
            raise SSOTError(
                f"project contains a symlink outside state: {path.relative_to(root)}"
            )
        if path.is_file():
            rows.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": _sha_file(path),
                }
            )
    return _sha_bytes(_canonical(rows))


def _records_equal(left: List[Dict[str, Any]], right: List[Dict[str, Any]]) -> bool:
    return _content_projection(left) == _content_projection(right)


def _all_records(root: Path, kind: str) -> List[Tuple[Path, Dict[str, Any]]]:
    directory = root / STATE_DIR / kind
    if not directory.exists():
        return []
    records = [(path, _read_json(path)) for path in directory.glob("*.json")]
    return sorted(
        records, key=lambda item: (item[1].get("created_at", ""), item[0].name)
    )


def _latest_work_order(
    root: Path, stage_id: str
) -> Optional[Tuple[Path, Dict[str, Any]]]:
    matches = [
        (path, row)
        for path, row in _all_records(root, "work-orders")
        if row.get("stage_id") == stage_id
    ]
    return matches[-1] if matches else None


def _terminal(root: Path, run_id: str) -> bool:
    return any(
        _state_path(root, kind, run_id).exists()
        for kind in ("verification", "abandoned")
    )


def _live_verifications(
    root: Path, project: Dict[str, Any], manifest_hash: str
) -> Dict[str, Dict[str, Any]]:
    target_records = _file_records(root, project["target"]["files"], require=True)
    target_digest = _records_digest(target_records)
    by_run = {
        path.stem: row
        for path, row in _all_records(root, "verification")
        if row.get("status") == "verified"
    }
    live: Dict[str, Dict[str, Any]] = {}
    for stage in _topological_stages(project):
        candidates = [
            row for row in by_run.values() if row.get("stage_id") == stage["id"]
        ]
        candidates.sort(key=lambda row: row.get("created_at", ""), reverse=True)
        for receipt in candidates:
            run_id = receipt.get("run_id", "")
            work_path = _state_path(root, "work-orders", run_id)
            producer_path = _state_path(root, "producer-receipts", run_id)
            if not work_path.exists() or not producer_path.exists():
                continue
            work = _read_json(work_path)
            if (
                receipt.get("manifest_sha256") != manifest_hash
                or work.get("manifest_sha256") != manifest_hash
            ):
                continue
            if (
                receipt.get("target_digest") != target_digest
                or work.get("target_digest") != target_digest
            ):
                continue
            if receipt.get("work_order_sha256") != _sha_file(work_path):
                continue
            if receipt.get("producer_receipt_sha256") != _sha_file(producer_path):
                continue
            current_outputs = _file_records(root, stage["outputs"], require=True)
            if not _records_equal(current_outputs, receipt.get("outputs", [])):
                continue
            current_materials = _file_records(root, stage["materials"], require=True)
            if not _records_equal(current_materials, receipt.get("materials", [])):
                continue
            verifier_files = stage["verifier"].get("files", [])
            current_verifiers = _file_records(root, verifier_files, require=True)
            if not _records_equal(current_verifiers, receipt.get("verifier_files", [])):
                continue
            expected_dependencies = receipt.get("dependency_verifications", {})
            if set(expected_dependencies) != set(stage.get("depends_on", [])):
                continue
            if any(
                dep not in live
                or expected_dependencies[dep] != live[dep]["receipt_sha256"]
                for dep in expected_dependencies
            ):
                continue
            copy = dict(receipt)
            copy["receipt_path"] = str(_state_path(root, "verification", run_id))
            copy["receipt_sha256"] = _sha_file(
                _state_path(root, "verification", run_id)
            )
            live[stage["id"]] = copy
            break
    return live


def _requirement_status(project: Dict[str, Any]) -> Dict[str, Any]:
    counts = {name: 0 for name in REQUIREMENT_DISPOSITIONS}
    unresolved: List[str] = []
    for requirement in project["requirements"]:
        disposition = requirement["disposition"]
        counts[disposition] += 1
        if disposition == "unresolved":
            unresolved.append(requirement["id"])
    return {
        "counts": counts,
        "unresolved": sorted(unresolved),
        "conserved": not unresolved,
    }


def project_status(root: Union[Path, str]) -> Dict[str, Any]:
    root = Path(root).resolve()
    project, _, manifest_hash = _load_project(root)
    event_path = root / STATE_DIR / "events.jsonl"
    event_count = len(_verify_event_chain(event_path)) if event_path.exists() else 0
    live = _live_verifications(root, project, manifest_hash)
    stages = []
    for stage in _topological_stages(project):
        latest = _latest_work_order(root, stage["id"])
        if stage["id"] in live:
            state = "verified"
        elif latest and not _terminal(root, latest[1]["run_id"]):
            state = "in_progress"
        elif all(dependency in live for dependency in stage.get("depends_on", [])):
            state = "frontier"
        else:
            state = "blocked"
        stages.append(
            {
                "id": stage["id"],
                "state": state,
                "depends_on": stage.get("depends_on", []),
            }
        )

    all_verified = len(live) == len(project["stages"])
    requirement_status = _requirement_status(project)
    acceptance_live = False
    acceptance_path: Optional[Path] = None
    if all_verified and requirement_status["conserved"]:
        stage_hashes = {
            stage_id: row["receipt_sha256"] for stage_id, row in live.items()
        }
        for path, receipt in reversed(_all_records(root, "acceptance")):
            if (
                receipt.get("status") == "accepted"
                and receipt.get("manifest_sha256") == manifest_hash
                and receipt.get("stage_verifications") == stage_hashes
                and _records_equal(
                    _file_records(
                        root,
                        project.get("acceptance", {}).get("files", []),
                        require=True,
                    ),
                    receipt.get("acceptance_files", []),
                )
            ):
                acceptance_live = True
                acceptance_path = path
                break
    cap = project.get("authority_cap", "tested")
    if acceptance_live:
        intrinsic_authority = "tested"
    elif all_verified:
        intrinsic_authority = "enforced"
    elif event_count:
        intrinsic_authority = "configured"
    else:
        intrinsic_authority = "compiled"
    authority_state = AUTHORITY[
        min(AUTHORITY.index(intrinsic_authority), AUTHORITY.index(cap))
    ]
    return {
        "project_id": project["project_id"],
        "manifest_sha256": manifest_hash,
        "authority_cap": cap,
        "authority_state": authority_state,
        "stages_verified": all_verified,
        "requirements": requirement_status,
        "complete": acceptance_live,
        "accepted": acceptance_live,
        "acceptance_receipt": str(acceptance_path) if acceptance_path else None,
        "event_count": event_count,
        "stages": stages,
    }


@_mutating
def prepare_work(
    root: Union[Path, str],
    stage_id: str,
    worker: str,
    runtime: Dict[str, Any],
) -> Dict[str, Any]:
    root = Path(root).resolve()
    if not worker.strip():
        raise SSOTError("worker identity is required")
    _validate_runtime(runtime)
    project, _, manifest_hash = _load_project(root)
    stages = _stage_map(project)
    if stage_id not in stages:
        raise SSOTError(f"unknown stage: {stage_id}")
    status = project_status(root)
    state = next(row["state"] for row in status["stages"] if row["id"] == stage_id)
    if state != "frontier":
        raise SSOTError(f"stage is not on the current frontier: {stage_id} ({state})")
    stage = stages[stage_id]
    if worker.casefold() == stage["verifier"]["owner"].casefold():
        raise SSOTError("worker and verifier owner must differ")
    live = _live_verifications(root, project, manifest_hash)
    target_records = _file_records(root, project["target"]["files"], require=True)
    material_records = _file_records(root, stage["materials"], require=True)
    run_id = uuid.uuid4().hex
    work = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": _utc_now(),
        "project_id": project["project_id"],
        "stage_id": stage_id,
        "objective": stage.get("objective", ""),
        "acceptance": stage.get("acceptance", ""),
        "worker": worker,
        "runtime": runtime,
        "runtime_sha256": _sha_bytes(_canonical(runtime)),
        "manifest_sha256": manifest_hash,
        "target_files": _content_projection(target_records),
        "target_digest": _records_digest(target_records),
        "dependency_verifications": {
            dependency: live[dependency]["receipt_sha256"]
            for dependency in stage.get("depends_on", [])
        },
        "requirements": list(stage["requirements"]),
        "materials": _content_projection(material_records),
        "material_digest": _records_digest(material_records),
        "expected_outputs": list(stage["outputs"]),
        "output_baseline": _file_records(root, stage["outputs"], require=False),
        "verifier_owner": stage["verifier"]["owner"],
        "properties": list(stage["properties"]),
        "verifier_files": _content_projection(
            _file_records(root, stage["verifier"].get("files", []), require=True)
        ),
        "authority": "work_order_only",
    }
    path = _state_path(root, "work-orders", run_id)
    _write_new_json(path, work)
    _append_event(
        root,
        "work_prepared",
        {"run_id": run_id, "stage_id": stage_id, "work_order_sha256": _sha_file(path)},
    )
    return work


@_mutating
def submit_outputs(
    root: Union[Path, str],
    run_id: str,
    worker: str,
    execution: Dict[str, Any],
) -> Dict[str, Any]:
    root = Path(root).resolve()
    project, _, manifest_hash = _load_project(root)
    work_path = _state_path(root, "work-orders", run_id)
    work = _read_json(work_path)
    stage_id = work.get("stage_id")
    stage = _stage_map(project).get(stage_id)
    if stage is None:
        raise SSOTError("work order names an unknown stage")
    latest = _latest_work_order(root, stage_id)
    if latest is None or latest[1].get("run_id") != run_id or _terminal(root, run_id):
        raise SSOTError("work order is stale, replayed, or already terminal")
    if worker != work.get("worker"):
        raise SSOTError("worker identity does not match the work order")
    if work.get("manifest_sha256") != manifest_hash:
        raise SSOTError("project manifest changed after preparation")
    current_target = _file_records(root, project["target"]["files"], require=True)
    if _records_digest(current_target) != work.get("target_digest"):
        raise SSOTError("target changed after preparation")
    materials = _file_records(root, stage["materials"], require=True)
    if not _records_equal(materials, work.get("materials", [])):
        raise SSOTError("stage material bytes changed after preparation")
    outputs = _file_records(root, stage["outputs"], require=True)
    baseline = work.get("output_baseline", [])
    baseline_by_path = {row["path"]: row for row in baseline}
    for output in outputs:
        prior = baseline_by_path.get(output["path"], {"exists": False})
        if prior.get("exists") and prior.get("sha256") == output.get("sha256"):
            raise SSOTError(f"output was not produced in this run: {output['path']}")
    execution_record = _validate_execution(root, stage, work["runtime"], execution)
    execution_record["runtime_sha256"] = work["runtime_sha256"]
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": _utc_now(),
        "project_id": project["project_id"],
        "stage_id": stage_id,
        "worker": worker,
        "runtime": work["runtime"],
        "runtime_sha256": work["runtime_sha256"],
        "execution": execution_record,
        "produced": True,
        "manifest_sha256": manifest_hash,
        "target_digest": work["target_digest"],
        "work_order_sha256": _sha_file(work_path),
        "dependency_verifications": work.get("dependency_verifications", {}),
        "requirements": work["requirements"],
        "materials": _content_projection(materials),
        "material_digest": work["material_digest"],
        "outputs": _content_projection(outputs),
        "authority": "produced_unverified",
    }
    path = _state_path(root, "producer-receipts", run_id)
    _write_new_json(path, receipt)
    _append_event(
        root,
        "outputs_submitted",
        {
            "run_id": run_id,
            "stage_id": stage_id,
            "producer_receipt_sha256": _sha_file(path),
        },
    )
    return receipt


def _expanded_argv(argv: List[str]) -> List[str]:
    return [sys.executable if value == "{python}" else value for value in argv]


def _run_read_only(root: Path, command: Dict[str, Any]) -> Tuple[str, int, str, str]:
    before = _project_digest(root)
    argv = _expanded_argv(command["argv"])
    verifier_environment = os.environ.copy()
    verifier_environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run(
            argv,
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=command.get("timeout_seconds", 60),
            env=verifier_environment,
            shell=False,
            check=False,
        )
        code = completed.returncode
        stdout = completed.stdout[-16384:]
        stderr = completed.stderr[-16384:]
    except subprocess.TimeoutExpired as exc:
        code = 124
        stdout = (exc.stdout or "")[-16384:] if isinstance(exc.stdout, str) else ""
        stderr = "verifier timed out"
    after = _project_digest(root)
    purity = "pure" if before == after else "mutated_project"
    return purity, code, stdout, stderr


@_mutating
def verify_stage(root: Union[Path, str], run_id: str) -> Dict[str, Any]:
    root = Path(root).resolve()
    project, _, manifest_hash = _load_project(root)
    work_path = _state_path(root, "work-orders", run_id)
    producer_path = _state_path(root, "producer-receipts", run_id)
    work = _read_json(work_path)
    producer = _read_json(producer_path)
    stage_id = work.get("stage_id")
    stage = _stage_map(project).get(stage_id)
    if stage is None or producer.get("stage_id") != stage_id:
        raise SSOTError("stage identity mismatch")
    latest = _latest_work_order(root, stage_id)
    if latest is None or latest[1].get("run_id") != run_id or _terminal(root, run_id):
        raise SSOTError("work order is stale, replayed, or already terminal")
    if work.get("worker", "").casefold() == stage["verifier"]["owner"].casefold():
        raise SSOTError("worker cannot verify its own output")
    if manifest_hash != work.get("manifest_sha256") or manifest_hash != producer.get(
        "manifest_sha256"
    ):
        raise SSOTError("manifest changed after work began")
    current_target = _file_records(root, project["target"]["files"], require=True)
    if _records_digest(current_target) != work.get("target_digest"):
        raise SSOTError("target changed after work began")
    outputs = _file_records(root, stage["outputs"], require=True)
    if not _records_equal(outputs, producer.get("outputs", [])):
        raise SSOTError("output bytes changed after submission")
    materials = _file_records(root, stage["materials"], require=True)
    if not _records_equal(materials, work.get("materials", [])) or not _records_equal(
        materials, producer.get("materials", [])
    ):
        raise SSOTError("stage material bytes changed after work began")
    if producer.get("runtime_sha256") != work.get("runtime_sha256"):
        raise SSOTError("runtime identity changed between work and submission")
    verifier_files = _file_records(
        root, stage["verifier"].get("files", []), require=True
    )
    if not _records_equal(verifier_files, work.get("verifier_files", [])):
        raise SSOTError("verifier bytes changed after preparation")
    live = _live_verifications(root, project, manifest_hash)
    for dependency, receipt_hash in work.get("dependency_verifications", {}).items():
        if dependency not in live or live[dependency]["receipt_sha256"] != receipt_hash:
            raise SSOTError(f"dependency is absent or stale: {dependency}")

    negative_purity, negative_code, negative_stdout, negative_stderr = _run_read_only(
        root, stage["verifier"]["negative_control"]
    )
    if negative_code == 0 and negative_purity == "pure":
        purity, code, stdout, stderr = _run_read_only(root, stage["verifier"])
    else:
        purity, code, stdout, stderr = (
            "not_run",
            125,
            "",
            "positive verifier skipped because its negative control failed",
        )
    passed = (
        negative_code == 0
        and negative_purity == "pure"
        and code == 0
        and purity == "pure"
    )
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": _utc_now(),
        "project_id": project["project_id"],
        "stage_id": stage_id,
        "status": "verified" if passed else "failed",
        "manifest_sha256": manifest_hash,
        "target_digest": work["target_digest"],
        "work_order_sha256": _sha_file(work_path),
        "producer_receipt_sha256": _sha_file(producer_path),
        "dependency_verifications": work.get("dependency_verifications", {}),
        "requirements": work["requirements"],
        "materials": _content_projection(materials),
        "material_digest": work["material_digest"],
        "outputs": _content_projection(outputs),
        "runtime": work["runtime"],
        "runtime_sha256": work["runtime_sha256"],
        "execution": producer["execution"],
        "verifier_owner": stage["verifier"]["owner"],
        "properties": list(stage["properties"]),
        "verifier_argv": _expanded_argv(stage["verifier"]["argv"]),
        "verifier_files": _content_projection(verifier_files),
        "verifier_exit_code": code,
        "verifier_purity": purity,
        "negative_control_argv": _expanded_argv(
            stage["verifier"]["negative_control"]["argv"]
        ),
        "negative_control_exit_code": negative_code,
        "negative_control_purity": negative_purity,
        "negative_control_stdout": negative_stdout,
        "negative_control_stderr": negative_stderr,
        "stdout": stdout,
        "stderr": stderr,
        "authority": "stage_verified" if passed else "no_authority",
    }
    path = _state_path(root, "verification", run_id)
    _write_new_json(path, receipt)
    _append_event(
        root,
        "stage_verified" if passed else "stage_failed",
        {
            "run_id": run_id,
            "stage_id": stage_id,
            "verification_sha256": _sha_file(path),
        },
    )
    return receipt


@_mutating
def abandon_work(root: Union[Path, str], run_id: str, reason: str) -> Dict[str, Any]:
    root = Path(root).resolve()
    if not reason.strip():
        raise SSOTError("an abandonment reason is required")
    work = _read_json(_state_path(root, "work-orders", run_id))
    if _terminal(root, run_id):
        raise SSOTError("run is already terminal")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "stage_id": work.get("stage_id"),
        "created_at": _utc_now(),
        "reason": reason,
        "authority": "no_authority",
    }
    path = _state_path(root, "abandoned", run_id)
    _write_new_json(path, receipt)
    _append_event(
        root,
        "work_abandoned",
        {"run_id": run_id, "stage_id": work.get("stage_id"), "reason": reason},
    )
    return receipt


@_mutating
def accept_project(root: Union[Path, str], acceptor: str) -> Dict[str, Any]:
    root = Path(root).resolve()
    project, _, manifest_hash = _load_project(root)
    acceptance = project.get("acceptance")
    if not acceptance:
        raise SSOTError("project has no independent acceptance command")
    if acceptor != acceptance["owner"]:
        raise SSOTError("acceptor does not match the configured independent owner")
    status = project_status(root)
    if not status["stages_verified"]:
        raise SSOTError("all stages must be live and verified before acceptance")
    if not status["requirements"]["conserved"]:
        raise SSOTError("unresolved requirements block independent acceptance")
    workers = {
        row.get("worker", "").casefold()
        for _, row in _all_records(root, "producer-receipts")
    }
    if acceptor.casefold() in workers:
        raise SSOTError("a producer cannot independently accept the project")
    acceptance_files = _file_records(root, acceptance.get("files", []), require=True)
    negative_purity, negative_code, negative_stdout, negative_stderr = _run_read_only(
        root, acceptance["negative_control"]
    )
    if negative_code != 0 or negative_purity != "pure":
        raise SSOTError(
            "independent acceptance negative control failed: "
            f"exit={negative_code}, purity={negative_purity}, "
            f"stderr={negative_stderr}"
        )
    purity, code, stdout, stderr = _run_read_only(root, acceptance)
    if code != 0 or purity != "pure":
        raise SSOTError(
            f"independent acceptance failed: exit={code}, purity={purity}, stderr={stderr}"
        )
    live = _live_verifications(root, project, manifest_hash)
    run_id = uuid.uuid4().hex
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": _utc_now(),
        "project_id": project["project_id"],
        "status": "accepted",
        "acceptor": acceptor,
        "manifest_sha256": manifest_hash,
        "stage_verifications": {
            stage_id: row["receipt_sha256"] for stage_id, row in live.items()
        },
        "acceptance_argv": _expanded_argv(acceptance["argv"]),
        "negative_control_argv": _expanded_argv(acceptance["negative_control"]["argv"]),
        "negative_control_exit_code": negative_code,
        "negative_control_purity": negative_purity,
        "negative_control_stdout": negative_stdout,
        "negative_control_stderr": negative_stderr,
        "acceptance_files": _content_projection(acceptance_files),
        "stdout": stdout,
        "stderr": stderr,
        "authority": project.get("authority_cap", "tested"),
    }
    path = _state_path(root, "acceptance", run_id)
    _write_new_json(path, receipt)
    _append_event(
        root,
        "project_accepted",
        {
            "run_id": run_id,
            "acceptance_sha256": _sha_file(path),
            "authority": receipt["authority"],
        },
    )
    return receipt
