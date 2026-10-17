"""Bounded regular-file snapshots using the same metadata API on both handles."""
import hashlib
import os
from pathlib import Path
import stat


def _stamp(info):
    return tuple(getattr(info, field) for field in (
        "st_dev", "st_ino", "st_mode", "st_nlink", "st_size",
        "st_mtime_ns", "st_ctime_ns"))


def _canonical(path):
    if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True) != path:
        raise ValueError("An absolute source without aliases is required")


def stable_snapshot(path, max_bytes=524288):
    """Read one authorized file; reject observed replacement or metadata drift.

    The caller supplies its authorized canonical path and byte limit. This does
    not grant access, attest an owner, lock the file, or impose an OS deadline.
    A successful snapshot is evidence at the checked points, not a lease on the
    pathname after return. UTF-8 and document interpretation belong to callers.
    """
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("A positive integer byte limit is required")
    path = Path(path)
    _canonical(path)
    flags = os.O_RDONLY
    for name in ("O_BINARY", "O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC"):
        flags |= getattr(os, name, 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or not 0 < before.st_size <= max_bytes):
            raise ValueError("A nonempty bounded regular file with one link is required")
        chunks, remaining = [], max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        source = b"".join(chunks)
        after = os.fstat(descriptor)
        # Windows runtimes can give pathname stat and fstat different ctime
        # meanings. Keep ctime and compare fstat with fstat instead.
        named_descriptor = os.open(path, flags)
        try:
            named = os.fstat(named_descriptor)
            if (len(source) != before.st_size or _stamp(before) != _stamp(after)
                    or _stamp(after) != _stamp(named)):
                raise ValueError("Source changed during the snapshot")
            _canonical(path)
        finally:
            os.close(named_descriptor)
        return {"source": source, "source_bytes": len(source),
                "source_sha256": hashlib.sha256(source).hexdigest(),
                "source_stamp": _stamp(before)}
    finally:
        os.close(descriptor)


def pinned_snapshot(path, expected_bytes, expected_sha256, *, max_bytes):
    """Read an authorized source against a caller-selected pin and byte budget.

    Reject an impossible declared size before I/O. Never infer or increase the
    budget from the file being read. Matching bytes do not attest the pin's
    owner, source authority, freshness, or permission to execute its contents.
    """
    if (type(expected_bytes) is not int or expected_bytes <= 0
            or type(max_bytes) is not int or max_bytes <= 0):
        raise ValueError("Pin size and byte budget must be positive integers")
    if (type(expected_sha256) is not str or len(expected_sha256) != 64
            or any(char not in "0123456789abcdef" for char in expected_sha256)):
        raise ValueError("The source pin requires a lowercase SHA256 digest")
    if expected_bytes > max_bytes:
        raise ValueError("Declared source size exceeds the selected byte budget")
    result = stable_snapshot(path, max_bytes)
    if (result["source_bytes"] != expected_bytes
            or result["source_sha256"] != expected_sha256):
        raise ValueError("Snapshot differs from the selected source pin")
    return result
