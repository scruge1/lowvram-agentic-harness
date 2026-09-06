#!/usr/bin/env python3
"""Create a target-bound, unresolved SSOT scaffold for agent-led integration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from importlib import resources
from pathlib import Path
from typing import Any, Dict, Iterable, List

from ssot.control import SSOTError
from ssot.workflow import init_project


SCHEMA_VERSION = 1
PRD_NAME = "trusted-task-integration-prd.md"
PROFILE_NAME = "trusted-task-integration-target.json"
HOSTS = {"claude-code", "hermes", "pi", "generic"}
COMPONENTS = {"enforcement", "ssot", "local-inference", "research"}


class IntegrationError(RuntimeError):
    """The target cannot safely receive an integration scaffold."""


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _template_bytes() -> bytes:
    return (
        resources.files("harness")
        .joinpath("templates/integration-setup-prd.md")
        .read_bytes()
    )


def _surface_record(root: Path, relative: str) -> Dict[str, Any]:
    if not isinstance(relative, str) or not relative.strip():
        raise IntegrationError("surface paths must be non-empty strings")
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise IntegrationError(f"surface escapes target root: {relative}")
    unresolved = root / candidate
    current = unresolved
    while current != root:
        if current.is_symlink():
            raise IntegrationError(f"surface cannot use symlinks: {relative}")
        current = current.parent
    path = unresolved.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise IntegrationError(f"surface escapes target root: {relative}") from exc
    if not path.is_file():
        raise IntegrationError(f"surface must be an existing regular file: {relative}")
    stat = path.stat()
    return {
        "path": candidate.as_posix(),
        "size": stat.st_size,
        "sha256": _sha_file(path),
        "authority": "declared-discovery-input",
    }


def _write_new(path: Path, payload: bytes) -> None:
    if path.exists():
        raise IntegrationError(f"refusing to overwrite: {path.name}")
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def init_integration(
    root: Path,
    host: str,
    surfaces: Iterable[str] = (),
    components: Iterable[str] = ("enforcement", "ssot"),
) -> Dict[str, Any]:
    """Create target profile, setup PRD, and unresolved SSOT without overwrites."""
    root = root.resolve()
    if not root.is_dir():
        raise IntegrationError(f"target root does not exist: {root}")
    if host not in HOSTS:
        raise IntegrationError(f"unsupported host: {host}")
    selected = sorted(set(components))
    if not selected or any(item not in COMPONENTS for item in selected):
        raise IntegrationError("components must use supported non-empty values")
    if (root / "ssot-project.json").exists() or (root / ".ssot").exists():
        raise IntegrationError(
            "target already has SSOT state; add integration stages to that authority"
        )
    for name in (PRD_NAME, PROFILE_NAME):
        if (root / name).exists():
            raise IntegrationError(f"refusing to overwrite: {name}")

    declared_surfaces = sorted(set(surfaces))
    if not declared_surfaces:
        raise IntegrationError(
            "declare at least one target instruction or authority surface"
        )
    records = [_surface_record(root, item) for item in declared_surfaces]
    template = _template_bytes()
    module_path = Path(__file__).resolve()
    profile = {
        "schema_version": SCHEMA_VERSION,
        "status": "discovered_not_compiled",
        "authority": "scaffolded",
        "target_root": str(root),
        "host": host,
        "selected_components": selected,
        "declared_surfaces": records,
        "bootstrap": {
            "module": "harness.integration",
            "module_sha256": _sha_file(module_path),
            "setup_prd_sha256": _sha_bytes(template),
        },
        "open_requirements": [
            "read target instruction precedence",
            "discover all real action and bypass paths",
            "compile every setup and target-specific normative leaf",
            "configure target-specific producers, verifiers, and negative controls",
            "prove live host invocation and independent acceptance",
        ],
    }
    prd_path = root / PRD_NAME
    profile_path = root / PROFILE_NAME
    created: List[Path] = []
    try:
        _write_new(prd_path, template)
        created.append(prd_path)
        _write_new(
            profile_path,
            (json.dumps(profile, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        created.append(profile_path)
        scaffold = init_project(root, PRD_NAME, f"trusted-task-integration-{host}")
    except (IntegrationError, SSOTError):
        for path in reversed(created):
            if path.is_file():
                path.unlink()
        raise
    return {
        "status": "scaffolded",
        "authority": "no_installation_authority",
        "target_root": str(root),
        "host": host,
        "profile": str(profile_path),
        "setup_prd": str(prd_path),
        "ssot_manifest": scaffold["manifest"],
        "ready": False,
        "next": (
            "Give the target to an integrating agent. It must read the target's "
            "instructions, decompose every setup requirement into ssot-project.json, "
            "configure target-specific gates, and run blessed-ssot doctor."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="bootstrap an agent-led trusted-task integration SSOT"
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--host", choices=sorted(HOSTS), required=True)
    parser.add_argument("--surface", action="append", default=[])
    parser.add_argument("--component", action="append")
    args = parser.parse_args()
    try:
        result = init_integration(
            args.root,
            args.host,
            args.surface,
            args.component or ("enforcement", "ssot"),
        )
    except (IntegrationError, SSOTError) as exc:
        parser.exit(2, f"INTEGRATION HOLD: {exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
