"""Checkpoint exact reviewed source, retaining ordinary Git and ownership rules.

Adapted from reviewed source-checkpoint132b, SHA256
141442c0a37a910f95fbfce3addc2d764a67cf497d7b8985abb18d241d95753f.
The original inventory/admission/stage/commit/readback algorithm is retained.
Rig paths, source allowlist maintenance, credentials and private API are omitted.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit


SCHEMA = "source-checkpoint/v1"
BASE = Path(".icm/workspace/artifacts/source-control")


class CheckpointError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise CheckpointError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def hash_value(value):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def git(root, *arguments, allowed=(0,)):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_TRACE="0", GIT_TRACE_CURL="0",
               GIT_CURL_VERBOSE="0", GIT_ALLOW_PROTOCOL="file:http:https:ssh")
    # The existing workflow host forwards PATH/LANG only. Resolve the operating
    # system user's real home for ordinary Git identity/helpers; no agent HOME.
    env.setdefault("HOME", str(Path.home()))
    result = subprocess.run(["git", "--literal-pathspecs", "-C", str(root), *arguments],
                            env=env, capture_output=True, timeout=45)
    require(result.returncode in allowed,
            "Git " + arguments[0] + " failed: " + result.stderr.decode(errors="replace")[:700])
    return result.stdout


def head(root):
    value = git(root, "rev-parse", "--verify", "--quiet", "HEAD", allowed=(0, 1)).decode().strip()
    return value or None


def branch(root):
    return git(root, "symbolic-ref", "--short", "HEAD").decode().strip()


def base_for(project):
    base = project / BASE
    require(base.resolve().is_relative_to(project), "Source-control artifacts escape the project")
    return base


def inventory_location(value, base):
    try:
        path = Path(value).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise CheckpointError("Inventory must be an existing JSON file under " + str(base)) from exc
    require(path.is_file() and path.is_relative_to(base.resolve()),
            "Inventory must resolve under " + str(base) + "; no operation was created")
    return path


def project_repository(project):
    require(project.is_absolute(), "Use an explicit absolute project root")
    project = project.resolve(strict=True)
    require(project.is_dir(), "Project root must be an existing directory")
    root = Path(git(project, "rev-parse", "--show-toplevel").decode().strip()).resolve(strict=True)
    require(project.is_relative_to(root), "Project is outside its actual Git root")
    return project, root


def reviewed_files(project, root, inventories):
    candidates = {}
    for item in inventories:
        require(isinstance(item, dict) and set(item) == {"path", "sha256"} and hash_value(item["sha256"]),
                "Invalid reviewed inventory binding")
        path = inventory_location(item["path"], base_for(project))
        require(str(path) == item["path"], "Inventory binding must use its canonical absolute path")
        data = path.read_bytes()
        require(len(data) <= 2 * 1024 * 1024 and sha(data) == item["sha256"], "Reviewed inventory hash changed")
        inventory = json.loads(data)
        require(isinstance(inventory, dict) and isinstance(inventory.get("safe_files"), list), "Invalid reviewed inventory")
        for source in inventory["safe_files"]:
            require(isinstance(source, dict) and set(source) == {"path", "sha256"} and hash_value(source["sha256"]),
                    "Invalid reviewed file binding")
            file = Path(source["path"])
            require(file.is_absolute() and file.resolve(strict=True) == file and file.is_file() and not file.is_symlink(),
                    "Reviewed source must be a canonical regular file without symlink routing")
            require(file.is_relative_to(project) and not file.is_relative_to(base_for(project)),
                    "Reviewed candidate escapes source scope or names runtime artifacts")
            relative = file.relative_to(root).as_posix()
            require(not any(ord(char) < 32 or ord(char) == 127 for char in relative), "Invalid source path separator")
            require(not any(part in {".git", ".ssh", "node_modules", "venv", ".venv", "sessions"}
                            for part in file.relative_to(project).parts), "Runtime or credential directory is not reviewed source")
            current = file.read_bytes()
            require(len(current) <= 1024 * 1024 and b"\0" not in current, "Reviewed source must be bounded text")
            require(sha(current) == source["sha256"], "Reviewed candidate changed; whole checkpoint refused: " + relative)
            owner = Path(git(file.parent, "rev-parse", "--show-toplevel").decode().strip()).resolve(strict=True)
            require(owner == root, "Nested/vendor repository needs its own checkpoint: " + relative)
            require(relative not in candidates or candidates[relative] == current, "Conflicting reviewed source bindings")
            candidates[relative] = current
    require(candidates and sum(map(len, candidates.values())) < 10 * 1024 * 1024,
            "Checkpoint requires reviewed source below 10 MiB")
    return candidates


def safe_push_url(value):
    require(isinstance(value, str) and value and not any(ord(c) < 32 or ord(c) == 127 for c in value),
            "Invalid approved push URL")
    if Path(value).is_absolute():
        return
    require(not any(c.isspace() for c in value), "Push URL must not contain whitespace")
    parsed = urlsplit(value)
    if parsed.scheme in {"https", "http", "ssh", "file"}:
        require(not parsed.query and not parsed.fragment and parsed.password is None, "Credential/query/fragment in push URL refused")
        if parsed.scheme in {"http", "https"}:
            require(parsed.hostname and parsed.username is None, "Credential-bearing HTTP push URL refused")
        elif parsed.scheme == "ssh":
            require(parsed.hostname and (parsed.username is None or re.fullmatch(r"[\w.-]+", parsed.username)),
                    "Invalid SSH push URL")
        else:
            require(parsed.netloc in {"", "localhost"} and parsed.username is None and Path(parsed.path).is_absolute(),
                    "File push URL must name a local absolute path")
        return
    require(re.fullmatch(r"(?:[\w.-]+@)?[\w.-]+:[\w./~+%-]+", value) is not None and "::" not in value,
            "Unsupported Git push transport or credential-bearing URL")


def check_push(root, push):
    require(isinstance(push, dict) and set(push) == {"remote", "url", "branch"}, "Invalid push binding")
    require(isinstance(push["remote"], str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", push["remote"]),
            "Use one explicit remote name")
    safe_push_url(push["url"])
    require(push["branch"] == branch(root), "Current branch differs from the approved push branch")
    git(root, "check-ref-format", "--branch", push["branch"])
    require(git(root, "remote", "get-url", "--push", "--all", push["remote"]).decode().splitlines() == [push["url"]],
            "Remote push destination is not the single approved URL")
    require(git(root, "ls-remote", "--get-url", "--", push["url"]).decode().splitlines() == [push["url"]],
            "Approved readback URL is redirected by Git configuration")


def remote_commit(root, push):
    check_push(root, push)
    rows = git(root, "ls-remote", "--", push["url"], "refs/heads/" + push["branch"]).decode().splitlines()
    require(len(rows) == 1 and len(rows[0].split()) == 2, "Approved remote branch is missing or ambiguous")
    commit, ref = rows[0].split()
    require(ref == "refs/heads/" + push["branch"], "Remote readback branch differs")
    return commit


def save_receipt(path, receipt):
    fd, temporary = tempfile.mkstemp(prefix="admission-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(receipt, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def changed_paths(root, commit):
    return git(root, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "-z", commit).decode().split("\0")[:-1]


def commit_checkpoint(project, inventories, operation, message, task_ref, push=None):
    require(project.is_absolute(), "Use an explicit absolute project root")
    project = project.resolve(strict=True)
    base = base_for(project)
    #132b: inventory location validation precedes every Git lookup and mutation.
    bindings = [{"path": str(inventory_location(path, base)), "sha256": expected} for path, expected in inventories]
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,127}", operation), "Use one unique operation name")
    for value, label in ((message, "Message"), (task_ref, "Task reference")):
        require(isinstance(value, str) and value == value.strip() and value
                and all(ord(c) >= 32 and ord(c) != 127 for c in value), label + " must be one clean nonempty line")
    project, root = project_repository(project)
    before = head(root)
    current_branch = branch(root)
    require(git(root, "diff", "--cached", "--name-only", "-z") == b"", "Existing staged work needs coordination")
    if push is not None:
        check_push(root, push)
    candidates = reviewed_files(project, root, bindings)
    run = base / operation
    require(not run.exists(), "Operation already exists; inspect retained state, do not replay")
    run.mkdir(exist_ok=False)
    out = run / "admission.json"
    receipt = {"schema": SCHEMA, "operation": operation,
               "at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "state": "prepared",
               "project_root": str(project), "git_root": str(root), "task_ref": task_ref,
               "message": message, "branch": current_branch, "before_head": before,
               "inventories": bindings, "files": {name: sha(data) for name, data in sorted(candidates.items())},
               "source_bytes": sum(map(len, candidates.values())), "push": push,
               "source_files_rewritten": False, "automatic_commit_gate_installed": False}
    save_receipt(out, receipt)
    try:
        require(head(root) == before and branch(root) == current_branch, "HEAD or branch changed before staging")
        paths = sorted(candidates)
        git(root, "add", "--", *paths)
        for name, data in candidates.items():
            require(sha(git(root, "show", ":" + name)) == sha(data), "Staged source bytes differ: " + name)
        staged = git(root, "diff", "--cached", "--name-only", "-z").decode().split("\0")[:-1]
        require(staged and set(staged).issubset(candidates), "Staged paths differ or there is no source change")
        require(all((root / name).read_bytes() == data for name, data in candidates.items()), "Source drift after staging")
        require(head(root) == before and branch(root) == current_branch, "HEAD or branch changed during staging")
        git(root, "commit", "--only", "-m", message, "--", *paths)
        receipt.update(commit=head(root),
                       state="local-source-admission-remote-pending" if push else "local-source-committed-verification-pending")
        save_receipt(out, receipt)
        receipt["changed_paths"] = changed_paths(root, receipt["commit"])
        require(set(receipt["changed_paths"]) == set(staged), "Committed paths differ from reviewed staged paths")
        validate_commit(project, root, receipt, candidates)
        if push is not None:
            check_push(root, push)
            git(root, "push", "--no-follow-tags", "--", push["remote"], "HEAD:refs/heads/" + push["branch"])
            delivered = remote_commit(root, push)
            require(delivered == receipt["commit"], "Approved remote does not contain the exact checkpoint commit")
            validate_commit(project, root, receipt, candidates)
            receipt.update(state="reviewed-source-committed-and-remote-verified", remote_commit=delivered)
        else:
            receipt["state"] = "reviewed-source-committed-local"
        save_receipt(out, receipt)
        return receipt
    except BaseException as exc:
        receipt["error"] = str(exc)[:1000]
        save_receipt(out, receipt)
        raise


def validate_commit(project, root, receipt, candidates):
    commit = receipt.get("commit")
    require(isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit), "Invalid checkpoint commit")
    require(head(root) == commit and branch(root) == receipt["branch"], "Checkpoint HEAD or branch is stale")
    require(receipt.get("files") == {name: sha(data) for name, data in sorted(candidates.items())}, "Receipt source binding differs")
    parents = git(root, "rev-list", "--parents", "-n", "1", commit).decode().strip().split()
    expected = [commit, receipt["before_head"]] if receipt.get("before_head") else [commit]
    require(parents == expected, "Checkpoint parent differs")
    changed = changed_paths(root, commit)
    require(changed and set(changed).issubset(candidates) and sorted(changed) == sorted(receipt["changed_paths"]),
            "Checkpoint changed paths differ")
    require(git(root, "log", "-1", "--format=%s", commit).decode().strip() == receipt["message"], "Checkpoint message differs")
    for name, data in candidates.items():
        require((root / name).resolve(strict=True).is_relative_to(project) and (root / name).read_bytes() == data,
                "Source changed after checkpoint: " + name)
        require(sha(git(root, "show", commit + ":" + name)) == sha(data), "Committed source bytes differ: " + name)
        require(sha(git(root, "show", ":" + name)) == sha(data), "Current staged source bytes differ: " + name)


def verify_checkpoint(relative):
    project = Path.cwd().resolve(strict=True)
    supplied = Path(relative)
    require(not supplied.is_absolute() and supplied.parts and ".." not in supplied.parts, "Verifier requires a project-relative receipt")
    path = project / supplied
    require(path.is_file() and not path.is_symlink(), "Source checkpoint receipt is missing")
    base = base_for(project).resolve(strict=True)
    require(path.resolve(strict=True).is_relative_to(base) and path.name == "admission.json", "Receipt escapes source-control artifacts")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(receipt, dict) and receipt.get("schema") == SCHEMA
            and receipt.get("project_root") == str(project), "Receipt project or schema differs")
    require(isinstance(receipt.get("operation"), str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,127}", receipt["operation"]), "Invalid receipt operation")
    require(path.resolve().parent == base / receipt["operation"], "Receipt operation path differs")
    project, root = project_repository(project)
    require(receipt.get("git_root") == str(root), "Receipt Git root differs")
    inventories = receipt.get("inventories")
    require(isinstance(inventories, list) and inventories, "Receipt inventory binding is missing")
    candidates = reviewed_files(project, root, inventories)
    validate_commit(project, root, receipt, candidates)
    if receipt.get("push") is not None:
        require(receipt.get("state") == "reviewed-source-committed-and-remote-verified", "Remote delivery is pending")
        require(remote_commit(root, receipt["push"]) == receipt["commit"] == receipt.get("remote_commit"), "Remote checkpoint is stale")
    else:
        require(receipt.get("state") == "reviewed-source-committed-local", "Local checkpoint verification is pending")
    return {"verified": True, "commit": receipt["commit"], "reviewed_files": len(candidates),
            "remote_verified": receipt.get("push") is not None, "authority": "source snapshot only"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--verify", metavar="PROJECT_RELATIVE_RECEIPT")
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--inventory", action="append", nargs=2, metavar=("PATH", "SHA256"))
    parser.add_argument("--operation")
    parser.add_argument("--message")
    parser.add_argument("--task-ref")
    parser.add_argument("--push-remote")
    parser.add_argument("--expected-push-url")
    parser.add_argument("--expected-branch")
    args = parser.parse_args(argv)
    try:
        if args.verify is not None:
            require(all(value is None for name, value in vars(args).items() if name != "verify"), "Verifier does not accept mutation options")
            result = verify_checkpoint(args.verify)
        else:
            require(all(value is not None for value in (args.project_root, args.inventory, args.operation, args.message, args.task_ref)),
                    "Commit requires --project-root, --inventory, --operation, --message and --task-ref")
            group = (args.push_remote, args.expected_push_url, args.expected_branch)
            require(not any(value is not None for value in group) or all(value is not None for value in group), "Specify all three push options together")
            push = dict(zip(("remote", "url", "branch"), group)) if group[0] is not None else None
            receipt = commit_checkpoint(args.project_root, args.inventory, args.operation, args.message, args.task_ref, push)
            result = {key: receipt[key] for key in ("state", "commit", "source_bytes")}
            result["reviewed_files"] = len(receipt["files"])
        print(json.dumps(result))
        return 0
    except (CheckpointError, OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1 if args.verify is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
