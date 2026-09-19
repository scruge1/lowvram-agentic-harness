#!/usr/bin/env python3
"""Identity-bound Pi adapter for host-local per-project Hermes boards."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import inspect
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc

from project_identity import initialize_identity, load_identity
from project_closeout import compile_closeout
from project_knowledge import build as build_knowledge
from project_knowledge import query as query_knowledge
from project_skill_candidate import compile_candidate


SCHEMA = "pi-kanban-result/v1"
EXPECTED_HERMES_COMMIT = "866332bfb52c46e543143b2620a9aeee8bce9c77"
EXPECTED_MODULE_HASHES = {
    "kanban_db": "0b2003b32368b7de9e80db6796468e6e3daa492892949116b666041796587e2d",
    "kanban_db_connect": "96f4c0520858905250b10f33f00cb4613f55ede9646cb59bb7fe91cb93cc4b2c",
}
WORKSPACE_INITIALIZER = Path(__file__).with_name("init_workspace.py")
EXPECTED_WORKSPACE_INITIALIZER_SHA256 = "1cd480bd692001fa8d56775496d723c6ff937c1b306ddd66c1c6f343ec90c6b9"
STATE_BASE = Path(os.environ.get("PI_PROJECT_STATE_BASE", "~/.local/state/pi-projects")).expanduser()
CREATOR = "pi-kanban-supervisor"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
VISIBLE_STATUSES = {"triage", "todo", "ready", "running", "blocked", "review", "done", "archived"}
CREATE_STATUSES = {"triage", "ready"}
TRANSITIONS = {
    "schedule",
    "block",
    "unblock",
    "request_review",
    "request_changes",
    "reopen_review",
    "complete",
    "archive",
}


class AdapterError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AdapterError(message)


def exact(value: Any, keys: set[str], optional: set[str] = set()) -> Mapping[str, Any]:
    require(isinstance(value, Mapping), "request must be an object")
    present = set(value)
    require(keys <= present, f"missing fields: {sorted(keys - present)}")
    require(present <= keys | optional, f"unexpected fields: {sorted(present - keys - optional)}")
    return value


def text(value: Any, name: str, maximum: int, *, empty: bool = False) -> str:
    require(isinstance(value, str), f"{name} must be text")
    require(value == value.strip(), f"{name} must be trimmed")
    require(empty or bool(value), f"{name} must not be empty")
    require(len(value) <= maximum, f"{name} is too long")
    return value


def identifier(value: Any, name: str) -> str:
    value = text(value, name, 128)
    require(bool(IDENTIFIER.fullmatch(value)), f"{name} has invalid characters")
    return value


def package_commit() -> str:
    dist = importlib.metadata.distribution("hermes-agent")
    direct = dist.read_text("direct_url.json")
    require(direct is not None, "Hermes direct-url identity is missing")
    value = json.loads(direct)
    commit = value.get("vcs_info", {}).get("commit_id")
    require(commit == EXPECTED_HERMES_COMMIT, "Hermes package revision drift")
    for name, module in (("kanban_db", kb), ("kanban_db_connect", kbc)):
        source = inspect.getsourcefile(module)
        require(source is not None, f"Hermes {name} source identity is missing")
        digest = hashlib.sha256(Path(source).read_bytes()).hexdigest()
        require(digest == EXPECTED_MODULE_HASHES[name], f"Hermes {name} byte drift")
    return commit


def task_value(task: Any) -> dict[str, Any]:
    fields = (
        "id",
        "title",
        "body",
        "assignee",
        "status",
        "tenant",
        "priority",
        "created_by",
        "created_at",
        "started_at",
        "completed_at",
        "result",
        "completion_contract",
        "last_failure_error",
        "session_id",
    )
    return {field: getattr(task, field, None) for field in fields}


def show(conn: sqlite3.Connection, task_id: str, tenant: str) -> dict[str, Any]:
    task = kb.get_task(conn, task_id)
    require(task is not None, "task not found")
    require(getattr(task, "tenant", None) == tenant, "task belongs to a different project board")
    return {
        "task": task_value(task),
        "parents": kb.parent_ids(conn, task_id),
        "children": kb.child_ids(conn, task_id),
        "comments": [
            {
                "id": getattr(item, "id", None),
                "author": item.author,
                "body": item.body,
                "created_at": item.created_at,
            }
            for item in kb.list_comments(conn, task_id)
        ],
    }


def workspace_status(root: Path, identity: Mapping[str, Any]) -> dict[str, Any]:
    workspace = root / identity["workspace_path"]
    required = (
        "AGENTS.md",
        "PROJECT-SSOT.md",
        "ACTIVE-CHECKPOINT.md",
        "TARGET-PROVENANCE.json",
        "CONTRACT-SOURCE-MANIFEST.json",
        "REQUIREMENT-INVENTORY.jsonl",
        "RUN-REGISTER.jsonl",
        "DIARY.md",
        "COVERAGE-MATRIX.md",
        "wiki/HOWTO.md",
    )
    missing = [item for item in required if not (workspace / item).is_file()]
    return {"path": str(workspace), "state": "scaffolded" if not missing else "incomplete", "missing": missing}


def ensure_workspace(
    root: Path,
    identity: Mapping[str, Any],
    *,
    target: Any,
    why: Any,
    system_setup: Any,
) -> dict[str, Any]:
    target = text(target, "target", 1000)
    why = text(why, "why", 2000)
    require(isinstance(system_setup, bool), "system_setup must be Boolean")
    authority = identity.get("native_authority")
    require(isinstance(authority, str) and bool(authority), "native_authority is required to initialize an ICM workspace")
    require(WORKSPACE_INITIALIZER.is_file(), "ICM workspace initializer is unavailable")
    require(
        hashlib.sha256(WORKSPACE_INITIALIZER.read_bytes()).hexdigest() == EXPECTED_WORKSPACE_INITIALIZER_SHA256,
        "ICM workspace initializer byte drift",
    )
    command = [
        sys.executable,
        "-B",
        str(WORKSPACE_INITIALIZER),
        "--root",
        str(root / identity["workspace_path"]),
        "--target",
        target,
        "--why",
        why,
        "--parent-authority",
        authority,
        "--resume",
    ]
    if system_setup:
        command.append("--system-setup")
    completed = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
    require(completed.returncode == 0, f"ICM workspace initialization failed: {completed.stderr.strip()[:1000]}")
    try:
        operation = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AdapterError("ICM workspace initializer returned invalid JSON") from exc
    result = workspace_status(root, identity)
    require(result["state"] == "scaffolded", f"ICM workspace is incomplete: {result['missing']}")
    result["operation"] = operation
    return result


def save_capability_snapshot(state_root: Path, identity: Mapping[str, Any], snapshot: Any, session_id: Any) -> dict[str, Any]:
    require(isinstance(snapshot, Mapping), "capability snapshot must be an object")
    require(snapshot.get("schema") == "pi-native-capabilities/v1", "unsupported capability snapshot schema")
    session_id = identifier(session_id, "session_id")
    require(snapshot.get("session_id") == session_id, "capability snapshot session differs")
    tools = snapshot.get("configured_tools")
    require(isinstance(tools, list) and len(tools) <= 10000, "capability tool registry is invalid")
    names: list[str] = []
    for tool in tools:
        require(isinstance(tool, Mapping), "capability tool entry must be an object")
        names.append(identifier(tool.get("name"), "capability tool name"))
        require(isinstance(tool.get("active"), bool), "capability active state must be Boolean")
    require(len(names) == len(set(names)), "capability tool names must be unique")
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    require(len(canonical) <= 512 * 1024, "capability snapshot is too large")
    record = {
        "schema": "pi-project-capability-snapshot/v1",
        "project_id": identity["project_id"],
        "session_id": session_id,
        "observed_at": snapshot.get("observed_at"),
        "snapshot_sha256": hashlib.sha256(canonical).hexdigest(),
        "snapshot": snapshot,
        "authority": "registry_observation_only",
    }
    state_root.mkdir(parents=True, exist_ok=True)
    target = state_root / "capabilities.json"
    temporary = state_root / f".capabilities-{os.getpid()}.json"
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(target)
    return {key: record[key] for key in ("schema", "project_id", "session_id", "observed_at", "snapshot_sha256", "authority")}


def project_context(project_root: Any, *, initialize: bool = False, native_authority: Any = None) -> tuple[Path, dict[str, Any], Path, Path]:
    root_text = text(project_root, "project_root", 4096)
    requested_root = Path(root_text).expanduser()
    if initialize and not requested_root.exists():
        require(requested_root.name not in {"", ".", ".."}, "project_root name is invalid")
        parent = requested_root.parent.resolve(strict=True)
        require(parent.is_dir(), "project_root parent must be a directory")
        require(parent != Path(parent.anchor), "project_root cannot be created directly under a filesystem root")
        requested_root = parent / requested_root.name
        requested_root.mkdir(mode=0o700)
    root = requested_root.resolve(strict=True)
    require(root.is_dir(), "project_root must be a directory")
    require(root != Path(root.anchor), "project_root cannot be a filesystem root")
    require(root != Path.home().resolve(), "project_root cannot be the user home directory")
    if initialize:
        if native_authority is not None:
            native_authority = text(native_authority, "native_authority", 4096, empty=True) or None
        identity, _ = initialize_identity(root, native_authority=native_authority)
    else:
        identity = load_identity(root)
    project_id = identity["project_id"]
    state_root = STATE_BASE / project_id
    return root, identity, state_root / "kanban.db", state_root / "supervisor.lock"


@contextlib.contextmanager
def locked_board(database: Path, lock: Path):
    state_root = database.parent
    state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock.touch(mode=0o600, exist_ok=True)
    import fcntl

    with lock.open("r+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        with kbc.connect_closing(database) as conn:
            yield conn


def status(conn: sqlite3.Connection, tenant: str, database: Path, identity: Mapping[str, Any]) -> dict[str, Any]:
    tasks = kb.list_tasks(conn, tenant=tenant, include_archived=True, limit=10000)
    counts = {name: 0 for name in sorted(VISIBLE_STATUSES)}
    for task in tasks:
        counts[task.status] = counts.get(task.status, 0) + 1
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    return {
        "backend": "hermes_local_v1",
        "backend_revision": package_commit(),
        "backend_module_sha256": EXPECTED_MODULE_HASHES,
        "hermes_version": importlib.metadata.version("hermes-agent"),
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "sqlite_version": sqlite3.sqlite_version,
        "journal_mode": mode,
        "project_id": identity["project_id"],
        "board_id": identity["board_id"],
        "board_sha256": hashlib.sha256(database.read_bytes()).hexdigest() if database.exists() else None,
        "task_counts": counts,
        "dispatcher": "disabled",
        "ssot_authority": "none",
    }


def execute(request: Mapping[str, Any]) -> dict[str, Any]:
    exact(request, {"action", "project_root"}, {"initialize", "native_authority", "target", "why", "system_setup", "terms", "snapshot", "status", "limit", "task_id", "title", "body", "priority", "parents", "idempotency_key", "initial_status", "transition", "reason", "summary", "comment", "session_id", "card_id", "receipt_path", "receipt_sha256", "lessons", "request_id", "objective", "draft_plan", "name", "description", "closeout_path", "closeout_sha256", "triggers", "steps", "verification", "stop_conditions"})
    action = identifier(request["action"], "action")
    initialize = request.get("initialize", False)
    require(isinstance(initialize, bool), "initialize must be Boolean")
    require(action == "project_admit" or not initialize, "initialize is valid only for project_admit")
    root, identity, database, lock = project_context(
        request["project_root"],
        initialize=initialize,
        native_authority=request.get("native_authority"),
    )
    if action == "project_admit" and initialize:
        workspace = ensure_workspace(
            root,
            identity,
            target=request.get("target"),
            why=request.get("why"),
            system_setup=request.get("system_setup", False),
        )
    else:
        workspace = workspace_status(root, identity)
        require(workspace["state"] == "scaffolded", f"ICM workspace is incomplete: {workspace['missing']}")
    tenant = identity["board_id"]
    package_commit()
    with locked_board(database, lock) as conn:
        if action == "project_admit":
            knowledge = build_knowledge(root)
            result = {
                "project_root": str(root),
                "identity": identity,
                "workspace": workspace,
                "knowledge": knowledge,
                "board": status(conn, tenant, database, identity),
            }
        elif action == "knowledge_query":
            terms = text(request.get("terms"), "terms", 1000)
            limit = request.get("limit", 10)
            require(isinstance(limit, int) and not isinstance(limit, bool) and 1 <= limit <= 50, "limit must be from 1 through 50")
            result = query_knowledge(root, terms, limit)
        elif action == "knowledge_build":
            result = build_knowledge(root)
        elif action == "capability_snapshot":
            result = save_capability_snapshot(database.parent, identity, request.get("snapshot"), request.get("session_id"))
        elif action == "consultation_admit":
            task_id = identifier(request.get("task_id"), "task_id")
            request_id = identifier(request.get("request_id"), "request_id")
            objective = text(request.get("objective"), "objective", 200)
            draft_plan = text(request.get("draft_plan"), "draft_plan", 6000)
            session_id = identifier(request.get("session_id"), "session_id")
            requested_card_id = request.get("card_id")
            if requested_card_id is not None:
                card_id = identifier(requested_card_id, "card_id")
                card = show(conn, card_id, tenant)["task"]
                require(card["status"] not in {"done", "archived"}, "consultation card is terminal")
                kb.add_comment(conn, card_id, CREATOR, f"Revised planning consultation {request_id}.\n\n{draft_plan}"[:8000])
                result = {"resumed": True, **show(conn, card_id, tenant)}
            else:
                prefix = f"Consultation task: {task_id}\n"
                matches = [task for task in kb.list_tasks(conn, tenant=tenant, include_archived=True, limit=10000) if (task.body or "").startswith(prefix)]
                require(len(matches) <= 1, "multiple cards exist for the consultation task ID")
                if matches:
                    card_id = matches[0].id
                    kb.add_comment(conn, card_id, CREATOR, f"Revised planning consultation {request_id}.\n\n{draft_plan}"[:8000])
                    result = {"resumed": True, **show(conn, card_id, tenant)}
                else:
                    key = f"consult-task-{hashlib.sha256(task_id.encode('utf-8')).hexdigest()[:24]}"
                    card_id = kb.create_task(
                        conn, title=objective,
                        body=f"Consultation task: {task_id}\nRequest: {request_id}\n\n{draft_plan}"[:8000],
                        created_by=CREATOR, workspace_kind="scratch", tenant=tenant,
                        priority=0, parents=[], idempotency_key=key, triage=False,
                        initial_status="running", session_id=session_id,
                        completion_contract="local-only",
                    )
                    result = {"resumed": False, **show(conn, card_id, tenant)}
        elif action == "project_closeout_prepare":
            card_id = identifier(request.get("card_id"), "card_id")
            show(conn, card_id, tenant)
            result = compile_closeout(root, {
                "task_id": request.get("task_id"),
                "card_id": card_id,
                "receipt_path": request.get("receipt_path"),
                "receipt_sha256": request.get("receipt_sha256"),
                "summary": request.get("summary"),
                "lessons": request.get("lessons"),
            })
            kb.add_comment(conn, card_id, CREATOR, f"Verified project closeout prepared at {result['closeout_path']} with SHA-256 {result['closeout_sha256']}. Durable memory remains pending independent write and readback.")
        elif action == "project_skill_candidate_compile":
            result = compile_candidate(root, {
                key: request.get(key)
                for key in (
                    "name", "description", "closeout_path", "closeout_sha256",
                    "triggers", "steps", "verification", "stop_conditions",
                )
            })
        elif action == "status":
            result = status(conn, tenant, database, identity)
        elif action == "list":
            status_filter = request.get("status")
            if status_filter is not None:
                status_filter = identifier(status_filter, "status")
                require(status_filter in VISIBLE_STATUSES, "unsupported status")
            limit = request.get("limit", 50)
            require(isinstance(limit, int) and not isinstance(limit, bool) and 1 <= limit <= 100, "limit must be from 1 through 100")
            tasks = kb.list_tasks(conn, status=status_filter, tenant=tenant, include_archived=status_filter == "archived", limit=limit, order_by="updated")
            result = {"tasks": [task_value(task) for task in tasks], "count": len(tasks)}
        elif action == "show":
            result = show(conn, identifier(request.get("task_id"), "task_id"), tenant)
        elif action == "create":
            title = text(request.get("title"), "title", 200)
            body = text(request.get("body", ""), "body", 8000, empty=True)
            priority = request.get("priority", 0)
            require(isinstance(priority, int) and not isinstance(priority, bool) and -100 <= priority <= 100, "priority must be from -100 through 100")
            parents = request.get("parents", [])
            require(isinstance(parents, list) and len(parents) <= 20, "parents must be a list with at most 20 items")
            parents = [identifier(item, "parent task ID") for item in parents]
            initial_status = identifier(request.get("initial_status", "ready"), "initial_status")
            require(initial_status in CREATE_STATUSES, "initial_status must be triage or ready")
            key = request.get("idempotency_key")
            if key is not None:
                key = identifier(key, "idempotency_key")
            session_id = request.get("session_id")
            if session_id is not None:
                session_id = identifier(session_id, "session_id")
            task_id = kb.create_task(
                conn,
                title=title,
                body=body or None,
                created_by=CREATOR,
                workspace_kind="scratch",
                tenant=tenant,
                priority=priority,
                parents=parents,
                idempotency_key=key,
                triage=initial_status == "triage",
                initial_status="running",
                session_id=session_id,
                completion_contract="local-only",
            )
            result = show(conn, task_id, tenant)
        elif action == "comment":
            task_id = identifier(request.get("task_id"), "task_id")
            show(conn, task_id, tenant)
            kb.add_comment(conn, task_id, CREATOR, text(request.get("comment"), "comment", 8000))
            result = show(conn, task_id, tenant)
        elif action == "move":
            task_id = identifier(request.get("task_id"), "task_id")
            show(conn, task_id, tenant)
            transition = identifier(request.get("transition"), "transition")
            require(transition in TRANSITIONS, "unsupported transition")
            reason = text(request.get("reason", ""), "reason", 2000, empty=True) or None
            summary = text(request.get("summary", ""), "summary", 4000, empty=True) or None
            if transition == "schedule":
                ok = kb.schedule_task(conn, task_id, reason=reason)
            elif transition == "block":
                ok = kb.block_task(conn, task_id, reason=reason, kind="needs_input")
            elif transition == "unblock":
                ok = kb.unblock_task(conn, task_id)
            elif transition == "request_review":
                ok = kb.request_review(conn, task_id, summary=summary, metadata={"ssot_authority": "none"}, reviewer=CREATOR, force=True)
                ok = ok[0] if isinstance(ok, tuple) else ok
            elif transition == "request_changes":
                ok, _ = kb.request_changes(conn, task_id, reason=reason or "Changes requested by Pi coordinator")
            elif transition == "reopen_review":
                ok = kb.reopen_review_task(conn, task_id)
            elif transition == "complete":
                ok = kb.complete_task(conn, task_id, summary=summary, metadata={"ssot_authority": "none"}, fire_lifecycle_hook=False)
            elif transition == "archive":
                ok = kb.archive_task(conn, task_id)
            else:
                raise AssertionError("unreachable transition")
            require(bool(ok), "transition was rejected by the board state machine")
            result = show(conn, task_id, tenant)
        else:
            raise AdapterError("unsupported action")
    return {"schema": SCHEMA, "ok": True, "action": action, "result": result, "limits": ["Host-local board only.", "No dispatcher or worker launch.", "Board state has no SSOT, evidence, proof, or submission authority."]}


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(65537)
        require(0 < len(raw) <= 65536, "request size is invalid")
        request = json.loads(raw)
        print(json.dumps(execute(request), sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(json.dumps({"schema": SCHEMA, "ok": False, "error": str(exc)}, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
