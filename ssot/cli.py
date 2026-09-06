"""Command-line interface for the starter SSOT control plane."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from .control import (
    SSOTError,
    abandon_work,
    accept_project,
    prepare_work,
    project_status,
    submit_outputs,
    verify_stage,
)
from .workflow import doctor_project, init_project, next_work, run_stage_command


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def _read_json_argument(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SSOTError(f"cannot read {label}: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Harness-neutral, receipt-gated SSOT controller"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="project directory containing ssot-project.json",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create a source-bound unresolved scaffold")
    init.add_argument("--prd", required=True, help="exact PRD path relative to root")
    init.add_argument("--project-id", required=True)
    sub.add_parser("doctor", help="diagnose whether the contract can issue work")
    sub.add_parser("next", help="preview agent-ready packets on the current frontier")
    sub.add_parser("status", help="derive the current frontier and authority")
    prepare = sub.add_parser(
        "prepare", help="issue an immutable work order for one frontier stage"
    )
    prepare.add_argument("stage")
    prepare.add_argument("--worker", required=True)
    prepare.add_argument(
        "--runtime-file",
        type=Path,
        required=True,
        help="host-observed runtime identity JSON",
    )
    submit = sub.add_parser(
        "submit", help="hash outputs and create a same-run producer receipt"
    )
    submit.add_argument("run_id")
    submit.add_argument("--worker", required=True)
    submit.add_argument(
        "--execution-file",
        type=Path,
        required=True,
        help="host-observed execution receipt JSON",
    )
    verify = sub.add_parser(
        "verify", help="run the configured independent stage verifier"
    )
    verify.add_argument("run_id")
    abandon = sub.add_parser(
        "abandon", help="close an interrupted work order without authority"
    )
    abandon.add_argument("run_id")
    abandon.add_argument("--reason", required=True)
    accept = sub.add_parser("accept", help="run whole-project independent acceptance")
    accept.add_argument("--acceptor", required=True)
    run_parser = sub.add_parser(
        "run", help="host-launch one stage, record execution, and verify it"
    )
    run_parser.add_argument("stage")
    run_parser.add_argument("--worker", required=True)
    run_parser.add_argument("--runtime-file", type=Path, required=True)
    run_parser.add_argument("--timeout-seconds", type=int, default=3600)
    raw_args = sys.argv[1:]
    host_command: list[str] = []
    if "--" in raw_args:
        marker = raw_args.index("--")
        host_command = raw_args[marker + 1 :]
        raw_args = raw_args[:marker]
    args = parser.parse_args(raw_args)
    if host_command and args.command != "run":
        parser.error("-- COMMAND is valid only with run")

    def prepare_call() -> Any:
        runtime = _read_json_argument(args.runtime_file, "runtime identity")
        return prepare_work(args.root, args.stage, args.worker, runtime)

    def submit_call() -> Any:
        execution = _read_json_argument(args.execution_file, "execution receipt")
        return submit_outputs(args.root, args.run_id, args.worker, execution)

    def run_call() -> Any:
        runtime = _read_json_argument(args.runtime_file, "runtime identity")
        return run_stage_command(
            args.root,
            args.stage,
            args.worker,
            runtime,
            host_command,
            timeout_seconds=args.timeout_seconds,
        )

    calls: dict[str, Callable[[], Any]] = {
        "init": lambda: init_project(args.root, args.prd, args.project_id),
        "doctor": lambda: doctor_project(args.root),
        "next": lambda: next_work(args.root),
        "status": lambda: project_status(args.root),
        "prepare": prepare_call,
        "submit": submit_call,
        "verify": lambda: verify_stage(args.root, args.run_id),
        "abandon": lambda: abandon_work(args.root, args.run_id, args.reason),
        "accept": lambda: accept_project(args.root, args.acceptor),
        "run": run_call,
    }
    try:
        result = calls[args.command]()
    except SSOTError as exc:
        parser.exit(2, f"SSOT HOLD: {exc}\n")
    _print(result)
    if isinstance(result, dict) and result.get("status") == "failed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
