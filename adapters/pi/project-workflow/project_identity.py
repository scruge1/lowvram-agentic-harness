#!/usr/bin/env python3
"""Resolve and initialize one stable project identity without overwriting it."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


SCHEMA = "pi-project-identity/v1"
PROJECT_FILE = Path(".icm/project.json")
PROJECT_ID_RE = re.compile(r"^p_[a-z0-9][a-z0-9-]{0,47}_[0-9a-f]{12}$")


class ProjectIdentityError(RuntimeError):
    """The project identity is absent, ambiguous, stale, or invalid."""


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical(path: Path) -> Path:
    return path.expanduser().resolve(strict=True)


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def _slug(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (value or "project")[:48].rstrip("-")


def _project_id(root: Path) -> str:
    digest = hashlib.sha256(os.path.normcase(str(root)).encode("utf-8")).hexdigest()[:12]
    return f"p_{_slug(root.name)}_{digest}"


def _find_up(start: Path, relative: Path) -> Path | None:
    current = start if start.is_dir() else start.parent
    for candidate_root in (current, *current.parents):
        if (candidate_root / relative).exists():
            return candidate_root
    return None


def resolve_project_root(start: Path, explicit_root: Path | None = None) -> tuple[Path, str]:
    """Resolve a project root from explicit input, an identity pointer, or Git."""
    if explicit_root is not None:
        root = _canonical(explicit_root)
        if not root.is_dir():
            raise ProjectIdentityError(f"explicit project root is not a directory: {root}")
        return root, "explicit"

    location = _canonical(start)
    pointer_root = _find_up(location, PROJECT_FILE)
    git_root = _find_up(location, Path(".git"))
    if pointer_root is not None:
        return pointer_root, "existing_pointer"
    if git_root is not None:
        return git_root, "git_toplevel"
    raise ProjectIdentityError(
        "no project root found; supply --root or work inside a tree with .icm/project.json or .git"
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectIdentityError(f"cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProjectIdentityError(f"project identity must be a JSON object: {path}")
    return value


def validate_identity(document: dict[str, Any], root: Path) -> dict[str, Any]:
    required = {
        "schema",
        "project_id",
        "canonical_root",
        "root_identity_method",
        "native_authority",
        "workspace_path",
        "board_id",
        "state_root",
        "knowledge_manifest",
        "knowledge_index",
        "local_skill_dir",
        "shared_skill_promotion",
        "created_at",
        "last_verified_at",
    }
    missing = sorted(required - document.keys())
    extra = sorted(document.keys() - required)
    if missing or extra:
        raise ProjectIdentityError(f"identity fields differ: missing={missing}, extra={extra}")
    if document["schema"] != SCHEMA:
        raise ProjectIdentityError(f"unsupported schema: {document['schema']!r}")
    if not isinstance(document["project_id"], str) or not PROJECT_ID_RE.fullmatch(document["project_id"]):
        raise ProjectIdentityError("invalid project_id")
    recorded_root = Path(str(document["canonical_root"])).expanduser().resolve(strict=False)
    if not _same_path(recorded_root, root):
        raise ProjectIdentityError(
            f"stale project root: pointer records {recorded_root}, resolved root is {root}"
        )
    expected_board = f"project:{document['project_id']}"
    if document["board_id"] != expected_board:
        raise ProjectIdentityError(f"board_id must be {expected_board}")
    expected_state = f"~/.local/state/pi-projects/{document['project_id']}"
    if document["state_root"] != expected_state:
        raise ProjectIdentityError(f"state_root must be {expected_state}")
    if document["shared_skill_promotion"] not in {"not_requested", "candidate", "reviewed", "promoted"}:
        raise ProjectIdentityError("invalid shared_skill_promotion")
    return document


def load_identity(root: Path) -> dict[str, Any]:
    canonical_root = _canonical(root)
    return validate_identity(_read_json(canonical_root / PROJECT_FILE), canonical_root)


def initialize_identity(
    root: Path,
    *,
    native_authority: str | None = None,
    workspace_path: str = ".icm/workspace",
) -> tuple[dict[str, Any], bool]:
    """Create an identity once, or validate and return the existing identity."""
    canonical_root = _canonical(root)
    if not canonical_root.is_dir():
        raise ProjectIdentityError(f"project root is not a directory: {canonical_root}")
    target = canonical_root / PROJECT_FILE
    if target.exists():
        return load_identity(canonical_root), False

    project_id = _project_id(canonical_root)
    timestamp = _utc_now()
    document: dict[str, Any] = {
        "schema": SCHEMA,
        "project_id": project_id,
        "canonical_root": str(canonical_root),
        "root_identity_method": "explicit",
        "native_authority": native_authority,
        "workspace_path": workspace_path,
        "board_id": f"project:{project_id}",
        "state_root": f"~/.local/state/pi-projects/{project_id}",
        "knowledge_manifest": ".icm/knowledge-manifest.json",
        "knowledge_index": f"~/.local/state/pi-projects/{project_id}/knowledge",
        "local_skill_dir": ".icm/skills",
        "shared_skill_promotion": "not_requested",
        "created_at": timestamp,
        "last_verified_at": timestamp,
    }
    validate_identity(document, canonical_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
    try:
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        return load_identity(canonical_root), False
    return document, True


def _result(document: dict[str, Any], root: Path, method: str, created: bool | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "root": str(root),
        "resolution_method": method,
        "identity": document,
    }
    if created is not None:
        result["created"] = created
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("resolve", "init", "status"))
    parser.add_argument("--start", type=Path, default=Path.cwd())
    parser.add_argument("--root", type=Path)
    parser.add_argument("--native-authority")
    parser.add_argument("--workspace-path", default=".icm/workspace")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            if args.root is None:
                raise ProjectIdentityError("init requires --root; implicit initialization is forbidden")
            root, method = resolve_project_root(args.start, args.root)
            document, created = initialize_identity(
                root,
                native_authority=args.native_authority,
                workspace_path=args.workspace_path,
            )
            result = _result(document, root, method, created)
        else:
            root, method = resolve_project_root(args.start, args.root)
            document = load_identity(root) if (root / PROJECT_FILE).exists() else {}
            if args.command == "status" and not document:
                raise ProjectIdentityError(f"project identity does not exist: {root / PROJECT_FILE}")
            result = _result(document, root, method)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except ProjectIdentityError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
