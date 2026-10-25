#!/usr/bin/env python3
"""Bind the installed Framework decision helper to one target environment."""

from __future__ import annotations

import argparse
import base64
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import sys


SCHEMA = "pi-framework-binding/v1"
FRAMEWORK_VERSION = "1.21.0"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_binding() -> dict:
    """Check wheel RECORD bytes before binding all installed core Python sources."""
    dist = metadata.distribution("agent-framework-core")
    if dist.version != FRAMEWORK_VERSION:
        raise ValueError("Agent Framework version differs from the qualified 1.21.0")
    site = Path(dist.locate_file(".")).resolve(strict=True)
    source_records = [item for item in (dist.files or [])
                      if str(item).startswith("agent_framework/") and str(item).endswith(".py")]
    if not source_records or len(source_records) > 500:
        raise ValueError("Framework distribution has no bounded installed source inventory")
    files = []
    seen = set()
    for item in source_records:
        path = Path(dist.locate_file(item)).resolve(strict=True)
        try:
            path.relative_to(site)
        except ValueError as exc:
            raise ValueError("Framework source escapes its installed distribution") from exc
        if not path.is_file() or path in seen:
            raise ValueError("Framework source is missing or duplicated")
        seen.add(path)
        record_hash = item.hash
        if record_hash is None or record_hash.mode != "sha256":
            raise ValueError("Framework source has no wheel RECORD SHA256")
        digest = sha256(path)
        encoded = base64.urlsafe_b64encode(bytes.fromhex(digest)).decode("ascii").rstrip("=")
        if encoded != record_hash.value:
            raise ValueError("Framework source differs from its installed wheel RECORD")
        files.append({"path": str(path), "sha256": digest})
    helper = Path(__file__).with_name("decision-138.py").resolve(strict=True)
    python = Path(sys.executable).absolute()
    if not python.is_file() or not helper.is_file():
        raise ValueError("Target Python or decision helper is unavailable")
    return {"schema": SCHEMA, "framework_version": FRAMEWORK_VERSION,
            "python": str(python), "python_sha256": sha256(python),
            "helper": str(helper), "helper_sha256": sha256(helper),
            "files": sorted(files, key=lambda item: item["path"])}


def write_binding(output: Path) -> dict:
    if not output.is_absolute():
        raise ValueError("Binding output must be an absolute path")
    parent = output.parent.resolve(strict=True)
    if not parent.is_dir():
        raise ValueError("Binding output parent must exist")
    target = parent / output.name
    # Refuse an occupied destination before inspecting the target environment.
    if target.exists() or target.is_symlink():
        raise FileExistsError("Framework binding already exists; preserve its accepted generation")
    value = build_binding()
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    with target.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"schema": SCHEMA, "path": str(target), "sha256": hashlib.sha256(raw).hexdigest(),
            "framework_version": FRAMEWORK_VERSION, "files": len(value["files"]),
            "authority": "installed_source_binding_only"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path,
                      help="Absent absolute JSON filename inside the selected agent home")
    mode.add_argument("--verify", type=Path,
                      help="Verify an existing generation against the actual complete target binding")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            if not args.verify.is_absolute() or args.verify.is_symlink():
                raise ValueError("Existing binding must be an absolute regular file")
            raw = args.verify.read_bytes()
            if json.loads(raw) != build_binding():
                raise ValueError("Existing Framework binding differs from the actual selected target")
            result = {"schema": SCHEMA, "path": str(args.verify),
                      "sha256": hashlib.sha256(raw).hexdigest(), "framework_version": FRAMEWORK_VERSION,
                      "authority": "installed_source_binding_only"}
        else:
            result = write_binding(args.output)
    except (OSError, ValueError, metadata.PackageNotFoundError) as exc:
        print(json.dumps({"schema": SCHEMA, "ok": False, "error": str(exc)}))
        return 2
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
