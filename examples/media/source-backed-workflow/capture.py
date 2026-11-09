"""Capture a bounded, real offline SSOT fixture without publishing host artifacts.

This runs the public examples/enforced-task scripted fixture in a disposable copy.
It does not launch Pi, a model server, a browser, a desktop app or a GPU job.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[3]
SCHEMA = "stuaim-offline-workflow-capture/v1"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_source_sha(path: Path) -> str:
    """SHA-256 of tracked textual source with canonical LF endings.

    Core controller .py files can check out with CRLF on Windows, unlike Git
    blob text. This digest binds identical source meaning across both hosts;
    it does not claim to be the raw OS file-byte hash on Windows.
    """
    if path.is_symlink() or not path.is_file():
        raise ValueError("Public source identity changed")
    raw = path.read_bytes()
    if b"\x00" in raw:
        raise ValueError("Public source is not a text file")
    return sha(raw.replace(b"\r\n", b"\n"))


def capture(repo: Path = ROOT) -> dict:
    repo = repo.resolve(strict=True)
    source = repo / "examples/enforced-task"
    if not (source / "demo.py").is_file() or not (repo / "ssot/control.py").is_file():
        raise ValueError("Supply a real public harness repository")
    with tempfile.TemporaryDirectory(prefix="public-agent-workflow-") as td:
        copied = Path(td) / "fixture"
        shutil.copytree(source, copied)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        process = subprocess.run(
            [sys.executable, "demo.py"],
            cwd=copied,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
        )
        if (
            process.returncode
            or len(process.stdout) > 65536
            or len(process.stderr) > 65536
        ):
            raise ValueError("Offline script fixture did not complete cleanly")
        status = json.loads(process.stdout)
        receipt = json.loads(
            (copied / "artifacts/enforcement-receipt.json").read_text(encoding="utf-8")
        )
        output = (copied / "artifacts/result.txt").read_bytes()
        attempts = receipt.get("attempts", [])
        if not (
            status.get("project_id") == "enforced-task-example"
            and status.get("accepted") is True
            and status.get("complete") is True
            and status.get("authority_cap") == "tested"
            and status.get("authority_state") == "tested"
            and status.get("stages_verified") is True
            and len(status.get("stages", [])) == 1
            and status["stages"][0].get("state") == "verified"
            and receipt.get("status") == "accepted"
            and receipt.get("accepted_attempt") == 2
            and len(attempts) == 2
            and attempts[0].get("status") == "rejected"
            and attempts[0].get("verifier_exit_code") == 1
            and attempts[1].get("status") == "accepted"
            and attempts[1].get("verifier_exit_code") == 0
            and receipt.get("authority_cap") == "tested"
            and receipt.get("task_id") == "offline-enforced-example"
            and receipt.get("outputs", [{}])[0].get("sha256") == sha(output)
            and output.decode("utf-8").strip()
            == "accepted: admitted research and corrective retry were used"
        ):
            raise ValueError(
                "Fixture outcomes differ from the recorded public test contract"
            )

        # Do not export the fixture's local paths, run identifiers, process
        # traces, email, environment, full project files or raw private logs.
        return {
            "schema": SCHEMA,
            "kind": "scripted_offline_fixture",
            "product_ui_captured": False,
            "live_model_invoked": False,
            "project": status["project_id"],
            "task": receipt["task_id"],
            "source_hash_mode": "canonical_lf_text_sha256",
            "source": {
                relative: canonical_source_sha(repo / relative)
                for relative in (
                    "examples/enforced-task/demo.py",
                    "examples/enforced-task/task.json",
                    "examples/enforced-task/verify_result.py",
                    "examples/enforced-task/worker.py",
                    "ssot/control.py",
                )
            },
            "workflow": [
                {"step": "source_bound_task", "requirements": 1, "state": "admitted"},
                {
                    "step": "worker_attempt_1",
                    "status": "rejected",
                    "verifier_exit_code": 1,
                },
                {"step": "corrective_feedback", "reason_class": "verification_failure"},
                {
                    "step": "worker_attempt_2",
                    "status": "accepted",
                    "verifier_exit_code": 0,
                },
                {"step": "independent_project_acceptance", "state": "tested"},
            ],
            "result": {
                "accepted": True,
                "complete": True,
                "authority_cap": "tested",
                "stage_state": "verified",
                "result_sha256": sha(output),
                "result_text": output.decode("utf-8").strip(),
            },
            "limitations": [
                "visualization of a real scripted offline fixture, not a desktop screenshot",
                "no local language model was exercised",
                "local tested does not establish externally blessed",
            ],
        }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, help="Optional new JSON output; refuses to overwrite"
    )
    args = parser.parse_args(argv)
    try:
        record = capture()
        value = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        if args.output is None:
            print(value, end="")
        else:
            if args.output.is_symlink() or args.output.exists():
                raise ValueError("Refuse overwriting an existing capture")
            with args.output.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(value)
            print(
                json.dumps(
                    {
                        "status": "captured",
                        "sha256": sha(value.encode("utf-8")),
                        "output": args.output.name,
                    },
                    sort_keys=True,
                )
            )
    except (
        OSError,
        ValueError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ) as error:
        print(
            json.dumps({"status": "refused", "reason": type(error).__name__}),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
