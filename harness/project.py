#!/usr/bin/env python3
"""Explicit natural-language project activation and immutable intent state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional


SCHEMA_VERSION = 1
STATE_DIR = ".trusted-project"
ZERO_HASH = "0" * 64
MODES = {"plan", "execute"}
SURFACES = (
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "ssot-project.json",
    ".claude/settings.json",
    ".claude/settings.local.json",
)
DEFAULT_BUDGETS = {
    "model_tokens": 0,
    "cost_usd": 0,
    "wall_seconds": 300,
    "outer_attempts": 0,
    "research_sources": 0,
    "storage_bytes": 1_000_000,
    "external_side_effects": 0,
}
BUDGET_FIELDS = set(DEFAULT_BUDGETS)


class ProjectError(RuntimeError):
    """The project activation or immutable state failed closed."""


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


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _target_root(root: Path) -> Path:
    requested = root.expanduser()
    resolved = requested.resolve()
    if not resolved.is_dir():
        raise ProjectError(f"target root does not exist: {resolved}")
    state = resolved / STATE_DIR
    if state.is_symlink():
        raise ProjectError(f"{STATE_DIR} cannot be a symlink")
    if state.exists() and not state.is_dir():
        raise ProjectError(f"{STATE_DIR} must be a directory")
    for name in ("locks", "projects"):
        child = state / name
        if child.is_symlink():
            raise ProjectError(f"{STATE_DIR}/{name} cannot be a symlink")
    return resolved


def _root_identity(root: Path) -> Dict[str, Any]:
    stat = root.stat()
    record = {
        "resolved_path": str(root),
        "device": int(stat.st_dev),
        "inode": int(stat.st_ino),
    }
    record["sha256"] = _sha_bytes(_canonical(record))
    return record


def _surface_record(root: Path, relative: str) -> Dict[str, Any]:
    unresolved = root / relative
    current = unresolved
    while current != root:
        if current.is_symlink():
            raise ProjectError(f"authority surface cannot use symlinks: {relative}")
        current = current.parent
    if not unresolved.exists():
        return {"path": relative, "exists": False}
    if not unresolved.is_file():
        raise ProjectError(f"authority surface is not a file: {relative}")
    return {
        "path": relative,
        "exists": True,
        "size": unresolved.stat().st_size,
        "sha256": _sha_file(unresolved),
    }


def _authority_surfaces(root: Path) -> List[Dict[str, Any]]:
    return [_surface_record(root, relative) for relative in SURFACES]


def _write_new_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            raise ProjectError(f"refusing to overwrite immutable file: {path}")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def _project_lock(root: Path, project_id: str) -> Iterator[None]:
    lock_dir = root / STATE_DIR / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{project_id}.lock"
    deadline = time.monotonic() + 5
    descriptor: Optional[int] = None
    while descriptor is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise ProjectError(f"project state is locked: {project_id}")
            time.sleep(0.05)
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode())
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)


def _slug(value: str) -> str:
    words = re.findall(r"[a-z0-9]+", value.casefold())[:6]
    return "-".join(words)[:48] or "project"


def _budget_contract(root: Path, budget_file: Optional[Path]) -> Dict[str, Any]:
    if budget_file is None:
        return {
            "source": "e6a-capture-only-default",
            "values": dict(DEFAULT_BUDGETS),
            "authority": "no_model_or_external_execution",
        }
    unresolved = budget_file if budget_file.is_absolute() else root / budget_file
    path = unresolved.resolve()
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ProjectError("budget file escapes target root") from exc
    current = unresolved
    while current != root:
        if current.is_symlink():
            raise ProjectError("budget file cannot use symlinks")
        # Windows short names can identify the root without textual equality.
        # Walk raw parent segments first when '..' could hide an ancestor link.
        if ".." not in current.parts and current.resolve() == root:
            break
        parent = current.parent
        if parent == current:
            raise ProjectError("budget file ancestry cannot reach target root")
        current = parent
    if not path.is_file():
        raise ProjectError("budget file must be an existing regular target file")
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectError(f"invalid budget file: {exc}") from exc
    if not isinstance(values, dict) or set(values) != BUDGET_FIELDS:
        raise ProjectError(
            "budget file must contain exactly: " + ", ".join(sorted(BUDGET_FIELDS))
        )
    for key, value in values.items():
        if key == "cost_usd":
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            valid = isinstance(value, int) and not isinstance(value, bool)
        if not valid or value < 0:
            raise ProjectError(f"invalid non-negative budget: {key}")
    return {
        "source": relative,
        "source_sha256": _sha_file(path),
        "values": values,
        "authority": "declared_not_yet_consumed",
    }


def _stable_intent(value: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value[key]
        for key in (
            "schema_version",
            "project_id",
            "requested_mode",
            "request",
            "target",
            "constraints",
            "open_decisions",
            "budgets",
            "authority",
            "ssot",
        )
    }


def _event_body(value: Dict[str, Any]) -> Dict[str, Any]:
    return {key: item for key, item in value.items() if key != "record_sha256"}


def _append_event(
    project_dir: Path,
    intent_sha256: str,
    event_type: str,
    details: Dict[str, Any],
) -> Dict[str, Any]:
    events = _read_events(project_dir, intent_sha256)
    sequence = len(events) + 1
    previous = _sha_file(events[-1][0]) if events else ZERO_HASH
    body = {
        "schema_version": SCHEMA_VERSION,
        "sequence": sequence,
        "created_at": _utc_now(),
        "event_type": event_type,
        "intent_sha256": intent_sha256,
        "previous_event_sha256": previous,
        "details": details,
    }
    event = {**body, "record_sha256": _sha_bytes(_canonical(body))}
    path = project_dir / "events" / f"{sequence:06d}-{event_type}.json"
    _write_new_json(path, event)
    return event


def _read_events(project_dir: Path, intent_sha256: str) -> List[Any]:
    event_dir = project_dir / "events"
    paths = sorted(event_dir.glob("*.json")) if event_dir.is_dir() else []
    rows = []
    previous = ZERO_HASH
    for sequence, path in enumerate(paths, 1):
        if path.is_symlink() or not path.is_file():
            raise ProjectError(f"project event is not a regular file: {path.name}")
        try:
            event = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectError(f"invalid project event {path.name}: {exc}") from exc
        if (
            not isinstance(event, dict)
            or event.get("sequence") != sequence
            or event.get("intent_sha256") != intent_sha256
            or event.get("previous_event_sha256") != previous
            or event.get("record_sha256") != _sha_bytes(_canonical(_event_body(event)))
        ):
            raise ProjectError(f"project event chain is invalid: {path.name}")
        rows.append((path, event))
        previous = _sha_file(path)
    return rows


def _project_dir(root: Path, project_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", project_id):
        raise ProjectError("invalid project id")
    project_dir = root / STATE_DIR / "projects" / project_id
    for path in (project_dir, project_dir / "events", project_dir / "intent.json"):
        if path.is_symlink():
            raise ProjectError("project state cannot use symlinks")
    return project_dir


def create_intent(
    root: Path,
    request: str,
    mode: str,
    *,
    constraints: Iterable[str] = (),
    open_decisions: Iterable[str] = (),
    budget_file: Optional[Path] = None,
) -> Dict[str, Any]:
    """Capture one exact request without starting PRD work or execution."""
    root = _target_root(root)
    request = request.strip()
    if not request or len(request) > 100_000:
        raise ProjectError("request must contain 1..100000 characters")
    if mode not in MODES:
        raise ProjectError(f"unsupported requested mode: {mode}")
    constraint_values = list(constraints)
    decision_values = list(open_decisions)
    if not all(isinstance(item, str) for item in constraint_values + decision_values):
        raise ProjectError("constraints and open decisions must be strings")
    constraint_list = [item.strip() for item in constraint_values if item.strip()]
    decision_list = [item.strip() for item in decision_values if item.strip()]
    root_identity = _root_identity(root)
    surfaces = _authority_surfaces(root)
    ssot_manifest = root / "ssot-project.json"
    ssot_state = root / ".ssot"
    if ssot_manifest.is_file():
        ssot = {
            "mode": "reuse_existing",
            "manifest": "ssot-project.json",
            "manifest_sha256": _sha_file(ssot_manifest),
        }
    elif ssot_state.exists():
        ssot = {"mode": "ambiguous_existing_state", "manifest": None}
    else:
        ssot = {"mode": "new_project_pending", "manifest": None}
    budgets = _budget_contract(root, budget_file)
    identity_seed = {
        "request": request,
        "requested_mode": mode,
        "target_sha256": root_identity["sha256"],
        "constraints": constraint_list,
        "open_decisions": decision_list,
        "budgets": budgets,
    }
    project_id = f"{_slug(request)}-{_sha_bytes(_canonical(identity_seed))[:12]}"
    project_dir = _project_dir(root, project_id)
    intent = {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "created_at": _utc_now(),
        "requested_mode": mode,
        "request": {"text": request, "sha256": _sha_bytes(request.encode("utf-8"))},
        "target": {
            "root": root_identity,
            "authority_surfaces": surfaces,
        },
        "constraints": constraint_list,
        "open_decisions": decision_list,
        "budgets": budgets,
        "authority": {
            "activation": "explicit_cli_or_installed_skill",
            "current": "intent_capture_only",
            "model_or_research_calls": False,
            "project_file_changes": False,
            "external_side_effects": False,
        },
        "ssot": ssot,
    }
    intent_path = project_dir / "intent.json"
    with _project_lock(root, project_id):
        if intent_path.exists():
            try:
                existing = json.loads(intent_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ProjectError(f"existing intent is invalid: {exc}") from exc
            if _stable_intent(existing) != _stable_intent(intent):
                raise ProjectError("project id collision with different intent")
            result = project_status(root, project_id)
            result["idempotent"] = True
            return result
        _write_new_json(intent_path, intent)
        intent_hash = _sha_file(intent_path)
        initial_status = (
            "held_authority_ambiguous"
            if ssot["mode"] == "ambiguous_existing_state"
            else "intent_captured"
        )
        _append_event(
            project_dir,
            intent_hash,
            "intent_captured",
            {"status": initial_status, "requested_mode": mode},
        )
    result = project_status(root, project_id)
    result["idempotent"] = False
    return result


def _load_intent(root: Path, project_id: str) -> Any:
    project_dir = _project_dir(root, project_id)
    path = project_dir / "intent.json"
    try:
        intent = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectError(f"cannot read project intent: {exc}") from exc
    if not isinstance(intent, dict) or intent.get("project_id") != project_id:
        raise ProjectError("intent project identity is invalid")
    try:
        _stable_intent(intent)
    except KeyError as exc:
        raise ProjectError(f"intent is missing required field: {exc.args[0]}") from exc
    request = intent.get("request")
    if (
        not isinstance(request, dict)
        or not isinstance(request.get("text"), str)
        or request.get("sha256") != _sha_bytes(request["text"].encode("utf-8"))
    ):
        raise ProjectError("intent request hash is invalid")
    return project_dir, path, intent


def project_status(root: Path, project_id: str) -> Dict[str, Any]:
    """Derive current project status from immutable intent and event bytes."""
    root = _target_root(root)
    project_dir, intent_path, intent = _load_intent(root, project_id)
    intent_hash = _sha_file(intent_path)
    events = _read_events(project_dir, intent_hash)
    if not events or events[0][1].get("event_type") != "intent_captured":
        raise ProjectError("intent has no valid capture event")
    expected_root = intent["target"]["root"]
    current_root = _root_identity(root)
    drift = []
    if current_root != expected_root:
        drift.append("target root identity changed")
    current_surfaces = _authority_surfaces(root)
    expected_surfaces = intent["target"]["authority_surfaces"]
    if current_surfaces != expected_surfaces:
        drift.append("target instruction or authority surfaces changed")
    budget_contract = intent["budgets"]
    if budget_contract.get("source") != "e6a-capture-only-default":
        budget_source = _surface_record(root, budget_contract["source"])
        if (
            not budget_source.get("exists")
            or budget_source.get("sha256") != budget_contract.get("source_sha256")
        ):
            drift.append("budget authority changed")
    abandoned = any(row[1].get("event_type") == "abandoned" for row in events)
    review_events = [
        row[1] for row in events if row[1].get("event_type") == "prd_reviewed"
    ]
    if len(review_events) > 1:
        raise ProjectError("project has more than one PRD review event")
    review_receipt = None
    if review_events:
        from harness.prd import verify_review_event

        review_receipt = verify_review_event(
            root, project_dir, intent, intent_hash, review_events[0]
        )
    compile_events = [
        row[1] for row in events if row[1].get("event_type") == "ssot_compiled"
    ]
    if len(compile_events) > 1:
        raise ProjectError("project has more than one SSOT compile event")
    compile_receipt = None
    execution = None
    if compile_events:
        if review_receipt is None:
            raise ProjectError("SSOT compilation has no reviewed PRD predecessor")
        from harness.compiler import verify_compile_event

        compile_receipt = verify_compile_event(
            root, project_dir, intent, intent_hash, compile_events[0]
        )
        if compile_receipt["publication_mode"] == "new_project_pending":
            expected_surfaces = [
                compile_receipt["root_manifest"]
                if row["path"] == "ssot-project.json"
                else row
                for row in expected_surfaces
            ]
        elif compile_receipt["publication_mode"] != "reuse_existing":
            raise ProjectError("SSOT compilation publication mode is invalid")
        drift = []
        if current_root != expected_root:
            drift.append("target root identity changed")
        if current_surfaces != expected_surfaces:
            drift.append("target instruction or authority surfaces changed")
        if budget_contract.get("source") != "e6a-capture-only-default":
            budget_source = _surface_record(root, budget_contract["source"])
            if (
                not budget_source.get("exists")
                or budget_source.get("sha256")
                != budget_contract.get("source_sha256")
            ):
                drift.append("budget authority changed")
        if not drift and not abandoned:
            from harness.executor import execution_status

            try:
                execution = execution_status(root, project_dir, intent, events)
            except Exception as exc:
                from ssot.control import SSOTError

                if isinstance(exc, (ProjectError, SSOTError)):
                    raise ProjectError(f"execution state is invalid: {exc}") from exc
                raise
    ambiguous = intent["ssot"]["mode"] == "ambiguous_existing_state"
    if abandoned:
        state = "abandoned"
        next_action = "start a new intent if the objective is still required"
    elif drift:
        state = "held_target_drift"
        next_action = "review target drift and create a new or superseding intent"
    elif ambiguous:
        state = "held_authority_ambiguous"
        next_action = "resolve existing .ssot state before PRD development"
    elif intent["open_decisions"]:
        state = "held_open_decisions"
        next_action = "resolve the intent's material decisions before PRD review"
    elif execution is not None:
        state = execution["state"]
        next_action = execution["next_allowed_action"]
    elif review_receipt is not None:
        state = "prd_reviewed"
        next_action = "E6c compile the reviewed PRD into the target SSOT"
    else:
        state = "intent_captured"
        next_action = "E6b PRD development and reinforcement"
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "state": state,
        "requested_mode": intent["requested_mode"],
        "request_sha256": intent["request"]["sha256"],
        "target_sha256": expected_root["sha256"],
        "ssot_mode": intent["ssot"]["mode"],
        "event_count": len(events),
        "event_head_sha256": _sha_file(events[-1][0]),
        "drift": drift,
        "ready_for_execution": execution["ready_for_execution"] if execution else False,
        "authority": (
            execution["authority"]
            if execution is not None
            else (
                "reviewed_prd_only_no_execution"
                if review_receipt is not None and state == "prd_reviewed"
                else "intent_only"
            )
        ),
        "next_allowed_action": next_action,
        **(
            {
                "budgets": execution["budgets"],
                "usage": execution["usage"],
                "remaining": execution["remaining"],
                "budget_exceeded": execution["budget_exceeded"],
                "execution_receipts": execution["execution_receipts"],
                "ssot": execution["ssot"],
            }
            if execution is not None
            else {}
        ),
    }


def resume_project(
    root: Path,
    project_id: str,
    *,
    authorizations: Optional[Mapping[str, Path]] = None,
) -> Dict[str, Any]:
    result = project_status(root, project_id)
    if result["state"] == "abandoned":
        raise ProjectError("abandoned project cannot resume")
    if result["requested_mode"] == "execute" and result["state"] in {
        "configured",
        "running",
        "verified",
        "held_execution",
        "failed",
    }:
        from harness.executor import execute_project

        result = execute_project(root, project_id, authorizations=authorizations)
    result["operation"] = "resume"
    result["resumed"] = result["state"] in {
        "intent_captured",
        "prd_reviewed",
        "configured",
        "running",
        "verified",
    }
    return result


def abandon_project(root: Path, project_id: str, reason: str) -> Dict[str, Any]:
    root = _target_root(root)
    reason = reason.strip()
    if not reason or len(reason) > 2000:
        raise ProjectError("abandon reason must contain 1..2000 characters")
    project_dir, intent_path, _intent = _load_intent(root, project_id)
    intent_hash = _sha_file(intent_path)
    with _project_lock(root, project_id):
        status = project_status(root, project_id)
        if status["state"] == "abandoned":
            status["idempotent"] = True
            return status
        _append_event(
            project_dir,
            intent_hash,
            "abandoned",
            {"reason": reason, "reason_sha256": _sha_bytes(reason.encode("utf-8"))},
        )
    status = project_status(root, project_id)
    status["idempotent"] = False
    return status


def request_execution(
    root: Path,
    value: str,
    *,
    constraints: Iterable[str] = (),
    open_decisions: Iterable[str] = (),
    budget_file: Optional[Path] = None,
    authorizations: Optional[Mapping[str, Path]] = None,
) -> Dict[str, Any]:
    """Resolve or capture an execute intent and run only an admitted SSOT."""
    root = _target_root(root)
    if (root / STATE_DIR / "projects" / value / "intent.json").is_file():
        result = project_status(root, value)
    else:
        result = create_intent(
            root,
            value,
            "execute",
            constraints=constraints,
            open_decisions=open_decisions,
            budget_file=budget_file,
        )
    if result["state"] == "intent_captured":
        result["state"] = "held_prd_not_reviewed"
        result["next_allowed_action"] = "implement E6b PRD development and review"
    elif result["state"] == "prd_reviewed":
        result["state"] = "held_ssot_not_compiled"
        result["next_allowed_action"] = "implement E6c reviewed-PRD compilation"
    elif result["state"] in {"configured", "running", "verified", "held_execution", "failed"}:
        from harness.executor import execute_project

        return execute_project(
            root, result["project_id"], authorizations=authorizations
        )
    if result["state"] not in {"tested", "held_budget_exhausted"}:
        result["ready_for_execution"] = False
        result["authority"] = "no_execution_authority"
    return result


def _add_intent_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("value")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--constraint", action="append", default=[])
    parser.add_argument("--open-decision", action="append", default=[])
    parser.add_argument("--budget-file", type=Path)


def _authorization_map(values: Iterable[str]) -> Dict[str, Path]:
    result = {}
    for value in values:
        stage, separator, path = value.partition("=")
        if not separator or not stage.strip() or not path.strip() or stage in result:
            raise ProjectError(
                "--authorization must be a unique STAGE=TARGET_RELATIVE_PATH"
            )
        result[stage] = Path(path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="explicit trusted-project activation and intent protocol"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    _add_intent_arguments(plan)
    execute = sub.add_parser("execute")
    _add_intent_arguments(execute)
    execute.add_argument("--authorization", action="append", default=[])
    status_command = sub.add_parser("status")
    status_command.add_argument("project_id")
    status_command.add_argument("--root", type=Path, required=True)
    resume_command = sub.add_parser("resume")
    resume_command.add_argument("project_id")
    resume_command.add_argument("--root", type=Path, required=True)
    resume_command.add_argument("--authorization", action="append", default=[])
    abandon = sub.add_parser("abandon")
    abandon.add_argument("project_id")
    abandon.add_argument("--root", type=Path, required=True)
    abandon.add_argument("--reason", required=True)
    admit = sub.add_parser("admit-prd")
    admit.add_argument("project_id")
    admit.add_argument("--root", type=Path, required=True)
    admit.add_argument("--contract", type=Path, required=True)
    compile_command = sub.add_parser("compile-ssot")
    compile_command.add_argument("project_id")
    compile_command.add_argument("--root", type=Path, required=True)
    compile_command.add_argument("--contract", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "plan":
            result = create_intent(
                args.root,
                args.value,
                "plan",
                constraints=args.constraint,
                open_decisions=args.open_decision,
                budget_file=args.budget_file,
            )
        elif args.command == "execute":
            result = request_execution(
                args.root,
                args.value,
                constraints=args.constraint,
                open_decisions=args.open_decision,
                budget_file=args.budget_file,
                authorizations=_authorization_map(args.authorization),
            )
        elif args.command == "status":
            result = project_status(args.root, args.project_id)
        elif args.command == "resume":
            result = resume_project(
                args.root,
                args.project_id,
                authorizations=_authorization_map(args.authorization),
            )
        elif args.command == "admit-prd":
            from harness.prd import admit_prd

            result = admit_prd(args.root, args.project_id, args.contract)
        elif args.command == "compile-ssot":
            from harness.compiler import compile_ssot

            result = compile_ssot(args.root, args.project_id, args.contract)
        else:
            result = abandon_project(args.root, args.project_id, args.reason)
    except ProjectError as exc:
        parser.exit(2, f"TRUSTED PROJECT HOLD: {exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
