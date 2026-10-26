"""Inspect the selected home's native Hermes jobs, attempts and local output.

This module never imports the scheduler, repairs a store, creates a job or
dispatches an agent. SQLite read transactions can use coordination sidecars.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import time

from harness import home as factory, home_entry
from scripts.build_project_board_assets import native_source_identity


SCHEMA = "agent-home-scheduling/v1"
MAX_JSON = 2 * 1024**2
MAX_DATABASE = 256 * 1024**2
MAX_RESULT = 8 * 1024**2
MAX_OUTPUT = 65536
RESULT_PREFIX = 8192
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
OUTPUT_NAME = re.compile(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.md\Z")


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selected_path(home, relative):
    path = home / relative
    require(path.is_relative_to(home), "Native store path escaped this home")
    current = home
    for part in path.relative_to(home).parts:
        current /= part
        require(not current.is_symlink(), "Native scheduling path is redirected")
    require(path.resolve() == path, "Native scheduling path is an alias")
    return path


def read_file(path, maximum):
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "Use a regular native store file")
    if hasattr(os, "getuid"):
        require(info.st_uid == os.getuid(), "Native store belongs to another owner")
    require(info.st_size <= maximum, "Native file exceeds this bounded inspection limit")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    after = path.stat()
    require(len(raw) <= maximum and (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
            "Native file changed during inspection; inspect again")
    return raw


def source_binding(home, config):
    manifest_path = selected_path(home, "runtime/runtime-manifest.json")
    require(digest(manifest_path) == config.get("runtime_manifest_sha256"), "Home runtime manifest changed")
    manifest = json.loads(read_file(manifest_path, 4 * 1024**2))
    files = {row["path"]: row["sha256"] for row in manifest["files"]}
    closure = ("harness/scheduling.py", "harness/home.py", "harness/home_entry.py",
               "scripts/build_project_board_assets.py")
    require(all(name in files and digest(selected_path(home, "runtime/" + name)) == files[name]
                for name in closure), "Scheduling runtime source changed or is not installed")
    require(digest(Path(__file__)) == files["harness/scheduling.py"], "Scheduling reader differs from this home")
    record = config.get("installed", {}).get("hermes")
    require(isinstance(record, dict), "Hermes is not installed in this home; use the reviewed source installer")
    require(config.get("selected_packages", {}).get("hermes") == factory.PINS["hermes"], "Selected Hermes package pin differs")
    require(factory.check_package(home, "hermes", record) is None, "Installed Hermes package changed")
    native = selected_path(home, "packages/hermes-source")
    require(native.is_dir(), "Installed native Hermes source is missing")
    identity = native_source_identity(native, factory.GIT_SOURCES["hermes"][1])
    return {"commit": identity["commit"], "tree": identity["tree"], "tracked_source": identity["tracked_source"]}


def text(value, maximum=2048):
    require(value is None or isinstance(value, str), "Native record has an unsupported text field")
    require(value is None or len(value) <= maximum, "Native record text exceeds its inspection limit")
    return value


def identifier(value):
    require(isinstance(value, str) and IDENTIFIER.fullmatch(value), "Use an exact native job ID")
    return value


def jobs(home, limit):
    path = selected_path(home, "state/hermes/cron/jobs.json")
    if not path.exists():
        return {"state": "missing", "rows": [], "reason": "No native job store exists; no store was created."}
    value = json.loads(read_file(path, MAX_JSON))
    require(isinstance(value, dict) and isinstance(value.get("jobs"), list),
            "Native job store needs explicit native inspection or repair; no automatic repair was attempted")
    require(len(value["jobs"]) <= 5000 and all(isinstance(row, dict) for row in value["jobs"]), "Native job store exceeds its schema limit")
    rows, seen = [], set()
    for row in value["jobs"]:
        key = identifier(row.get("id"))
        require(key not in seen, "Native job IDs are duplicated; no repair was attempted")
        seen.add(key)
        require(type(row.get("enabled")) is bool, "Native enabled flag is unavailable")
        rows.append({"id": key, "enabled": row["enabled"], **{field: text(row.get(field)) for field in
                     ("name", "state", "schedule_display", "next_run_at", "last_run_at", "last_status", "last_error", "paused_reason")}})
    return {"state": "present", "total": len(rows), "truncated": len(rows) > limit, "rows": rows[:limit],
            "limits": "Native stored fields only; planned time and enabled state do not prove a running ticker or execution."}


def runs(home, job_id, limit):
    if job_id is not None:
        identifier(job_id)
    path = selected_path(home, "state/hermes/cron/executions.db")
    if not path.exists():
        return {"state": "missing", "rows": [], "reason": "No native execution history exists; no database was created."}
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= MAX_DATABASE, "Unsupported native execution database")
    if hasattr(os, "getuid"):
        require(info.st_uid == os.getuid(), "Native history belongs to another owner")
    for suffix in ("-wal", "-shm", "-journal"):
        selected_path(home, "state/hermes/cron/executions.db" + suffix)
    deadline = time.monotonic() + 5
    fields = ("id", "job_id", "source", "status", "claimed_at", "started_at", "finished_at", "error", "delivery_outcome", "scheduled_instant")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        columns = {row[1] for row in db.execute("PRAGMA table_info(executions)")}
        require(set(fields).issubset(columns), "Native history schema differs; no migration was attempted")
        db.execute("BEGIN")
        query = "SELECT " + ",".join(fields) + " FROM executions"
        parameters = []
        if job_id is not None:
            query += " WHERE job_id=?"
            parameters.append(job_id)
        query += " ORDER BY claimed_at DESC,id DESC LIMIT ?"
        parameters.append(limit + 1)
        selected = db.execute(query, parameters).fetchall()
    rows = []
    for values in selected[:limit]:
        row = {field: text(value) for field, value in zip(fields, values)}
        require(row["status"] in {"claimed", "running", "completed", "failed", "unknown"}, "Native execution status is unsupported")
        identifier(row["job_id"])
        rows.append(row)
    return {"state": "present", "truncated": len(selected) > limit, "rows": rows,
            "limits": "Native execution outcomes are not checked-file acceptance. Missed or paused schedules can have no execution row.",
            "sqlite_access": "Read transaction only; SQLite may use existing or create coordination sidecars. No schema or job repair."}


def result(home, job_id, filename):
    identifier(job_id)
    directory = selected_path(home, "state/hermes/cron/output/" + job_id)
    if not directory.exists():
        return {"state": "missing", "reason": "No retained local output exists for this job."}
    require(directory.is_dir(), "Native output directory is unsupported")
    if filename is None:
        names = []
        for count, item in enumerate(directory.iterdir()):
            require(count < 1000, "Native output directory exceeds this inspection limit")
            if OUTPUT_NAME.fullmatch(item.name):
                names.append(item.name)
        if not names:
            return {"state": "missing", "reason": "No native Markdown output file is retained."}
        filename = max(names)
    require(isinstance(filename, str) and OUTPUT_NAME.fullmatch(filename), "Use an exact native output filename")
    path = selected_path(home, "state/hermes/cron/output/" + job_id + "/" + filename)
    require(path.is_file(), "Selected native output is missing")
    raw = read_file(path, MAX_RESULT)
    full = raw.decode("utf-8")
    prefix = full.encode()[:RESULT_PREFIX].decode("utf-8", errors="ignore")
    return {"state": "present", "job_id": job_id, "filename": filename,
            "path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "file_bytes": len(raw),
            "text": prefix, "truncated": len(prefix.encode()) != len(raw),
            "content_scope": "prefix" if len(prefix.encode()) != len(raw) else "complete_file",
            "execution_link": "not_established", "checked_file_acceptance": "not_established",
            "limits": "This is saved native output text. A filename or scheduler completion does not verify its claims or link it to a particular execution."}


def inspect(value, action, *, job_id=None, filename=None, limit=20):
    require(type(limit) is int and 1 <= limit <= 50, "Select a limit from1 to50")
    require(action in {"list", "runs", "result"}, "Only list, runs and result inspection are supported")
    home, config = home_entry.selected_home(value)
    with home_entry.consumer(home):
        home, config = home_entry.selected_home(home)
        config_sha = digest(home / "home.json")
        binding = source_binding(home, config)
        if action == "list":
            observation = jobs(home, limit)
        elif action == "runs":
            observation = runs(home, job_id, limit)
        else:
            observation = result(home, job_id, filename)
        require(digest(home / "home.json") == config_sha and source_binding(home, config) == binding,
                "Home or native source changed during inspection; no result was delivered")
        report = {"schema": SCHEMA, "home": str(home), "action": action, "authority": "none",
                  "generative_requests": 0, "scheduler_started": False, "jobs_dispatched": 0,
                  "native_source": binding, "observation": observation,
                  "recurring_managed_agent": "not_qualified", "ticker_liveness": "not_inspected"}
        require(len(json.dumps(report).encode()) <= MAX_OUTPUT, "Scheduling report exceeds its delivery limit")
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--home", required=True, type=Path)
    commands = parser.add_subparsers(dest="operation", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--limit", type=int, default=20)
    history = commands.add_parser("runs")
    history.add_argument("--job")
    history.add_argument("--limit", type=int, default=20)
    output = commands.add_parser("result")
    output.add_argument("job")
    output.add_argument("filename", nargs="?")
    args = parser.parse_args(argv)
    try:
        report = inspect(args.home, args.operation, job_id=getattr(args, "job", None),
                         filename=getattr(args, "filename", None), limit=getattr(args, "limit", 20))
        print(json.dumps(report, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        print(json.dumps({"schema": SCHEMA, "status": "unavailable", "error": str(error), "authority": "none"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
