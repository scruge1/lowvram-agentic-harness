#!/usr/bin/env python3
"""Read-only private/public Pi source parity inventory; never copies source bytes.

The input is an explicit mapping of relative paths within two supplied roots.
The JSON report contains only logical IDs, hashes, sizes and drift states.
A different hash requires review, never an automatic patch or deployment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

SCHEMA = "pi-source-parity/v1"
MAP_SCHEMA = "pi-source-parity-map/v1"
MAX_MAP_BYTES = 64 * 1024
MAX_COMPONENTS = 128
MAX_SOURCE_BYTES = 32 * 1024 * 1024
COMPONENT_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
DIGEST = re.compile(r"[a-f0-9]{64}\Z")


class ParityError(ValueError):
    """Invalid/missing source boundary: reject the whole audit."""


def _root(candidate: Path) -> Path:
    if candidate.is_symlink() or not candidate.is_dir():
        raise ParityError("Source root must be an existing ordinary directory")
    return candidate.resolve(strict=True)


def _relative(value: object) -> tuple[str, ...]:
    if not isinstance(value, str) or not 1 <= len(value) <= 512:
        raise ParityError("Expected a bounded POSIX-relative file path")
    if any(char in value for char in ("\\", ":", "\x00", "\n", "\r")):
        raise ParityError("Relative paths cannot contain backslashes, drive letters or controls")
    path = PurePosixPath(value)
    if (path.is_absolute() or len(path.parts) == 0 or "." in path.parts
            or ".." in path.parts or str(path) != value):
        raise ParityError("Path is not a canonical relative file path")
    return path.parts


def _hash_file(root: Path, relative: str):
    parts = _relative(relative)
    file = root
    for part in parts:
        file = file / part
        if file.is_symlink():
            raise ParityError("Symlink in the mapped file path")
    if not file.exists():
        return None
    canonical = file.resolve(strict=True)
    if root not in canonical.parents or not canonical.is_file():
        raise ParityError("Mapped file escapes the supplied root or is not regular")
    before = file.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_SOURCE_BYTES:
        raise ParityError("Source is not a regular bounded file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(file, flags)
        try:
            original = os.fstat(fd)
            if not stat.S_ISREG(original.st_mode) or original.st_size > MAX_SOURCE_BYTES:
                raise ParityError("Source identity changed during open")
            digest = hashlib.sha256()
            length = 0
            while True:
                part = os.read(fd, min(1024 * 1024, MAX_SOURCE_BYTES + 1 - length))
                if not part:
                    break
                digest.update(part)
                length += len(part)
                if length > MAX_SOURCE_BYTES:
                    raise ParityError("Source exceeded file-size ceiling")
            final = os.fstat(fd)
        finally:
            os.close(fd)
    except OSError as error:
        raise ParityError("Could not read a mapped source safely") from error
    def identity(info):
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
    if identity(before) != identity(original) or identity(original) != identity(final):
        raise ParityError("Mapped source changed during read; restart the audit")
    return {"sha256": digest.hexdigest(), "size_bytes": length}


def _mapping(file: Path):
    if file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_MAP_BYTES:
        raise ParityError("Mapping file is unavailable or oversized")
    try:
        with file.open("rb") as stream:
            data = stream.read(MAX_MAP_BYTES + 1)
        if len(data) > MAX_MAP_BYTES:
            raise ParityError("Mapping file exceeds size ceiling")
        manifest = json.loads(data)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ParityError("Mapping file is not valid JSON") from error
    if (not isinstance(manifest, dict) or set(manifest) != {"schema", "components"}
            or manifest["schema"] != MAP_SCHEMA):
        raise ParityError("Mapping schema/fields are invalid")
    entries = manifest["components"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_COMPONENTS:
        raise ParityError("Mapping must contain 1..128 components")
    seen_ids, seen_paths, seen_installed = set(), set(), set()
    for item in entries:
        if (not isinstance(item, dict) or set(item) != {"id", "public", "installed"}
                or not isinstance(item["id"], str) or not COMPONENT_ID.fullmatch(item["id"])):
            raise ParityError("Invalid mapping component ID or field set")
        a, b = _relative(item["public"]), _relative(item["installed"])
        if item["id"] in seen_ids or a in seen_paths or b in seen_installed:
            raise ParityError("Duplicate ID or mapped source")
        seen_ids.add(item["id"])
        seen_paths.add(a)
        seen_installed.add(b)
        if not b:
            raise ParityError("Missing installed source")
    return entries


def audit(public_root: Path, installed_root: Path, mapping: Path):
    public, installed = _root(public_root), _root(installed_root)
    if public == installed:
        raise ParityError("Public and installed roots must be different")
    entries = _mapping(mapping)
    rows = []
    for item in entries:
        left = _hash_file(public, item["public"])
        right = _hash_file(installed, item["installed"])
        state = ("missing_both" if left is None and right is None else
                 "missing_public" if left is None else
                 "missing_installed" if right is None else
                 "byte_identical" if left["sha256"] == right["sha256"] else
                 "needs_review")
        rows.append({
            "id": item["id"], "state": state,
            "public": left, "installed": right,
            "semantic_equivalence_verified": False,
            "automatic_sync_allowed": False,
        })
    counts = {state: sum(item["state"] == state for item in rows)
              for state in ("byte_identical", "needs_review",
                            "missing_both", "missing_public", "missing_installed")}
    return {
        "schema": SCHEMA,
        "status": "byte_identical" if counts["byte_identical"] == len(rows) else "review_required",
        "authority": "read_only_evidence_not_release_approval",
        "component_count": len(rows), "counts": counts, "components": rows,
        "source_text_returned": False, "files_written": 0,
        "disclaimer": ("SHA-256 equality is byte equality only; changed bytes need "
                       "semantic, regression, safety and release review. Missing "
                       "sources are not empty sources. Receipt may identify private "
                       "code via hashes; retain it privately."),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--public-root", required=True, type=Path)
    parser.add_argument("--installed-root", required=True, type=Path)
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--strict-drift", action="store_true")
    opts = parser.parse_args(argv)
    try:
        result = audit(opts.public_root, opts.installed_root, opts.mapping)
    except (ParityError, OSError, TypeError, ValueError):
        print(json.dumps({"schema": SCHEMA, "status": "invalid",
                          "authority": "none", "source_text_returned": False,
                          "error": "Parity audit refused invalid, missing or changing source boundaries"}))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if opts.strict_drift and result["status"] != "byte_identical":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
