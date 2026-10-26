"""Capture one stopped owned project; restore verified files into a new export.

An export retains the original path-bound identity. It is not an admitted project
migration. Agent credentials, native sessions, packages and global memory are
outside this explicitly selected project/state snapshot.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import subprocess
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import home_entry, maintenance, runtime_update, session_resume

SCHEMA = "agent-project-backup/v1"
LIMIT = 16 * 1024 * 1024
DEFAULT_BYTES = 4 * 1024**3
DEFAULT_FILES = 20000


class BackupError(ValueError):
    pass


def require(value, message):
    if not value:
        raise BackupError(message)


def check_time(deadline, stage):
    require(time.monotonic() < deadline, stage + " deadline exceeded")


def budget(seconds):
    require(isinstance(seconds, (int, float)) and 0 < seconds <= 86400, "Supply a finite operation budget up to86400s")
    return time.monotonic() + seconds


def canonical(value):
    path = Path(value).expanduser()
    require(path.is_absolute() and ".." not in path.parts and path.resolve(strict=True) == path,
            "Use an existing absolute path without aliases")
    return path


def regular(path, *, directory=False):
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode), "Unsupported file type: " + str(path))
    require(not path.is_symlink(), "Symlinks are outside the backup scope")
    require(path.resolve() == path, "Redirected backup path")
    if hasattr(os, "getuid"):
        require(info.st_uid == os.getuid(), "Backup input belongs to another owner")
    if not directory:
        require(info.st_nlink == 1, "Hardlinked files are outside the backup scope")
    return info


def digest(path, deadline):
    regular(path)
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            check_time(deadline, "File hashing")
            result.update(block)
    return result.hexdigest()


def json_new(path, value):
    raw = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    require(len(raw) <= LIMIT, "Backup manifest exceeds its byte limit")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, 0o600)


def new_destination(value, forbidden):
    path = Path(value).expanduser()
    require(path.is_absolute() and ".." not in path.parts, "Use an explicit absolute destination")
    parent = canonical(path.parent)
    regular(parent, directory=True)
    require(not path.exists() and not path.is_symlink(), "Destination already exists; retain it and select a new destination")
    for source in forbidden:
        require(path != source and source not in path.parents and path not in source.parents,
                "Destination overlaps a captured tree")
    return path


def git_check(root, deadline, pass_fds=()):
    regular(root / ".git", directory=True)
    require(not (root / ".git/objects/info/alternates").exists(), "External Git object stores are unsupported")
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
    kwargs = {"pass_fds": pass_fds} if os.name == "posix" else {}
    check_time(deadline, "Git inspection")
    result = subprocess.run(["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root),
                             "rev-parse", "--show-toplevel", "--absolute-git-dir"],
                            env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=min(15, deadline-time.monotonic()), **kwargs)
    require(result.returncode == 0 and len(result.stdout) < 16384, "Native Git inspection refused")
    lines = result.stdout.decode("utf-8").splitlines()
    require(len(lines) == 2 and Path(lines[0]).resolve() == root and Path(lines[1]).resolve() == root / ".git",
            "Use a self-contained project Git directory, not a linked worktree")
    return {"native_git": "self_contained", "git_directory": ".git"}


def selection(home, project, deadline, pass_fds):
    """Reuse the installed native identity validator without ambient state paths."""
    root = canonical(project)
    regular(root, directory=True)
    helper = home / "runtime/adapters/pi/project-workflow/project_identity.py"
    manifest = home / "runtime/runtime-manifest.json"
    _, config = maintenance.bootstrap.load(home)
    require(digest(manifest, deadline) == config["runtime_manifest_sha256"], "Installed runtime manifest drift")
    declared = maintenance.read_json(manifest)
    matches = [entry["sha256"] for entry in declared["files"] if entry["path"] == "adapters/pi/project-workflow/project_identity.py"]
    require(len(matches) == 1 and digest(helper, deadline) == matches[0], "Installed project identity helper drift")
    env = dict(os.environ, PI_PROJECT_STATE_BASE=str(home / "state/projects"))
    check_time(deadline, "Project selection")
    result = subprocess.run([sys.executable, "-I", "-B", str(helper), "status", "--root", str(root)],
                            env=env, stdin=subprocess.DEVNULL, capture_output=True,
                            timeout=min(15, deadline-time.monotonic()), pass_fds=pass_fds)
    require(result.returncode == 0 and len(result.stdout) <= 131072, "Native project identity validation refused")
    supplied = json.loads(result.stdout)["identity"]
    _, identity_hash = session_resume._project(home, root, supplied)
    identity, checked_hash = session_resume._json(root / ".icm/project.json")
    require(checked_hash == identity_hash and identity == supplied, "Native project identity changed")
    state = canonical(identity["state_root"])
    regular(state, directory=True)
    require(root != home and root not in home.parents and (home not in root.parents or home / "projects" in root.parents),
            "Select a project tree, not this agent home's control/state trees")
    require(root not in state.parents and state not in root.parents, "Project/state trees overlap")
    require(identity["board_id"] == "project:" + identity["project_id"], "Project board tenant differs")
    for name in ("kanban.db", "knowledge.db"):
        regular(state / name)
    return root, state, identity, identity_hash


def inventory(roots, deadline, max_bytes, max_files):
    require(isinstance(max_bytes, int) and max_bytes > 0 and isinstance(max_files, int) and 0 < max_files <= 100000,
            "Supply positive byte/file limits (at most100000files)")
    files, directories, databases, total_bytes = {}, [], set(), 0
    for label, root in roots.items():
        regular(root, directory=True)
        for directory, names, names_files in os.walk(root, followlinks=False):
            check_time(deadline, "Source inventory")
            folder = Path(directory)
            regular(folder, directory=True)
            relative = folder.relative_to(root).as_posix()
            directories.append(label if relative == "." else label + "/" + relative)
            require(len(directories) + len(files) <= max_files, "Project exceeds the explicit entry quota")
            for name in names:
                regular(folder / name, directory=True)
            for name in names_files:
                path = folder / name
                info = regular(path)
                key = label + "/" + path.relative_to(root).as_posix()
                files[key] = {"size": info.st_size, "mode": stat.S_IMODE(info.st_mode), "sha256": digest(path, deadline)}
                total_bytes += info.st_size
                with path.open("rb") as stream:
                    if stream.read(16) == b"SQLite format 3\x00":
                        databases.add(key)
                require(len(directories) + len(files) <= max_files and total_bytes <= max_bytes,
                        "Project exceeds the explicit file/byte quota")
    databases.update(("state/kanban.db", "state/knowledge.db"))
    omitted = {name for name in files if any(name == db + suffix for db in databases for suffix in ("-wal", "-shm", "-journal"))}
    # Preserve a WAL-content fingerprint to detect noncooperating writers. SHM
    # read marks are transient SQLite locks and are not copied or data evidence.
    journals = {name: files[name] for name in omitted if not name.endswith("-shm")}
    for name in omitted:
        del files[name]
    return {"files": files, "directories": sorted(directories), "databases": sorted(databases), "journals": journals}


def path_for(roots, name):
    parts = PurePosixPath(name)
    require(not parts.is_absolute() and len(parts.parts) > 1 and all(part not in ("..", ".", "") for part in parts.parts), "Unsafe backup member")
    require(parts.parts[0] in roots and "\\" not in name and ":" not in name, "Unknown backup tree")
    return roots[parts.parts[0]].joinpath(*parts.parts[1:])


def sqlite_copy(source, target, deadline):
    check_time(deadline, "SQLite backup")
    def progress(_status, _remaining, _total):
        check_time(deadline, "SQLite backup")
    with closing(sqlite3.connect(source.as_uri()+"?mode=ro", uri=True, timeout=min(3, deadline-time.monotonic()))) as reader, closing(sqlite3.connect(target)) as writer:
        version = reader.execute("PRAGMA data_version").fetchone()
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM sqlite_master").fetchone()
        reader.backup(writer, pages=256, progress=progress, sleep=.1)
        reader.rollback()
        require(reader.execute("PRAGMA data_version").fetchone() == version, "SQLite source changed during capture")
        writer.execute("PRAGMA journal_mode=DELETE")
    require(not any(Path(str(target)+suffix).exists() for suffix in ("-wal", "-shm", "-journal")), "Unexpected snapshot journal sidecar")


def validate_database(path, deadline, identity, manifest_hash=None, *, role=None):
    stage = "open"
    try:
        with closing(sqlite3.connect(path.as_uri()+"?mode=ro", uri=True, timeout=min(3, max(.001, deadline-time.monotonic())))) as connection:
            connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            stage = "quick_check"
            check_time(deadline, stage)
            require(connection.execute("PRAGMA quick_check").fetchall() == [("ok",)], "SQLite integrity check failed")
            stage = "schema_read"
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if role == "state/kanban.db":
                stage = "project_tenant"
                require("tasks" in tables, "Project board schema is absent")
                require(connection.execute("SELECT count(*) FROM tasks WHERE tenant IS NOT ?", (identity["board_id"],)).fetchone()[0] == 0,
                        "Project database contains foreign board data")
            if role == "state/knowledge.db":
                stage = "knowledge_binding"
                metadata = dict(connection.execute("SELECT key,value FROM metadata"))
                require(metadata.get("project_id") == identity["project_id"] and metadata.get("manifest_sha256") == manifest_hash,
                        "Knowledge index binding differs")
            return {"quick_check": "ok", "tables": sorted(tables), "scope_checked": role in ("state/kanban.db", "state/knowledge.db")}
    except (sqlite3.Error, BackupError) as error:
        raise BackupError("SQLite validation failed at " + stage + ": " + str(error)) from error


def validate_payload(payload, manifest, deadline):
    roots = {label: payload / label for label in ("project", "state")}
    observed = inventory(roots, deadline, manifest["max_bytes"], manifest["max_files"])
    require(observed["files"] == manifest["files"] and observed["directories"] == manifest["directories"], "Snapshot membership/content differs")
    require(observed["databases"] == manifest["databases"] and not observed["journals"], "Snapshot database membership differs")
    identity_file = roots["project"] / ".icm/project.json"
    require(digest(identity_file, deadline) == manifest["identity_sha256"], "Snapshot identity bytes differ")
    require(json.loads(identity_file.read_text(encoding="utf-8")) == manifest["original_identity"], "Snapshot identity metadata differs")
    knowledge = roots["project"] / ".icm/knowledge-manifest.json"
    knowledge_hash = digest(knowledge, deadline)
    checks = {name: validate_database(path_for(roots, name), deadline, manifest["original_identity"], knowledge_hash, role=name)
              for name in manifest["databases"]}
    git_check(roots["project"], deadline)
    return checks


def failed(destination, stage, error):
    if destination.is_dir() and not (destination / "failure.json").exists():
        json_new(destination / "failure.json", {"status": "failed_partial", "stage": stage, "error_type": type(error).__name__, "reason": str(error)[:2000], "activated": False})


def capture(home, project, destination, *, copy_seconds=180, validation_seconds=180, max_bytes=DEFAULT_BYTES, max_files=DEFAULT_FILES):
    deadline = budget(copy_seconds)
    budget(validation_seconds)
    home, config = runtime_update.integrated(canonical(home))
    guard = home_entry._load_guard(home, config["lifecycle_guard_sha256"])
    with guard.lease(home, expected_sha256=config["lifecycle_guard_sha256"], mode="exclusive") as held:
        runtime_update.stopped(home)
        root, state, identity, identity_hash = selection(home, project, deadline, held.pass_fds)
        git = git_check(root, deadline, held.pass_fds)
        roots = {"project": root, "state": state}
        before = inventory(roots, deadline, max_bytes, max_files)
        destination = new_destination(destination, list(roots.values()))
        total = sum(row["size"] for row in before["files"].values()) + sum(row["size"] for row in before["journals"].values())
        capacity = shutil.disk_usage(destination.parent)
        require(capacity.free >= total * 2 + 8 * 1024 * 1024, "Selected destination volume lacks snapshot headroom")
        destination.mkdir(mode=0o700)
        stage = "copy"
        try:
            payload = destination / "payload"
            out_roots = {label: payload / label for label in roots}
            for directory in before["directories"]:
                (payload / directory).mkdir(parents=True, exist_ok=True, mode=0o700)
            for name, record in sorted(before["files"].items()):
                check_time(deadline, stage)
                source, target = path_for(roots, name), path_for(out_roots, name)
                if name in before["databases"]:
                    sqlite_copy(source, target, deadline)
                else:
                    with source.open("rb") as reader, target.open("xb") as writer:
                        for block in iter(lambda: reader.read(1024 * 1024), b""):
                            check_time(deadline, stage)
                            writer.write(block)
                os.chmod(target, record["mode"] & 0o777)
            require(inventory(roots, deadline, max_bytes, max_files) == before, "Source drift during capture")
            current, current_hash = session_resume._json(root / ".icm/project.json")
            require(current_hash == identity_hash and current == identity, "Project identity drift during capture")
            stage = "validation"
            validation_deadline = budget(validation_seconds)
            saved = inventory(out_roots, validation_deadline, max_bytes, max_files)
            require(saved["directories"] == before["directories"] and saved["databases"] == before["databases"],
                    "Copied tree/database membership differs")
            require(set(saved["files"]) == set(before["files"]), "Copied file membership differs")
            require(all(saved["files"][name] == record for name, record in before["files"].items() if name not in before["databases"]),
                    "Copied regular file differs from its source")
            manifest = {"schema": SCHEMA, "status": "verified_snapshot", "activated": False,
                        "home": str(home), "original_identity": identity, "identity_sha256": identity_hash,
                        "files": saved["files"], "directories": saved["directories"], "databases": saved["databases"],
                        "max_bytes": max_bytes, "max_files": max_files, "git": git,
                        "excluded": ["SQLite journal/SHM sidecars (committed data copied by native backup)", "agent sessions/auth/packages/global memory"],
                        "destination_volume": {"device": destination.stat().st_dev, "free_bytes_before": capacity.free},
                        "budgets": {"copy_seconds": copy_seconds, "validation_seconds": validation_seconds}}
            manifest["database_checks"] = validate_payload(payload, manifest, validation_deadline)
            json_new(destination / "manifest.json", manifest)
            return {"status": "verified_snapshot", "destination": str(destination), "manifest_sha256": hashlib.sha256((destination / "manifest.json").read_bytes()).hexdigest(), "activated": False}
        except BaseException as error:
            failed(destination, stage, error)
            raise


def restore(snapshot, destination, expected_manifest, *, copy_seconds=180, validation_seconds=180):
    deadline = budget(copy_seconds)
    budget(validation_seconds)
    snapshot = canonical(snapshot)
    manifest_file = snapshot / "manifest.json"
    require(isinstance(expected_manifest, str) and len(expected_manifest) == 64 and digest(manifest_file, deadline) == expected_manifest,
            "Supply the exact snapshot manifest SHA256")
    require(manifest_file.stat().st_size <= LIMIT, "Snapshot manifest is too large")
    manifest = maintenance.read_json(manifest_file)
    require(manifest.get("schema") == SCHEMA and manifest.get("status") == "verified_snapshot" and manifest.get("activated") is False,
            "Use an accepted project snapshot manifest")
    require(not (snapshot / "failure.json").exists(), "Snapshot retains a failure record")
    validate_payload(snapshot / "payload", manifest, budget(validation_seconds))
    originals = [Path(manifest["original_identity"][key]) for key in ("canonical_root", "state_root")]
    destination = new_destination(destination, [snapshot, *originals])
    total = sum(row["size"] for row in manifest["files"].values())
    require(shutil.disk_usage(destination.parent).free >= total * 2 + 8 * 1024 * 1024, "Export volume lacks headroom")
    destination.mkdir(mode=0o700)
    stage = "export_copy"
    try:
        deadline = budget(copy_seconds)
        for directory in manifest["directories"]:
            (destination / "payload" / directory).mkdir(parents=True, exist_ok=True, mode=0o700)
        roots = {label: snapshot / "payload" / label for label in ("project", "state")}
        out_roots = {label: destination / "payload" / label for label in roots}
        for name, record in manifest["files"].items():
            check_time(deadline, stage)
            source, target = path_for(roots, name), path_for(out_roots, name)
            with source.open("rb") as reader, target.open("xb") as writer:
                for block in iter(lambda: reader.read(1024 * 1024), b""):
                    check_time(deadline, stage)
                    writer.write(block)
            os.chmod(target, record["mode"] & 0o777)
        stage = "export_validation"
        validation_deadline = budget(validation_seconds)
        checks = validate_payload(destination / "payload", manifest, validation_deadline)
        require(digest(manifest_file, validation_deadline) == expected_manifest, "Snapshot manifest changed during export")
        json_new(destination / "manifest.json", manifest)
        receipt = {"status": "verified_export", "activated": False, "original_paths_retained": True,
                   "source_manifest_sha256": expected_manifest, "database_checks": checks,
                   "scope": "Verified file/database reconstruction only; use a separately supported adoption route before execution"}
        json_new(destination / "export.json", receipt)
        return dict(receipt, destination=str(destination))
    except BaseException as error:
        failed(destination, stage, error)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="action", required=True)
    for name in ("capture", "restore"):
        command = commands.add_parser(name)
        command.add_argument("--destination", type=Path, required=True)
        command.add_argument("--copy-seconds", type=float, default=180)
        command.add_argument("--validation-seconds", type=float, default=180)
        if name == "capture":
            command.add_argument("--home", type=Path, required=True)
            command.add_argument("--project", type=Path, required=True)
            command.add_argument("--max-bytes", type=int, default=DEFAULT_BYTES)
            command.add_argument("--max-files", type=int, default=DEFAULT_FILES)
        else:
            command.add_argument("--snapshot", type=Path, required=True)
            command.add_argument("--manifest-sha256", required=True)
    values = parser.parse_args(argv)
    try:
        common = dict(copy_seconds=values.copy_seconds, validation_seconds=values.validation_seconds)
        if values.action == "capture":
            result = capture(values.home, values.project, values.destination, max_bytes=values.max_bytes, max_files=values.max_files, **common)
        else:
            result = restore(values.snapshot, values.destination, values.manifest_sha256, **common)
    except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError, KeyError) as error:
        print(json.dumps({"status": "refused", "reason": str(error), "activated": False}), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
