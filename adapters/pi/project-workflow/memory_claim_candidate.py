#!/usr/bin/env python3
"""Compile one verified closeout readback into an immutable memory claim candidate."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

SCHEMA = "pi-memory-claim-candidate/v1"
SENSITIVE = re.compile(
    r"(?:\b(?:password|passcode|access[ -]?code|api[ -]?key|secret|token|credential)\b|"
    r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",
    re.I,
)


class MemoryClaimError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MemoryClaimError(message)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _normalized_sha256(value: str) -> str:
    return _sha256(" ".join(value.split()).encode("utf-8"))


def _inside(root: Path, path: Path) -> Path:
    root = root.resolve()
    path = path.resolve()
    _require(path == root or root in path.parents, "path is outside project root")
    return path


def compile_candidate(project_root: Path, closeout_path: Path, drawer_snapshot_path: Path) -> dict:
    root = project_root.resolve()
    closeout_path = _inside(root, closeout_path)
    drawer_snapshot_path = _inside(root, drawer_snapshot_path)
    closeout_bytes = closeout_path.read_bytes()
    closeout = json.loads(closeout_bytes.decode("utf-8-sig"))
    snapshot = json.loads(drawer_snapshot_path.read_text(encoding="utf-8-sig"))

    _require(closeout.get("schema") == "pi-project-closeout/v1", "closeout schema differs")
    _require(closeout.get("authority") == "verified_lesson_guidance_only", "closeout authority differs")
    _require(isinstance(snapshot.get("drawer_id"), str) and snapshot["drawer_id"], "drawer_id is required")
    _require(isinstance(snapshot.get("content"), str) and snapshot["content"], "drawer content is required")
    metadata = snapshot.get("metadata") or {}
    _require(isinstance(metadata.get("filed_at"), str) and metadata["filed_at"], "drawer filed_at is required")

    expected_memory = {
        "schema": "pi-project-closeout-memory/v1",
        "project_id": closeout["project_id"],
        "task_id": closeout["task_id"],
        "summary": closeout["summary"],
        "lessons": closeout["lessons"],
        "closeout_path": closeout_path.relative_to(root).as_posix(),
        "closeout_sha256": _sha256(closeout_bytes),
        "receipt_sha256": closeout["receipt"]["sha256"],
        "authority": "guidance_only",
    }
    expected_content = json.dumps(expected_memory, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    _require(snapshot["content"] == expected_content, "drawer content differs from verified closeout memory payload")

    safe_text = closeout["summary"].strip() + " Lessons: " + " ".join(item.strip() for item in closeout["lessons"])
    _require(not SENSITIVE.search(safe_text), "safe summary contains sensitive or account data")
    source_sha256 = _sha256(snapshot["content"].encode("utf-8"))
    claim = {
        "claim_id": f"{closeout['project_id']}:{closeout['task_id']}",
        "claim_sha256": _normalized_sha256(snapshot["content"]),
        "source_path": f"mempalace://drawer/{snapshot['drawer_id']}",
        "source_sha256": source_sha256,
        "state": "current",
        "evidence_class": "validated_lesson",
        "observed_at": metadata["filed_at"],
        "safe_text": safe_text,
        "safe_text_sha256": _sha256(safe_text.encode("utf-8")),
        "closeout_path": closeout_path.relative_to(root).as_posix(),
        "closeout_sha256": _sha256(closeout_bytes),
        "receipt_sha256": closeout["receipt"]["sha256"],
        "authority": "guidance_only",
    }
    record = {"schema": SCHEMA, "claim": claim, "promotion_state": "project_local_candidate"}
    payload = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    target = root / ".icm" / "workspace" / "wiki" / "memory-candidates" / f"{closeout['task_id']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        _require(target.read_bytes() == payload.encode("utf-8"), "existing memory candidate differs")
    return {
        "ok": True,
        "schema": SCHEMA,
        "candidate_path": str(target),
        "candidate_sha256": _sha256(payload.encode("utf-8")),
        "claim_id": claim["claim_id"],
        "promotion_state": "project_local_candidate",
        "authority": "guidance_only",
    }
