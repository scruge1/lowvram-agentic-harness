"""Explicit downstream Claude-mem package staging; never import its worker.

Disable the pinned upstream process-table orphan sweep. Preserve original bytes
and require their provenance on every entry. This is not a registry migration or
authority to signal processes found in old data.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile


SCHEMA = "agent-home-claude-memory-artifact/v1"
WORKER = "node_modules/claude-mem/plugin/scripts/worker-service.cjs"
PATCH_DIRECTORY = "agent-home-patch"
POLICY_KEYS = {"schema", "patch_id", "package", "upstream_version", "upstream_sha256", "upstream_bytes",
               "start_byte", "end_byte_exclusive", "span_sha256", "replacement", "replacement_sha256",
               "effective_sha256", "effective_bytes", "license_marker"}


class PatchError(ValueError):
    pass


def require(value, message):
    if not value:
        raise PatchError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def manifest():
    file = Path(__file__).with_name("claude-memory-patch.json")
    require(file.is_file() and not file.is_symlink(), "Missing canonical Claude-mem patch manifest")
    value = json.loads(file.read_text(encoding="utf-8"))
    require(isinstance(value, dict) and set(value) == POLICY_KEYS
            and value["schema"] == "agent-home-claude-memory-patch/v1"
            and value["package"] == "claude-mem", "Unknown Claude-mem patch policy")
    require(all(type(value[key]) is int and value[key] >= 0 for key in (
        "upstream_bytes", "effective_bytes", "start_byte", "end_byte_exclusive")), "Invalid Claude-mem patch span")
    require(value["start_byte"] < value["end_byte_exclusive"] <= value["upstream_bytes"], "Invalid Claude-mem patch bounds")
    return value


def _safe(path, *, directory=False):
    info = path.lstat()
    require(not path.is_symlink() and path.resolve() == path.absolute()
            and not getattr(info, "st_file_attributes", 0) & 0x400, "Claude-mem patch path is redirected")
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode), "Invalid Claude-mem patch path type")
    require(directory or info.st_nlink == 1, "Claude-mem patch file must have one link")
    if os.name != "nt":
        require(info.st_uid == os.getuid(), "Claude-mem patch path belongs to another user")
    return info


def paths(home):
    from .home import load
    home, _ = load(Path(home))
    require(not (home / "home.json").is_symlink(), "Home identity is redirected")
    prefix = home / "packages/claude-mem"
    _safe(prefix, directory=True)
    worker = prefix / WORKER
    _safe(worker)
    package = prefix / "node_modules/claude-mem/package.json"
    _safe(package)
    policy = manifest()
    require(json.loads(package.read_text())["version"] == policy["upstream_version"], "Unreviewed Claude-mem upstream version")
    return home, prefix, worker, policy


def _read_exact(path, expected_bytes):
    require(_safe(path).st_size == expected_bytes, "Claude-mem artifact byte count differs")
    with path.open("rb") as stream:
        raw = stream.read(expected_bytes + 1)
    require(len(raw) == expected_bytes, "Claude-mem artifact changed during read")
    return raw


def apply_bytes(raw, policy):
    """Pure exact-byte transform, also used to verify retained originals."""
    require(len(raw) == policy["upstream_bytes"] and digest(raw) == policy["upstream_sha256"], "Unreviewed Claude-mem upstream worker bytes")
    start, end = policy["start_byte"], policy["end_byte_exclusive"]
    old = raw[start:end]
    require(digest(old) == policy["span_sha256"] and raw.count(old) == 1, "Claude-mem patch span differs or is ambiguous")
    replacement = policy["replacement"].encode()
    require(digest(replacement) == policy["replacement_sha256"], "Claude-mem replacement bytes changed")
    marker = policy["license_marker"].encode()
    require(raw.count(marker) == 1 and raw.index(marker) >= end, "Claude-mem upstream licence footer is missing")
    effective = raw[:start] + replacement + raw[end:]
    require(len(effective) == policy["effective_bytes"] and digest(effective) == policy["effective_sha256"], "Claude-mem effective worker differs from reviewed patch")
    require(effective.endswith(raw[raw.index(marker):]), "Claude-mem licence footer changed")
    return effective


def _receipt(home, policy, original):
    return {"schema": SCHEMA, "home": str(home), "patch_id": policy["patch_id"],
            "package": "claude-mem", "upstream_version": policy["upstream_version"],
            "upstream_sha256": policy["upstream_sha256"], "effective_sha256": policy["effective_sha256"],
            "manifest_sha256": digest(wire(policy)), "span_sha256": policy["span_sha256"],
            "license_footer_sha256": digest(original[original.index(policy["license_marker"].encode()):]),
            "original": "upstream-worker-service.cjs", "worker": WORKER,
            "scope": "Downstream global orphan sweep disabled; not upstream-unmodified or capture acceptance"}


def artifacts(home):
    _, prefix, worker, _ = paths(home)
    return [worker, prefix / PATCH_DIRECTORY / "upstream-worker-service.cjs", prefix / PATCH_DIRECTORY / "receipt.json"]


def verify(home):
    home, prefix, worker, policy = paths(home)
    directory = prefix / PATCH_DIRECTORY
    _safe(directory, directory=True)
    original, receipt = directory / "upstream-worker-service.cjs", directory / "receipt.json"
    _safe(original)
    _safe(receipt)
    raw = _read_exact(original, policy["upstream_bytes"])
    require(_read_exact(worker, policy["effective_bytes"]) == apply_bytes(raw, policy), "Claude-mem effective package was altered")
    require(receipt.stat().st_size <= 8192, "Claude-mem patch receipt is oversized")
    value = json.loads(receipt.read_text())
    require(value == _receipt(home, policy, raw), "Claude-mem patch provenance differs")
    return value


def disclosure():
    policy = manifest()
    return {"upstream_version": policy["upstream_version"], "downstream_patch": policy["patch_id"],
            "required_effective_sha256": policy["effective_sha256"],
            "verification": "Managed worker entry verifies package inventory and patch provenance; native version is upstream only"}


def _fsync_directory(path):
    # Windows does not expose the POSIX directory-fsync contract here.
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish(path, raw, *, expected=None, mode=0o600):
    if path.exists() or path.is_symlink():
        _safe(path)
        require(expected is not None and path.read_bytes() == expected, "Concurrent Claude-mem package change")
    else:
        require(expected is None, "Claude-mem package disappeared during staging")
    descriptor, name = tempfile.mkstemp(prefix=".patch-", dir=path.parent)
    candidate = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        candidate.chmod(mode)
        if expected is None:
            os.link(candidate, path)  # No overwrite if another installer won.
        else:
            _safe(path)
            require(path.read_bytes() == expected, "Concurrent Claude-mem package change")
            os.replace(candidate, path)
        _fsync_directory(path.parent)
    finally:
        candidate.unlink(missing_ok=True)
        _fsync_directory(path.parent)


@contextmanager
def _locked(directory):
    path = directory / "staging.lock"
    if path.exists() or path.is_symlink():
        _safe(path)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "r+b") as stream:
        _safe(path)
        if path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        if os.name == "nt":
            import msvcrt
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def stage(home):
    """Installer hook before fingerprinting. Only this selected home's package."""
    home, prefix, worker, policy = paths(home)
    identity = (home / "home.json").read_bytes()
    directory = prefix / PATCH_DIRECTORY
    # Validate full bytes before creating staging state or a backup.
    require(worker.stat().st_size in {policy["upstream_bytes"], policy["effective_bytes"]}, "Claude-mem artifact byte count differs")
    current = _read_exact(worker, worker.stat().st_size)
    if digest(current) == policy["effective_sha256"]:
        return verify(home)
    effective = apply_bytes(current, policy)
    identity_file = home / "memory/claude-mem/worker.pid"
    require(not identity_file.exists() and not identity_file.is_symlink(),
            "Inspect and stop the existing observer identity before package patch staging; no live package is replaced")
    if directory.exists() or directory.is_symlink():
        _safe(directory, directory=True)
    else:
        directory.mkdir(mode=0o700)
        _fsync_directory(directory.parent)
    with _locked(directory):
        require((home / "home.json").read_bytes() == identity, "Home identity changed during package staging")
        original = directory / "upstream-worker-service.cjs"
        receipt = directory / "receipt.json"
        if original.exists() or original.is_symlink():
            _safe(original)
            require(original.read_bytes() == current, "Retained Claude-mem original differs")
        else:
            _publish(original, current)
        value = _receipt(home, policy, current)
        expected_receipt = wire(value) + b"\n"
        if receipt.exists() or receipt.is_symlink():
            _safe(receipt)
            require(receipt.read_bytes() == expected_receipt, "Retained Claude-mem patch receipt differs")
        # Publish provenance first. Entry refuses it until effective bytes match.
        else:
            _publish(receipt, expected_receipt)
        require((home / "home.json").read_bytes() == identity, "Home identity changed during package staging")
        _publish(worker, effective, expected=current, mode=stat.S_IMODE(worker.stat().st_mode))
    return verify(home)


def require_empty_registry(root):
    """A stored PID or process group is not authority to adopt or signal it."""
    root = Path(root)
    require(root.resolve() == root and not root.is_symlink(), "Observer data directory is redirected")
    path = root / "supervisor.json"
    if not path.exists() and not path.is_symlink():
        return
    _safe(path)
    require(path.stat().st_size <= 65536, "Observer registry exceeds its inspection bound")
    value = json.loads(path.read_text())
    require(isinstance(value, dict) and isinstance(value.get("processes"), dict)
            and not value["processes"], "Persisted observer registry entries require explicit ownership review; no startup or cleanup was attempted")
