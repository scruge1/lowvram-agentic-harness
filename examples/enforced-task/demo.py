"""Offline composed demo: research, retry, enforcement receipt, and SSOT acceptance."""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[2]
if (REPO / "ssot").is_dir():
    sys.path.insert(0, str(REPO))

from ssot.control import accept_project, project_status  # noqa: E402
from ssot.workflow import run_stage_command  # noqa: E402


def main():
    runtime = json.loads((ROOT / "runtime-script.json").read_text(encoding="utf-8"))
    result = run_stage_command(
        ROOT,
        "execute",
        "portable-supervisor",
        runtime,
        [
            sys.executable,
            "-m",
            "harness.enforcement",
            "run",
            "--root",
            str(ROOT),
            "--spec",
            str(ROOT / "task.json"),
        ],
    )
    if result["status"] != "verified":
        raise RuntimeError(f"stage failed: {result}")
    accept_project(ROOT, "independent-example-acceptor")
    print(json.dumps(project_status(ROOT), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
