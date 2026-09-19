#!/usr/bin/env python3
"""Compile one verified project task closeout from an accepted workflow receipt."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from project_identity import load_identity
from project_knowledge import build as build_knowledge


SCHEMA = "pi-project-closeout/v1"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class CloseoutError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CloseoutError(message)


def _text(value: Any, name: str, maximum: int) -> str:
    _require(isinstance(value, str) and value == value.strip() and bool(value), f"{name} must be non-empty trimmed text")
    _require(len(value) <= maximum, f"{name} is too long")
    return value


def _identifier(value: Any, name: str) -> str:
    value = _text(value, name, 128)
    _require(bool(IDENTIFIER.fullmatch(value)), f"{name} has invalid characters")
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
        raise CloseoutError(f"{name} is outside the project root") from exc
    _require(path.is_file(), f"{name} must be a file")
    return path


def _load_receipt(root: Path, path_value: Any, expected_sha256: Any) -> tuple[Path, Mapping[str, Any], str]:
    path = _inside(root, path_value, "receipt_path")
    raw = path.read_bytes()
    digest = _sha256(raw)
    _require(_text(expected_sha256, "receipt_sha256", 64) == digest, "receipt hash differs")
    try:
        receipt = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CloseoutError("receipt is not valid JSON") from exc
    _require(isinstance(receipt, Mapping), "receipt must be an object")
    _require(receipt.get("receipt_type") == "enforced_task", "receipt type is not enforced_task")
    _require(receipt.get("status") == "accepted", "receipt status is not accepted")
    _require(receipt.get("authority_cap") == "tested", "receipt authority is not tested")
    _identifier(receipt.get("run_id"), "receipt run_id")
    outputs = receipt.get("outputs")
    _require(isinstance(outputs, list) and outputs, "receipt has no outputs")
    for output in outputs:
        _require(isinstance(output, Mapping), "receipt output must be an object")
        output_path = _inside(root, output.get("path"), "receipt output path")
        data = output_path.read_bytes()
        _require(output.get("exists") is True, "receipt output is not marked present")
        _require(output.get("size") == len(data), "receipt output size differs")
        _require(output.get("sha256") == _sha256(data), "receipt output hash differs")
    return path, receipt, digest


def compile_closeout(root: Path, request: Mapping[str, Any]) -> dict[str, Any]:
    root = root.expanduser().resolve(strict=True)
    identity = load_identity(root)
    required = {"task_id", "card_id", "receipt_path", "receipt_sha256", "summary", "lessons"}
    _require(set(request) == required, "closeout fields differ")
    task_id = _identifier(request["task_id"], "task_id")
    card_id = _identifier(request["card_id"], "card_id")
    summary = _text(request["summary"], "summary", 4000)
    lessons = request["lessons"]
    _require(isinstance(lessons, list) and 1 <= len(lessons) <= 20, "lessons must contain 1 through 20 items")
    lessons = [_text(item, "lesson", 2000) for item in lessons]
    _require(len(lessons) == len(set(lessons)), "lessons must be unique")
    receipt_path, receipt, receipt_sha256 = _load_receipt(root, request["receipt_path"], request["receipt_sha256"])

    record = {
        "schema": SCHEMA,
        "project_id": identity["project_id"],
        "board_id": identity["board_id"],
        "task_id": task_id,
        "card_id": card_id,
        "summary": summary,
        "lessons": lessons,
        "receipt": {
            "path": receipt_path.relative_to(root).as_posix(),
            "sha256": receipt_sha256,
            "run_id": receipt["run_id"],
            "status": receipt["status"],
            "authority_cap": receipt["authority_cap"],
            "outputs": receipt["outputs"],
        },
        "authority": "verified_lesson_guidance_only",
    }
    payload = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    target = root / ".icm" / "workspace" / "wiki" / "task-closeouts" / f"{task_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        _require(target.read_bytes() == payload.encode("utf-8"), "existing closeout differs")

    knowledge = build_knowledge(root)
    memory_payload = {
        "schema": "pi-project-closeout-memory/v1",
        "project_id": identity["project_id"],
        "task_id": task_id,
        "summary": summary,
        "lessons": lessons,
        "closeout_path": target.relative_to(root).as_posix(),
        "closeout_sha256": _sha256(payload.encode("utf-8")),
        "receipt_sha256": receipt_sha256,
        "authority": "guidance_only",
    }
    canonical_memory = json.dumps(memory_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {
        "ok": True,
        "schema": SCHEMA,
        "project_id": identity["project_id"],
        "task_id": task_id,
        "closeout_path": str(target),
        "closeout_sha256": _sha256(payload.encode("utf-8")),
        "knowledge": knowledge,
        "memory_payload": canonical_memory,
        "memory_payload_sha256": _sha256(canonical_memory.encode("utf-8")),
        "authority": "guidance_only",
    }
