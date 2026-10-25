"""Linux lifetime leases for a newly integrated, managed agent home.

Install these exact bytes as HOME/home-lifecycle.py, outside HOME/runtime, and
record their SHA256 in home.json as lifecycle_guard_sha256. Load that stable
file before importing runtime code. This is not an activation implementation.

Use ``with lease(home, expected_sha256=pin) as held`` for a shared consumer.
Use mode="exclusive" for an updater; recover=True permits an existing pending
journal but never edits it. All acquisitions are nonblocking. A missing or
invalid home identity is refused even during recovery.

The descriptor is CLOEXEC by default. Keep the parent context through child
settlement; use held.pass_fds with subprocess when the child must retain the
lease if its parent dies. Close, rather than LOCK_UN, releases this process's
copy so an explicitly inherited child still holds its lease. Detached hubs
need their own shared entry lease before importing runtime. Unmanaged direct
Pi entrypoints and old homes without this integration are not covered.

The CLI acquires then execs an argument array. It intentionally makes its one
descriptor inheritable for that exec. AGENT_HOME_LIFECYCLE_FD identifies it for
explicit further passing, not authority to skip normal lease checks. An
inherited descriptor can keep a home busy until its last holder exits; do not
pass it to unrelated/background children. Descendants that do not inherit or
acquire a lease are not covered. This is cooperation, not hostile isolation.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import sys


LOCK = "state/home-lifecycle.lock"
PENDING = "state/updates/pending-activation.json"
FD_ENV = "AGENT_HOME_LIFECYCLE_FD"
MAX_JSON_BYTES = 65536


class LifecycleError(ValueError):
    """The selected managed home cannot admit this lifecycle operation."""


class LeaseBusy(LifecycleError):
    """A cooperating consumer or updater still holds this home's lease."""


def require(value, message):
    if not value:
        raise LifecycleError(message)


def require_linux():
    require(sys.platform == "linux" and hasattr(os, "O_NOFOLLOW"),
            "Agent-home lifecycle leases require Linux; no enforcement on this platform")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def owned(path, *, directory=False):
    info = path.lstat()
    require(not stat.S_ISLNK(info.st_mode), "Lifecycle path is a symlink: " + str(path))
    require(info.st_uid == os.getuid(), "Lifecycle path belongs to another user: " + str(path))
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode),
            "Lifecycle path has the wrong file type: " + str(path))
    if not directory:
        require(info.st_nlink == 1, "Lifecycle file has multiple links: " + str(path))
    return info


def canonical_home(value):
    path = Path(value).expanduser()
    require(path.is_absolute() and ".." not in path.parts, "Select an explicit absolute home path")
    # Require the actual path, including ancestors. Do not silently follow an
    # alias to a different home or put a lifecycle lock in a redirected state dir.
    require(path.resolve(strict=True) == path, "Lifecycle home path contains a symlink or alias")
    owned(path, directory=True)
    return path


def child_path(home, relative, *, directory=False, absent=False):
    path = home / relative
    for parent in reversed(path.parents):
        if parent == home or home in parent.parents:
            owned(parent, directory=True)
    if absent and not path.exists() and not path.is_symlink():
        return path
    owned(path, directory=directory)
    return path


def checked_home(value, expected_sha256):
    require_linux()
    require(isinstance(expected_sha256, str) and len(expected_sha256) == 64
            and all(char in "0123456789abcdef" for char in expected_sha256),
            "Supply the exact lowercase lifecycle guard SHA256")
    home = canonical_home(value)
    guard = child_path(home, "home-lifecycle.py")
    require(Path(__file__).absolute() == guard and sha256(guard) == expected_sha256,
            "Load the exact stable lifecycle guard installed in this home")
    config_path = child_path(home, "home.json")
    require(config_path.stat().st_size <= MAX_JSON_BYTES, "Home identity is too large")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    require(isinstance(config, dict) and config.get("schema") == "agent-home/v1"
            and config.get("home") == str(home), "Lifecycle home identity differs")
    require(config.get("lifecycle_guard_sha256") == expected_sha256,
            "Lifecycle guard is not bound by this home; old homes need explicit integration")
    child_path(home, "state", directory=True)
    return home


def pending(home):
    directory = child_path(home, "state/updates", directory=True, absent=True)
    if not directory.exists():
        return None
    owned(directory, directory=True)
    path = child_path(home, PENDING, absent=True)
    # Presence is sufficient: malformed or partial journal content must not
    # enable a normal consumer. Recovery code owns journal parsing and repair.
    return path if path.exists() else None


class HeldLease:
    def __init__(self, home, descriptor, mode, journal):
        self.home = home
        self.fd = descriptor
        self.mode = mode
        self.pending_journal = journal

    @property
    def pass_fds(self):
        require(self.fd is not None, "Lifecycle lease is closed")
        return (self.fd,)

    def close(self):
        if self.fd is not None:
            descriptor, self.fd = self.fd, None
            # flock belongs to the open file description. An explicit unlock
            # here would also unlock an inherited child's still-live copy.
            os.close(descriptor)


@contextmanager
def lease(home, *, expected_sha256, mode="shared", recover=False):
    """Acquire this integrated home's shared or exclusive nonblocking lease."""
    require(mode in {"shared", "exclusive"}, "Lease mode must be shared or exclusive")
    require(isinstance(recover, bool) and (not recover or mode == "exclusive"),
            "Only an explicit exclusive owner may inspect a pending activation")
    home = checked_home(home, expected_sha256)
    lock = child_path(home, LOCK, absent=True)
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    held = None
    try:
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1,
                "Lifecycle lock is not an owned regular file")
        current = owned(lock)
        require((info.st_dev, info.st_ino) == (current.st_dev, current.st_ino),
                "Lifecycle lock identity changed")
        import fcntl
        operation = fcntl.LOCK_SH if mode == "shared" else fcntl.LOCK_EX
        try:
            fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise LeaseBusy("Agent home is busy; a consumer or updater holds its lifecycle lease") from error
        # Recheck after locking. Another cooperating updater can have changed
        # configuration between the first identity check and this acquisition.
        checked_home(home, expected_sha256)
        current = owned(lock)
        require((info.st_dev, info.st_ino) == (current.st_dev, current.st_ino),
                "Lifecycle lock identity changed after acquisition")
        journal = pending(home)
        require(journal is None or (mode == "exclusive" and recover),
                "Pending activation blocks normal entry; use the explicit exclusive recovery route")
        held = HeldLease(home, descriptor, mode, journal)
        yield held
    finally:
        if held is None:
            os.close(descriptor)
        else:
            held.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--mode", choices=("shared", "exclusive"), default="shared")
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    try:
        require(bool(command), "Provide the explicit command argument array after --")
        with lease(args.home, expected_sha256=args.expected_sha256, mode=args.mode, recover=args.recover) as held:
            os.set_inheritable(held.fd, True)
            env = {**os.environ, FD_ENV: str(held.fd)}
            os.execvpe(command[0], command, env)
    except (OSError, ValueError) as error:
        print(json.dumps({"schema": "agent-home-lifecycle/v1", "status": "refused", "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
