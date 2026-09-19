#!/usr/bin/env python3
"""Compile an immutable project-local skill candidate from a verified closeout."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from project_identity import load_identity
from project_knowledge import build as build_knowledge


SCHEMA = "pi-project-skill-candidate/v1"
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


class SkillCandidateError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SkillCandidateError(message)


def _text(value: Any, name: str, maximum: int) -> str:
    _require(isinstance(value, str) and value == value.strip() and bool(value), f"{name} must be non-empty trimmed text")
    _require(len(value) <= maximum, f"{name} is too long")
    _require("\x00" not in value, f"{name} contains NUL")
    return value


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _inside(root: Path, value: Any, name: str) -> Path:
    supplied = Path(_text(value, name, 4096)).expanduser()
    path = supplied if supplied.is_absolute() else root / supplied
    path = path.resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise SkillCandidateError(f"{name} is outside the project root") from exc
    _require(path.is_file(), f"{name} must be a file")
    return path


def _list(value: Any, name: str, maximum_items: int, maximum_text: int) -> list[str]:
    _require(isinstance(value, list) and 1 <= len(value) <= maximum_items, f"{name} must contain 1 through {maximum_items} items")
    items = [_text(item, f"{name} item", maximum_text) for item in value]
    _require(len(items) == len(set(items)), f"{name} items must be unique")
    return items


def _write_once(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        _require(path.read_bytes() == data, f"existing candidate differs: {path.name}")


def compile_candidate(root: Path, request: Mapping[str, Any]) -> dict[str, Any]:
    root = root.expanduser().resolve(strict=True)
    identity = load_identity(root)
    required = {
        "name", "description", "closeout_path", "closeout_sha256",
        "triggers", "steps", "verification", "stop_conditions",
    }
    _require(set(request) == required, "skill candidate fields differ")
    name = _text(request["name"], "name", 64)
    _require(bool(IDENTIFIER.fullmatch(name)), "name must be lowercase kebab-case")
    description = _text(request["description"], "description", 500)
    triggers = _list(request["triggers"], "triggers", 12, 300)
    steps = _list(request["steps"], "steps", 30, 1000)
    verification = _list(request["verification"], "verification", 20, 1000)
    stop_conditions = _list(request["stop_conditions"], "stop_conditions", 20, 1000)

    closeout_path = _inside(root, request["closeout_path"], "closeout_path")
    closeout_bytes = closeout_path.read_bytes()
    closeout_sha256 = _text(request["closeout_sha256"], "closeout_sha256", 64)
    _require(bool(re.fullmatch(r"[a-f0-9]{64}", closeout_sha256)), "closeout_sha256 is invalid")
    _require(_sha256(closeout_bytes) == closeout_sha256, "closeout hash differs")
    try:
        closeout = json.loads(closeout_bytes)
    except json.JSONDecodeError as exc:
        raise SkillCandidateError("closeout is not valid JSON") from exc
    _require(isinstance(closeout, Mapping), "closeout must be an object")
    _require(closeout.get("schema") == "pi-project-closeout/v1", "closeout schema differs")
    _require(closeout.get("project_id") == identity["project_id"], "closeout project differs")
    _require(closeout.get("authority") == "verified_lesson_guidance_only", "closeout authority differs")
    receipt = closeout.get("receipt")
    _require(isinstance(receipt, Mapping), "closeout receipt is missing")
    _require(receipt.get("status") == "accepted" and receipt.get("authority_cap") == "tested", "closeout receipt is not accepted")

    skill_lines = [
        "---",
        f"name: {name}",
        f"description: {json.dumps(description, ensure_ascii=False)}",
        "---",
        "",
        f"# {name}",
        "",
        "Project-local candidate. This file is guidance only. It is not installed or promoted.",
        "",
        "## Use When",
        "",
        *[f"- {item}" for item in triggers],
        "",
        "## Steps",
        "",
        *[f"{index}. {item}" for index, item in enumerate(steps, 1)],
        "",
        "## Verification",
        "",
        *[f"- {item}" for item in verification],
        "",
        "## Stop Conditions",
        "",
        *[f"- {item}" for item in stop_conditions],
        "",
    ]
    skill_bytes = "\n".join(skill_lines).encode("utf-8")
    candidate_root = root / identity["local_skill_dir"] / name
    skill_path = candidate_root / "SKILL.md"
    manifest = {
        "schema": SCHEMA,
        "project_id": identity["project_id"],
        "name": name,
        "skill_path": skill_path.relative_to(root).as_posix(),
        "skill_sha256": _sha256(skill_bytes),
        "source_closeout": {
            "path": closeout_path.relative_to(root).as_posix(),
            "sha256": closeout_sha256,
            "task_id": closeout.get("task_id"),
            "receipt_sha256": receipt.get("sha256"),
        },
        "promotion_state": "project_local_candidate",
        "authority": "guidance_only",
        "limits": [
            "Not installed in any shared skill directory.",
            "No cross-project reuse or promotion authority.",
            "Independent review and repeated evidence are required before promotion.",
        ],
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    manifest_path = candidate_root / "candidate.json"
    _write_once(skill_path, skill_bytes)
    _write_once(manifest_path, manifest_bytes)
    knowledge = build_knowledge(root)
    return {
        "ok": True,
        "schema": SCHEMA,
        "project_id": identity["project_id"],
        "name": name,
        "skill_path": str(skill_path),
        "skill_sha256": _sha256(skill_bytes),
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256(manifest_bytes),
        "knowledge": knowledge,
        "promotion_state": "project_local_candidate",
        "authority": "guidance_only",
    }
