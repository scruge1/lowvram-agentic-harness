"""Offline demonstration. Run this file from any copied example directory."""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[2]
if (REPO / "ssot").is_dir():
    sys.path.insert(0, str(REPO))

from ssot.control import (  # noqa: E402
    accept_project,
    project_status,
)
from ssot.workflow import run_stage_command  # noqa: E402


def main():
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    runtime = json.loads((ROOT / "runtime-script.json").read_text(encoding="utf-8"))

    run_stage_command(
        ROOT,
        "plan",
        "example-worker",
        runtime,
        [
            sys.executable,
            "-c",
            (
                "import json; from pathlib import Path; "
                "Path('artifacts').mkdir(exist_ok=True); "
                "Path('artifacts/plan.json').write_text("
                "json.dumps({'project':'starter','steps':['plan','build']})+'\\n')"
            ),
        ],
    )
    run_stage_command(
        ROOT,
        "build",
        "example-worker",
        runtime,
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; "
                "Path('artifacts/result.txt').write_text('starter: plan-used\\n')"
            ),
        ],
    )
    accept_project(ROOT, "independent-example-acceptor")

    print(json.dumps(project_status(ROOT), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
