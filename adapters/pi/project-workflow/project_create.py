"""Create one named managed project through the existing home factory."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


SCHEMA = "pi-kanban-result/v1"
RELATIVE = "adapters/pi/project-workflow/project_create.py"
GIT_PATH_OVERRIDES = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                      "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                      "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT")


def require(value, message):
    if not value:
        raise ValueError(message)


def selected_target(home, name):
    require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", name),
            "Use a short project name: a letter or digit, then letters, digits, hyphens or underscores (80 maximum).")
    require(not any(key in os.environ for key in GIT_PATH_OVERRIDES),
            "Git path override environment is unsupported for managed project creation.")
    state = home / "state/projects"
    require(state.parent.is_dir() and not state.is_symlink() and state.resolve() == state
            and (not state.exists() or state.is_dir()), "Managed project state must stay under its canonical home directory.")
    projects = home / "projects"
    require(projects.is_dir() and not projects.is_symlink() and projects.resolve() == projects,
            "The managed projects directory must be an existing canonical directory.")
    root = projects / name
    require(not root.exists() and not root.is_symlink(),
            "Project destination already exists. Preserve it and use project_admit without initialize to inspect/adopt its existing identity.")
    return root


def bindings():
    file = Path(__file__).absolute()
    require(file.resolve() == file, "Managed project helper is redirected.")
    runtime = file.parents[3]
    home = runtime.parent
    require(runtime.name == "runtime" and os.environ.get("AGENT_HOME") == str(home)
            and home.resolve() == home and os.environ.get("PI_CODING_AGENT_DIR") == str(home / "agent")
            and os.environ.get("PI_PROJECT_STATE_BASE") == str(home / "state/projects"),
            "project_create requires this installed managed home's explicit environment.")
    config = json.loads((home / "home.json").read_text(encoding="utf-8"))
    manifest = runtime / "runtime-manifest.json"
    require(config.get("schema") == "agent-home/v1" and config.get("home") == str(home)
            and hashlib.sha256(manifest.read_bytes()).hexdigest() == config.get("runtime_manifest_sha256"),
            "Managed home/runtime binding differs.")
    records = json.loads(manifest.read_text(encoding="utf-8"))["files"]
    for item in records:
        path = runtime / item["path"]
        require(path.resolve().is_relative_to(runtime) and not path.is_symlink() and path.is_file()
                and hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"], "Managed runtime source drift.")
    require(any(item["path"] == RELATIVE for item in records), "Managed project helper is not declared.")
    guard = home / "home-lifecycle.py"
    require(guard.is_file() and not guard.is_symlink()
            and hashlib.sha256(guard.read_bytes()).hexdigest() == config.get("lifecycle_guard_sha256"),
            "Managed project creation requires the current home lifecycle guard.")
    return home, runtime


def create_project(home, name):
    """Delegate creation; preserve any partial directory if a prerequisite fails."""
    root = selected_target(home, name)
    from project_identity import _project_id
    state = home / "state/projects" / _project_id(root)
    require(not state.exists() and not state.is_symlink(),
            "Project state already exists. Preserve it; choose another new name or inspect/recover the original project before project_admit without initialize.")
    from harness import home as factory
    try:
        value = factory.project(home, name)
        require(root.resolve() == root and root.is_dir() and not root.is_symlink(), "Created project escaped its managed root.")
        require(all((root / name).is_file() and not (root / name).is_symlink() for name in ("AGENTS.md", ".gitignore"))
                and (root / ".git").is_dir() and not (root / ".git").is_symlink(), "Created project Git/instructions are incomplete.")
        observed = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                                  capture_output=True, text=True, encoding="utf-8", check=True, timeout=10)
        require(Path(observed.stdout.strip()).resolve() == root, "Created Git root differs.")
        result = value.get("result", {})
        require(value.get("schema") == SCHEMA and value.get("ok") is True and result.get("project_root") == str(root)
                and isinstance(result.get("identity", {}).get("project_id"), str)
                and isinstance(result.get("identity", {}).get("board_id"), str)
                and result.get("workspace", {}).get("state") == "scaffolded"
                and (root / ".icm/project.json").is_file() and not (root / ".icm/project.json").is_symlink(),
                "Created project admission is incomplete.")
        pointer = json.loads((root / ".icm/project.json").read_text(encoding="utf-8"))
        require(pointer.get("canonical_root") == str(root)
                and all(pointer.get(key) == result["identity"][key] for key in ("project_id", "board_id")),
                "Created identity pointer differs from board admission.")
        return {**value, "action": "project_create", "limits": [*value.get("limits", []),
                "Managed project creation selects no task and grants no execution permission."]}
    except Exception as error:
        if root.exists() or root.is_symlink():
            raise ValueError("Partial project preserved at " + str(root) + ". Inspect Git, instructions and ICM/board before "
                             "project_admit without initialize; do not recreate or reinitialize it. Cause: " + str(error)) from error
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--name", required=True)
    parser.add_argument("--perform", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        require(sys.platform == "linux", "Managed project creation requires Linux guarded process ownership.")
        home, runtime = bindings()
        selected_target(home, args.name)  # Refuse before Git or factory imports.
        sys.path.insert(0, str(runtime))
        from harness import home_entry
        if not args.perform:
            command = home_entry.guarded_command(home, [sys.executable, "-s", "-B", runtime / "pi-task-worker.py", "--guard",
                                                       sys.executable, "-s", "-B", Path(__file__), "--perform", "--name=" + args.name],
                                                  python=sys.executable)
            os.execvpe(command[0], command, {**os.environ, "PI_TASK_TIMEOUT": "90", "CUDA_VISIBLE_DEVICES": ""})
        with home_entry.consumer(home):
            print(json.dumps(create_project(home, args.name)))
        return 0
    except Exception as error:
        print(json.dumps({"schema": SCHEMA, "ok": False, "action": "project_create", "error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
