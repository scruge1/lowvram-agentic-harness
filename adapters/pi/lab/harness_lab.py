"""Inspect optional components or run the pinned, scripted Harness2 demo.

This fixed diagnostic has no model client. It does not grant project authority.
The native demo is Apache-2.0 Google Research code, installed separately from
https://github.com/google-research/harness2 at the home factory's exact pin.
"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from urllib.parse import urlsplit
from urllib.request import url2pathname


RELATIVE = "adapters/pi/lab/harness_lab.py"
SCHEMA = "harness-lab/v1"


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def environment(home):
    """Forward no provider credentials, proxy settings or Python overrides."""
    result = {key: os.environ[key] for key in ("HOME", "USER", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR")
              if key in os.environ}
    result.update({"PATH": str(home / "envs/harness2/bin") + os.pathsep + os.defpath,
                   "PYTHONDONTWRITEBYTECODE": "1", "CUDA_VISIBLE_DEVICES": "",
                   "PI_TASK_TIMEOUT": "120", "AGENT_HOME": str(home),
                   "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                   "TMPDIR": str(home / "cache/lab/tmp"), "XDG_CACHE_HOME": str(home / "cache/lab")})
    return result


def canonical_directory(path):
    require(path.is_dir() and not path.is_symlink() and path.resolve() == path,
            "Lab directory must stay inside its canonical managed home.")


def status(home):
    from harness import home as factory
    home, config = factory.load(home)
    require(config.get("profile") == "full" and config.get("selected_packages") ==
            {key: factory.PINS[key] for key in factory.PROFILES["full"]},
            "The optional lab requires the unchanged full package profile.")
    manifest = home / "runtime/runtime-manifest.json"
    require(sha(manifest) == config.get("runtime_manifest_sha256"), "Lab runtime manifest changed.")
    records = {item["path"]: item["sha256"] for item in json.loads(manifest.read_text(encoding="utf-8"))["files"]}
    for relative in (RELATIVE, "harness/home.py", "harness/home_entry.py", "pi-task-worker.py",
                     "pi_native_events.py", "native_pidfd.py"):
        path = home / "runtime" / relative
        require(path.is_file() and not path.is_symlink() and path.resolve() == path
                and records.get(relative) == sha(path), "Lab runtime source binding changed.")
    identities = {}
    for key in ("harness2", "deepseek"):
        record = config.get("installed", {}).get(key, {})
        require(record.get("requested") == factory.PINS[key], "Optional package is missing or has a different pin: " + key)
        require(factory.check_package(home, key, record) is None, "Optional package artifacts changed: " + key)
        identities[key] = {"requested": record["requested"], "recorded_artifacts": len(record["artifacts"])}
    expected_url, expected_commit = factory.GIT_SOURCES["harness2"]
    urls = [Path(item["path"]) for item in config["installed"]["harness2"]["artifacts"]
            if Path(item["path"]).name == "direct_url.json"]
    require(len(urls) == 1, "Harness2 direct URL identity is missing.")
    direct = json.loads(urls[0].read_text(encoding="utf-8"))
    checkout = home / "packages/harness2-source"
    canonical_directory(checkout)
    uri = urlsplit(direct.get("url", ""))
    require(uri.scheme == "file" and not uri.netloc and Path(url2pathname(uri.path)).resolve() == checkout,
            "Harness2 must come from this home's pinned source checkout.")
    env = environment(home)
    head = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True, timeout=10, env=env).stdout.strip()
    require(head == expected_commit, "Harness2 source commit differs from the selected pin.")
    clean = subprocess.run(["git", "-C", str(checkout), "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True, check=True, timeout=10, env=env)
    require(not clean.stdout.strip(), "Harness2 source checkout has tracked changes.")
    metadata = urls[0].parent
    site = metadata.parent
    tracked = subprocess.run(["git", "-C", str(checkout), "ls-files", "-z"], capture_output=True,
                             check=True, timeout=10, env=env).stdout
    require(len(tracked) <= 512 * 1024, "Harness2 tracked source list exceeds its bound.")
    code = []
    for relative in tracked.decode("utf-8").split("\0"):
        parts = Path(relative).parts
        if relative.endswith(".py") and parts and (parts[0] == "harness2" or parts[:2] == ("src", "harness2")):
            target = Path(*parts[1:]) if parts[0] == "src" else Path(relative)
            source, installed = checkout / relative, site / target
            require(source.is_file() and not source.is_symlink() and installed.is_file() and not installed.is_symlink()
                    and installed.resolve().is_relative_to(site) and sha(installed) == sha(source),
                    "Installed Harness2 code differs from its pinned source.")
            code.append(target.as_posix())
    require("harness2/demo.py" in code and "harness2/cli/demo.py" in code,
            "Pinned native deterministic demo source is missing.")
    package = home / "packages/deepseek/node_modules/@deepseek-ai/dsh/package.json"
    require(json.loads(package.read_text(encoding="utf-8"))["version"] == factory.PINS["deepseek"].rsplit("@", 1)[1],
            "DeepSeek component version differs.")
    identities["harness2"].update({"source": expected_url, "commit": head,
                                    "verified_code_files": len(code),
                                    "demo_source_sha256": sha(site / "harness2/demo.py")})
    return {"schema": SCHEMA, "ok": True, "action": "status", "components": identities,
            "scope": "recorded package identity; deterministic demo not run", "model_calls": 0,
            "experiment": "held; no portable model experiment is configured"}


def check_answers(root):
    """Check selected results independently from the native demo's done count."""
    report = json.loads((root / "demo.json").read_text(encoding="utf-8"))
    require(report.get("done") == 2 and report.get("failed") == 0, "Native demo did not finish both tasks.")
    summaries = list((root / "runs").rglob("summary.json"))
    require(len(summaries) == 2, "Expected exactly two native task summaries.")
    checked = {}
    fixed = {"ledger-1": ["100.25", "-20.10", "5.00"], "ledger-2": ["35.50", "-10.25", "-5.00"]}
    for file in summaries:
        require(not file.is_symlink() and file.resolve().is_relative_to(root), "Native summary escaped its run.")
        value = json.loads(file.read_text(encoding="utf-8"))
        task = value.get("task_id")
        require(task in fixed and task not in checked and value.get("status") in ("ok", "skipped"),
                "Native task identity/status differs.")
        source = root / "sources" / task / "ledger.csv"
        with source.open(encoding="utf-8", newline="") as stream:
            amounts = [row["amount"] for row in csv.DictReader(stream)]
        require(amounts == fixed[task], "Controlled signed ledger input changed.")
        expected = "Total: %.2f" % sum((Decimal(item) for item in amounts), Decimal(0))
        selections = value.get("selections", {})
        require(set(selections) == {"agg", "seq"}, "Both native recursion modes must select an answer.")
        checked[task] = {}
        for mode, selection in selections.items():
            run = Path(selection.get("chosen_run_dir", ""))
            answer = run / "answer.txt"
            require(run.is_absolute() and run.resolve().is_relative_to(root / "executions")
                    and answer.is_file() and not answer.is_symlink() and answer.stat().st_size <= 1024,
                    "Selected native answer is missing or outside this run.")
            require(answer.read_text(encoding="utf-8").strip() == expected, "Selected answer omitted or changed a signed amount.")
            checked[task][mode] = {"expected": expected, "answer_sha256": sha(answer)}
    return checked


def demo(home):
    status(home)  # Missing/wrong packages refuse before native demo dispatch.
    require(sys.platform == "linux", "The demo requires Linux guarded process ownership.")
    for relative in ("state", "state/harness-lab", "state/harness-lab/runs", "cache", "cache/lab", "cache/lab/tmp"):
        target = home / relative
        if not target.exists():
            target.mkdir(mode=0o700)
        canonical_directory(target)
    run = home / "state/harness-lab/runs" / uuid.uuid4().hex
    run.mkdir(mode=0o700)
    output = run / "demo"
    python = home / "envs/harness2/bin/python"
    result = {"schema": SCHEMA, "ok": False, "action": "demo", "run": str(run),
              "scope": "upstream deterministic signed-ledger adaptation; no model quality claim", "model_calls": 0}
    try:
        with (run / "stdout.log").open("xb") as stdout, (run / "stderr.log").open("xb") as stderr:
            process = subprocess.run([str(python), "-I", "-B", "-m", "harness2.cli.demo", "--output", str(output), "--k", "1", "--mode", "both"],
                                     cwd=home, env=environment(home), stdin=subprocess.DEVNULL,
                                     stdout=stdout, stderr=stderr, timeout=110)
        result["exit_code"] = process.returncode
        require(process.returncode == 0, "Native demo failed; inspect its retained logs.")
        result["checks"] = check_answers(output)
        result["ok"] = True
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result["error"] = str(error)[:700]
    (run / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--action", choices=("status", "demo", "experiment"), required=True)
    args = parser.parse_args(argv)
    try:
        file = Path(__file__).absolute()
        require(file.resolve() == file and args.home.is_absolute() and args.home.resolve() == args.home
                and file == args.home / "runtime" / RELATIVE, "Use this home's installed, source-bound lab helper.")
        sys.path.insert(0, str(args.home / "runtime"))
        require(args.action != "experiment", "Model experiments are held; only status and deterministic demo are supported.")
        from harness import home_entry
        with home_entry.consumer(args.home):
            value = demo(args.home) if args.action == "demo" else status(args.home)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        value = {"schema": SCHEMA, "ok": False, "action": args.action, "error": str(error)[:700]}
    print(json.dumps(value, ensure_ascii=False))
    return 0 if value["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
