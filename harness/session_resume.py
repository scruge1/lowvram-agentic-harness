"""Scoped native Pi continuation and a cooperative Linux writer lease.

Pi1.4 SessionManager has no active-writer lock. Every managed fresh/continued
launch must hold this bucket lock and pass its descriptor to the actual Node
process. Existing unmanaged Pi CLI owners are checked read-only through /proc.
This does not lock arbitrary SDK writers or make saved history permission.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

from .managed_launch import session_directory


class SessionResumeError(ValueError):
    pass


class SessionScopeError(SessionResumeError):
    pass


class NoPreviousSession(SessionResumeError):
    pass


class SessionBusyError(SessionResumeError):
    def __init__(self, message, owners=()):
        super().__init__(message)
        self.owners = tuple(owners)


@dataclass(frozen=True)
class Owner:
    pid: int
    start_ticks: str


@dataclass
class SessionLease:
    bucket: Path
    fd: int
    selection: Optional[Mapping[str, Any]]

    @property
    def pass_fds(self) -> Tuple[int, ...]:
        if self.fd < 0:
            raise SessionResumeError("Session lease is closed")
        return (self.fd,)

    @property
    def pi_args(self) -> Tuple[str, ...]:
        return ("--session", self.selection["path"]) if self.selection else ()

    def close(self):
        if self.fd >= 0:
            # Never LOCK_UN: the inherited Node descriptor shares this lock.
            # Closing only this descriptor retains ownership if Node survives.
            os.close(self.fd)
            self.fd = -1

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _absolute(value, name):
    if not isinstance(value, (str, os.PathLike)):
        raise SessionScopeError(name + " must be an absolute path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise SessionScopeError(name + " must be absolute")
    return path.resolve(strict=True)


def _json(path):
    raw = path.read_bytes()
    if len(raw) > 131072:
        raise SessionScopeError("Configuration is too large: " + str(path))
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise SessionScopeError("Invalid configuration: " + str(path)) from error
    if not isinstance(value, dict):
        raise SessionScopeError("Configuration must be an object: " + str(path))
    return value, hashlib.sha256(raw).hexdigest()


def _project(home, cwd, supplied):
    if supplied is None:
        # Reuse existing admission, without initialize or a new identity engine.
        from .home import board
        reply = board(home, {"action": "project_admit", "project_root": str(cwd)})
        supplied = reply.get("result", {}).get("identity")
    if not isinstance(supplied, Mapping):
        raise SessionScopeError("Current project admission is required")
    current, digest = _json(cwd / ".icm/project.json")
    keys = ("project_id", "board_id", "canonical_root", "state_root")
    if any(not isinstance(current.get(key), str) or not current[key] for key in keys):
        raise SessionScopeError("Current project identity is incomplete")
    if any(current[key] != supplied.get(key) for key in keys):
        raise SessionScopeError("Current project identity changed after admission")
    if _absolute(current["canonical_root"], "Project root") != cwd:
        raise SessionScopeError("Project identity belongs to another root")
    expected_state = home / "state/projects" / current["project_id"]
    if not Path(current["state_root"]).is_absolute() or Path(current["state_root"]).resolve() != expected_state:
        raise SessionScopeError("Project state belongs to another agent home")
    return {key: current[key] for key in keys}, digest


def _directory(home, cwd):
    bucket = session_directory(home, cwd)
    current = home
    for part in bucket.relative_to(home).parts:
        current = current / part
        if current.is_symlink():
            raise SessionScopeError("Native session directory contains a symlink")
    bucket.mkdir(parents=True, exist_ok=True, mode=0o700)
    if bucket.resolve() != bucket:
        raise SessionScopeError("Native session directory changed")
    return bucket


def _regular_owned(info, description):
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        raise SessionScopeError(description + " must be a single-link regular file owned by this user")


def _lock(bucket):
    import fcntl
    path = bucket / ".managed-session.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(fd)
        _regular_owned(info, "Session lock")
        named = path.stat(follow_symlinks=False)
        if (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino):
            raise SessionScopeError("Session lock path changed")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SessionBusyError("Another managed Pi owns this home/project session bucket") from error
        return fd
    except BaseException:
        os.close(fd)
        raise


def _process_start(directory):
    raw = (directory / "stat").read_text()
    fields = raw[raw.rfind(")") + 2:].split()
    return None if fields[0] in ("Z", "X") else fields[19]


def _small(path, limit):
    with path.open("rb") as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise SessionResumeError("Existing Pi process metadata exceeds its inspection bound")
    return value


def _entry(argv):
    index = 1
    while index < len(argv):
        arg = argv[index]
        if arg in ("-e", "--eval", "-p", "--print") or arg.startswith(("--eval=", "--print=")):
            return None
        if arg in ("-r", "--require", "--import", "--loader", "--experimental-loader"):
            index += 2
            continue
        if arg == "--":
            index += 1
            break
        if not arg.startswith("-"):
            break
        index += 1
    return index if index < len(argv) else None


def _option(arguments, name):
    value = None
    index = 0
    while index < len(arguments):
        arg = arguments[index]
        if arg == "--":
            break
        if arg == name and index + 1 < len(arguments):
            index += 1
            value = arguments[index]
        elif arg.startswith(name + "="):
            value = arg[len(name) + 1:]
        index += 1
    return value


def _path(value, cwd):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else cwd / path).resolve()


def _holds_other_bucket(directory, home, bucket):
    """Recognize an inherited kernel EX lease for a different managed bucket."""
    for count, descriptor in enumerate((directory / "fd").iterdir()):
        if count > 4096:
            raise SessionResumeError("Existing Pi descriptors exceed their inspection bound")
        try:
            target = Path(os.readlink(descriptor))
            if (not target.is_absolute() or target.name != ".managed-session.lock"
                    or target.parent.parent != home / "agent/sessions" or target.parent == bucket):
                continue
            named, opened = target.stat(follow_symlinks=False), descriptor.stat()
            if (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino):
                continue
            _regular_owned(named, "Other managed session lock")
            for line in (directory / "fdinfo" / descriptor.name).read_text().splitlines():
                if line.startswith("lock:") and "FLOCK ADVISORY WRITE" in " ".join(line.split()):
                    return True
        except FileNotFoundError:
            continue
    return False


def unmanaged_owners(home, cwd, bucket, pi_package, *, continue_recent=False, proc_root=Path("/proc")):
    """Inspect recognized same-UID native Node CLI owners; emit no argv/env text."""
    owners = []
    expected_cli = (pi_package / "dist/cli.js").resolve()
    for count, directory in enumerate(proc_root.iterdir()):
        if count > 32768:
            raise SessionResumeError("Cannot complete the existing-owner inspection")
        if not directory.name.isdigit() or int(directory.name) == os.getpid():
            continue
        try:
            if directory.stat().st_uid != os.getuid():
                continue
            start = _process_start(directory)
            comm = (directory / "comm").read_text().strip()
            if start is None or comm not in ("node", "nodejs", "pi", "pi-rpc"):
                continue
            argv = [os.fsdecode(part) for part in _small(directory / "cmdline", 131072).split(b"\0") if part]
            index = _entry(argv)
            # Native setup sets process.title='pi', which overwrites /proc argv.
            # Retain startup argv recognition and verify the executable below.
            native_title = comm in ("pi", "pi-rpc") and argv == [comm]
            candidate = argv[index].replace("\\", "/") if index is not None else ""
            if not native_title and candidate != str(expected_cli) and not candidate.endswith((
                    "/@earendil-works/pi-coding-agent/dist/cli.js", "/@mariozechner/pi-coding-agent/dist/cli.js")):
                continue
            if Path(os.readlink(directory / "exe")).name not in ("node", "nodejs"):
                continue
            process_cwd = Path(os.readlink(directory / "cwd")).resolve()
            entry = _path(argv[index], process_cwd) if index is not None else None
            recognized = native_title or entry == expected_cli or str(entry).replace("\\", "/").endswith((
                "/@earendil-works/pi-coding-agent/dist/cli.js", "/@mariozechner/pi-coding-agent/dist/cli.js"))
            if not recognized:
                continue
            environ = dict(part.split(b"=", 1) for part in _small(directory / "environ", 1048576).split(b"\0") if b"=" in part)
            env = {key: os.fsdecode(environ[key.encode()]) for key in (
                "HOME", "PI_CODING_AGENT_DIR", "PI_CODING_AGENT_SESSION_DIR") if key.encode() in environ}
            args = argv[index + 1:] if index is not None else []
            selected = _option(args, "--session")
            selected_dir = _option(args, "--session-dir") or env.get("PI_CODING_AGENT_SESSION_DIR")
            agent = env.get("PI_CODING_AGENT_DIR") or str(Path(env.get("HOME", "/")) / ".pi/agent")
            matches = (_path(agent, process_cwd) == home / "agent" and process_cwd == cwd)
            matches = matches or bool(selected_dir and _path(selected_dir, process_cwd) == bucket)
            matches = matches or bool(selected and _path(selected, process_cwd).parent == bucket)
            # Native process.title erases arbitrary CLI --session flags. On
            # continue, another Pi in this explicit home is unknown unless its
            # inherited kernel lease positively binds a different bucket.
            if (continue_recent and not matches and env.get("PI_CODING_AGENT_DIR")
                    and _path(env["PI_CODING_AGENT_DIR"], process_cwd) == home / "agent"):
                matches = not _holds_other_bucket(directory, home, bucket)
            if matches and _process_start(directory) == start:
                owners.append(Owner(int(directory.name), start))
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError as error:
            raise SessionResumeError("Cannot inspect an existing same-user Node owner") from error
    return owners


_NATIVE_SELECT = r"""
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const [pkg,cwd,bucket] = process.argv.slice(1);
const api = await import(pathToFileURL(path.join(pkg,'dist/core/session-manager.js')));
const nativeBucket = api.getDefaultSessionDir(cwd,process.env.PI_CODING_AGENT_DIR);
if (fs.realpathSync(nativeBucket) !== bucket) throw Error('Native session bucket differs');
const listed = await api.SessionManager.list(cwd,bucket);
const selected = api.findMostRecentSession(bucket,cwd);
if (!selected) throw Error('No previous native session');
const original = api.loadEntriesFromFile(selected);
const header = original[0];
if (header?.type !== 'session' || header.version !== api.CURRENT_SESSION_VERSION) throw Error('Session migration is not admitted');
const manager = api.SessionManager.continueRecent(cwd,bucket);
if (manager.getSessionFile() !== selected || !listed.some(item=>item.path===selected)) throw Error('Native session selection differs');
const saved = [...manager.getBranch()].reverse().find(entry=>entry.type==='custom' && entry.customType==='pi-kanban-selection/v1')?.data?.project;
if (saved && !['root','projectId','boardId'].every(key=>typeof saved[key]==='string' && saved[key].length<=4096)) throw Error('Invalid saved project identity');
console.log(JSON.stringify({path:selected,id:manager.getSessionId(),header_cwd:manager.getHeader()?.cwd,
 native_cwd:manager.getCwd(),listed_count:listed.length,saved_project:saved??null}));
"""


def _sources(bucket, cwd):
    result = {}
    for path in bucket.glob("*.jsonl"):
        info = path.lstat()
        _regular_owned(info, "Saved session")
        if path.resolve() != path or info.st_size == 0:
            raise SessionScopeError("Saved session is empty or aliases another path")
        with path.open("rb") as stream:
            first = stream.readline(131073)
            if len(first) > 131072:
                raise SessionScopeError("Saved session header exceeds its bound")
            try:
                header = json.loads(first.decode("utf-8-sig"))
            except (ValueError, UnicodeError) as error:
                raise SessionScopeError("Saved session has an invalid header") from error
            if not isinstance(header, dict) or header.get("type") != "session" or _absolute(header.get("cwd", ""), "Saved cwd") != cwd:
                raise SessionScopeError("Saved session header belongs to another project")
            stream.seek(-1, os.SEEK_END)
            if stream.read(1) != b"\n":
                raise SessionScopeError("Saved session has an incomplete final line; preserve it before recovery")
        result[path] = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                        hashlib.sha256(path.read_bytes()).hexdigest())
    return result


def _select(home, cwd, bucket, node, pi_package, identity):
    before = _sources(bucket, cwd)
    if not before:
        raise NoPreviousSession("No previous session in this home/project")
    env = {key: os.environ[key] for key in ("HOME", "USER", "LOGNAME", "PATH", "LANG", "LC_ALL") if key in os.environ}
    env.update(PI_CODING_AGENT_DIR=str(home / "agent"), PI_CODING_AGENT_SESSION_DIR=str(bucket),
               PI_OFFLINE="1", PI_SKIP_VERSION_CHECK="1")
    try:
        result = subprocess.run([str(node), "--input-type=module", "--eval", _NATIVE_SELECT,
                                 str(pi_package), str(cwd), str(bucket)], cwd=cwd, env=env,
                                capture_output=True, text=True, encoding="utf-8", timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SessionResumeError("Native session selection did not complete") from error
    if result.returncode != 0:
        raise SessionScopeError("Native session continuation refused: " + result.stderr[-1000:])
    try:
        selected = json.loads(result.stdout)
        if not isinstance(selected, dict) or not isinstance(selected.get("path"), str):
            raise ValueError("Invalid native selection")
    except (ValueError, UnicodeError) as error:
        raise SessionScopeError("Native session selection returned an invalid result") from error
    path = Path(selected["path"])
    if path not in before or path.parent != bucket or path.resolve() != path:
        raise SessionScopeError("Native session selection escaped its bucket")
    if _absolute(selected["header_cwd"], "Saved cwd") != cwd or _absolute(selected["native_cwd"], "Native cwd") != cwd:
        raise SessionScopeError("Native session belongs to another project")
    saved = selected.get("saved_project")
    if saved and (saved["root"] != str(cwd) or saved["projectId"] != identity["project_id"] or saved["boardId"] != identity["board_id"]):
        raise SessionScopeError("Saved selected project differs; use its original home/project route")
    if _sources(bucket, cwd) != before:
        raise SessionScopeError("Saved session source changed during selection")
    selected["source_sha256"] = before[path][-1]
    return selected


def acquire(home, cwd, *, continue_recent=False, node, pi_package, project_identity=None):
    """Return a lease for ALL launches; only explicit continue selects history.

    The caller retains its separate home SH lease and combines pass_fds when
    invoking Node. Direct user --session/--resume overrides remain unsupported.
    """
    if sys.platform != "linux":
        raise SessionResumeError("Managed session writer ownership requires Linux")
    home, cwd = _absolute(home, "Agent home"), _absolute(cwd, "Project cwd")
    if not home.is_dir() or not cwd.is_dir():
        raise SessionScopeError("Agent home and project must be directories")
    config, _ = _json(home / "home.json")
    if _absolute(config.get("home", ""), "Configured home") != home:
        raise SessionScopeError("Agent home binding differs")
    node, pi_package = _absolute(node, "Node executable"), _absolute(pi_package, "Pi package")
    expected_package = (home / "packages/pi/node_modules/@earendil-works/pi-coding-agent").resolve(strict=True)
    package, _ = _json(pi_package / "package.json")
    if pi_package != expected_package or package.get("name") != "@earendil-works/pi-coding-agent" or package.get("version") != "1.4.0":
        raise SessionScopeError("Use this home's accepted Pi1.4 package")
    identity, identity_hash = _project(home, cwd, project_identity)
    bucket = _directory(home, cwd)
    lease = SessionLease(bucket, _lock(bucket), None)
    try:
        owners = unmanaged_owners(home, cwd, bucket, pi_package, continue_recent=continue_recent)
        if owners:
            raise SessionBusyError("An existing Pi CLI owns this home/project; reconnect to that process", owners)
        if continue_recent:
            lease.selection = _select(home, cwd, bucket, node, pi_package, identity)
        _, after_identity_hash = _project(home, cwd, identity)
        if after_identity_hash != identity_hash:
            raise SessionScopeError("Current project pointer changed during session admission")
        if unmanaged_owners(home, cwd, bucket, pi_package, continue_recent=continue_recent):
            raise SessionBusyError("A Pi CLI appeared during session admission")
        info, named = os.fstat(lease.fd), (bucket / ".managed-session.lock").stat(follow_symlinks=False)
        if (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino):
            raise SessionScopeError("Session lock path changed during admission")
        return lease
    except BaseException:
        lease.close()
        raise
