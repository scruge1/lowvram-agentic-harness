"""Read-only catalogue of existing native Pi session files.

No separate history database, message parser, writer lease, or execution grant.
The existing launcher binds home and project; listing refuses cross-project
files, alias paths, changed source stamps and unsafe pagination.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import sys

from .managed_launch import session_directory

MAX_SESSIONS = 2000
MAX_PAGE = 25
HEADER_LIMIT = 131072
SESSION_NAME = re.compile(r"[a-zA-Z0-9_.-]{1,200}\.jsonl\Z")
SESSION_ID = re.compile(r"[a-zA-Z0-9_-]{1,256}\Z")
PIN = re.compile(r"[0-9a-f]{64}\Z")


class SessionCatalogueError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SessionCatalogueError(message)


def _bucket(home: Path, project: Path) -> Path:
    _require(sys.platform == "linux" and callable(getattr(os, "getuid", None)),
             "Native session catalogue requires the Linux host")
    home = Path(home).resolve(strict=True)
    project = Path(project).resolve(strict=True)
    _require(home.is_dir() and project.is_dir(), "Native home or project unavailable")
    marker = project / ".icm" / "project.json"
    _require(marker.is_file() and not marker.is_symlink(), "Admitted ICM project identity missing")
    raw = marker.read_bytes()
    _require(len(raw) <= HEADER_LIMIT, "ICM identity exceeds its bound")
    try:
        identity = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise SessionCatalogueError("Current ICM identity invalid") from exc
    pid = identity.get("project_id") if isinstance(identity, dict) else None
    _require(isinstance(pid, str) and pid and identity.get("canonical_root") == str(project)
             and identity.get("board_id") == "project:" + pid,
             "Current ICM project/board identity differs")
    _require(identity.get("state_root") == str(home / "state" / "projects" / pid),
             "Project state is owned by another home")
    bucket = session_directory(home, project)
    _require(bucket.is_relative_to(home), "Native session bucket outside owner home")
    current = home
    for component in bucket.relative_to(home).parts:
        current = current / component
        _require(not current.is_symlink(), "Native session bucket contains a symlink")
        if not current.exists():
            return bucket
        _require(current.is_dir(), "Native session bucket is not a directory")
    _require(bucket.resolve(strict=True) == bucket, "Native session bucket path changed")
    return bucket


def _stamp(info: os.stat_result) -> tuple[int, ...]:
    return (int(info.st_dev), int(info.st_ino), int(info.st_size),
            int(info.st_mtime_ns), int(info.st_ctime_ns), int(info.st_nlink))


def _header(path: Path, project: Path) -> tuple[dict, os.stat_result]:
    _require(SESSION_NAME.fullmatch(path.name) is not None,
             "Unexpected native session filename")
    info = path.stat(follow_symlinks=False)
    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
             and info.st_uid == os.getuid() and info.st_size > 0,
             "Native session must be an owned single-link regular file")
    _require(not path.is_symlink(), "Native session filename is a symlink")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) |
                 getattr(os, "O_CLOEXEC", 0))
    try:
        actual = os.fstat(fd)
        _require(_stamp(actual) == _stamp(info), "Native session changed during open")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            first = stream.readline(HEADER_LIMIT + 1)
        _require(first.endswith(b"\n") and len(first) <= HEADER_LIMIT,
                 "Native session header incomplete or oversized")
        try:
            row = json.loads(first.decode("utf-8-sig"))
        except (ValueError, UnicodeError) as exc:
            raise SessionCatalogueError("Native session header invalid") from exc
        _require(isinstance(row, dict) and row.get("type") == "session"
                 and row.get("cwd") == str(project),
                 "Native session header belongs to another project")
        sid = row.get("id")
        _require(isinstance(sid, str) and SESSION_ID.fullmatch(sid) is not None,
                 "Native session ID invalid")
        _require(_stamp(os.fstat(fd)) == _stamp(actual),
                 "Native session changed during read")
        return row, actual
    finally:
        os.close(fd)


def _listing(home: Path, project: Path) -> tuple[list[dict], str]:
    bucket = _bucket(home, project)
    entries, observed_stamps = [], []
    if bucket.is_dir():
        paths = list(bucket.glob("*.jsonl"))
        _require(len(paths) <= MAX_SESSIONS, "Session count exceeds safe bound")
        seen, fingerprints = set(), []
        for path in paths:
            header, info = _header(path, project)
            sid = header["id"]
            _require(sid not in seen, "Duplicate native session identity")
            seen.add(sid)
            fingerprints.append((path, _stamp(info)))
            observed_stamps.append((path.name, sid, _stamp(info)))
            updated = datetime.fromtimestamp(info.st_mtime_ns / 1e9,
                                              tz=timezone.utc).isoformat()
            created = header.get("timestamp")
            if not isinstance(created, str) or len(created) > 64:
                created = None
            elif created is not None:
                try:
                    datetime.fromisoformat(created.replace("Z", "+00:00"))
                except ValueError:
                    created = None
            entries.append({"session_id": sid, "created_at": created,
                            "updated_at": updated, "bytes": int(info.st_size),
                            "source": "native_pi_session_header_only"})
        for path, before in fingerprints:
            _require(_stamp(path.stat(follow_symlinks=False)) == before,
                     "Native session source changed during listing")
        _require(set(bucket.glob("*.jsonl")) == set(paths),
                 "Native session file set changed during listing")
    entries.sort(key=lambda x:(x["updated_at"], x["session_id"]), reverse=True)
    fingerprint = sha256(json.dumps(sorted(observed_stamps),
                                    separators=(",",":")).encode()).hexdigest()
    return entries, fingerprint


def list_project_sessions(home: Path, project: Path, *, offset=0, limit=20,
                          expected_snapshot_sha256=None) -> dict:
    _require(type(offset) is int and 0 <= offset <= MAX_SESSIONS,
             "Invalid history offset")
    _require(type(limit) is int and 1 <= limit <= MAX_PAGE,
             "Invalid history page length")
    _require(expected_snapshot_sha256 is None or isinstance(expected_snapshot_sha256,str)
             and PIN.fullmatch(expected_snapshot_sha256) is not None,
             "Invalid history snapshot fingerprint")
    _require(offset == 0 or expected_snapshot_sha256 is not None,
             "Next page requires original listing fingerprint")
    entries, fingerprint = _listing(Path(home), Path(project))
    _require(expected_snapshot_sha256 is None or expected_snapshot_sha256 == fingerprint,
             "Native history changed; refresh the listing")
    _require(offset <= len(entries), "History offset exceeds source")
    page = entries[offset:offset + limit]
    next_offset = offset + len(page) if offset + len(page) < len(entries) else None
    return {"schema":"agent-home-native-session-catalog/v1",
            "authority":"retrieval_only","project_bound":True,
            "snapshot_sha256":fingerprint,"total":len(entries),
            "offset":offset,"next_offset":next_offset,"sessions":page,
            "limits":"Native Pi header metadata only. No message contents, session selection, writer lease or execution permission."}

def main(argv=None):
    """Print metadata only; leave the native history and active agent untouched."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--expected-snapshot-sha256", default=None)
    opts = parser.parse_args(argv)
    try:
        result = list_project_sessions(
            opts.home, opts.project, offset=opts.offset, limit=opts.limit,
            expected_snapshot_sha256=opts.expected_snapshot_sha256,
        )
    except (OSError, ValueError, TypeError):
        print(json.dumps({"schema": "agent-home-native-session-catalog/v1",
                          "status": "unavailable", "authority": "retrieval_only",
                          "error": "Session catalogue unavailable or changed; verify selected home and original project identity."}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
