#!/usr/bin/env python3
"""Admit a reinforced PRD through a source-bound review checkpoint."""

from __future__ import annotations

import json
import os
import shutil
import stat
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from harness.enforcement import (
    EnforcementError,
    _files,
    _run_verifier,
    _validate_command,
    _validate_research,
)
from harness.project import (
    ProjectError,
    _append_event,
    _canonical,
    _load_intent,
    _project_lock,
    _sha_bytes,
    _sha_file,
    _target_root,
    project_status,
)


SCHEMA_VERSION = 1
SOURCE_CLASSES = {"user", "target", "research", "agent_proposal"}
REINFORCEMENT_CHECKS = (
    "coverage",
    "contradictions",
    "provenance",
    "feasibility",
    "risk",
    "failure_recovery",
    "measurable_acceptance",
)
FINAL_NAMES = {
    "contract": "admission-contract.json",
    "prd": "PRD.md",
    "manifest": "prd-manifest.json",
    "reinforcement": "prd-reinforcement.json",
    "receipt": "review-receipt.json",
}


def _is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(os.path, "isjunction", None)
    if is_junction is not None and is_junction(path):
        return True
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, FileNotFoundError):
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _safe_path(root: Path, relative: str, label: str, *, file: bool = True) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise ProjectError(f"{label} must be a non-empty relative path")
    candidate = Path(relative)
    if candidate.is_absolute():
        raise ProjectError(f"{label} cannot be absolute")
    unresolved = root / candidate
    current = root
    for part in candidate.parts:
        if part in ("", ".", ".."):
            raise ProjectError(f"{label} contains an unsafe path segment")
        current = current / part
        if os.path.lexists(current) and _is_link_or_reparse(current):
            raise ProjectError(f"{label} cannot use a link or reparse point")
    resolved = unresolved.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ProjectError(f"{label} escapes the target root") from exc
    if file and not resolved.is_file():
        raise ProjectError(f"{label} is not an existing regular file")
    return resolved


def _read_object(path: Path, label: str) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProjectError(f"{label} must contain a JSON object")
    return value


def _string_list(value: Any, label: str, *, nonempty: bool = False) -> List[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ProjectError(f"{label} must be a list")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ProjectError(f"{label} must contain non-empty strings")
    if len(value) != len(set(value)):
        raise ProjectError(f"{label} must not contain duplicates")
    return list(value)


def _file_record(root: Path, path: Path) -> Dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "size": path.stat().st_size,
        "sha256": _sha_file(path),
    }


def _validate_record(root: Path, record: Any, label: str) -> Path:
    if not isinstance(record, dict):
        raise ProjectError(f"{label} file record is invalid")
    path = _safe_path(root, record.get("path"), label)
    if record.get("size") != path.stat().st_size:
        raise ProjectError(f"{label} size changed")
    if record.get("sha256") != _sha_file(path):
        raise ProjectError(f"{label} hash changed")
    return path


def _validate_source(
    root: Path,
    source: Any,
    requirement_text: str,
    intent: Dict[str, Any],
    label: str,
) -> None:
    if not isinstance(source, dict) or source.get("class") not in SOURCE_CLASSES:
        raise ProjectError(f"{label}.source.class must name a supported source class")
    source_class = source["class"]
    locator = source.get("locator")
    if not isinstance(locator, str) or not locator.strip():
        raise ProjectError(f"{label}.source.locator is required")
    digest = source.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ProjectError(f"{label}.source.sha256 must be lowercase SHA-256")
    if any(character not in "0123456789abcdef" for character in digest):
        raise ProjectError(f"{label}.source.sha256 must be lowercase SHA-256")
    if source_class == "user":
        if set(source) != {"class", "locator", "sha256"}:
            raise ProjectError(f"{label}.source has invalid user-source fields")
        if locator != "intent.request" or digest != intent["request"]["sha256"]:
            raise ProjectError(f"{label}.source does not bind the exact user request")
        return
    if source_class == "agent_proposal":
        if set(source) != {"class", "locator", "sha256"}:
            raise ProjectError(f"{label}.source has invalid proposal fields")
        if digest != _sha_bytes(requirement_text.encode("utf-8")):
            raise ProjectError(f"{label}.source does not bind the proposal text")
        return
    if set(source) != {"class", "locator", "path", "sha256"}:
        raise ProjectError(f"{label}.source has invalid file-source fields")
    path = _safe_path(root, source.get("path"), f"{label}.source.path")
    if _sha_file(path) != digest:
        raise ProjectError(f"{label}.source file hash changed")
    if source_class == "research":
        try:
            _validate_research(_read_object(path, f"{label} research receipt"), 1)
        except EnforcementError as exc:
            raise ProjectError(f"{label}.source research is not admitted: {exc}") from exc


def _validate_prd_locator(prd_path: Path, locator: Any, label: str) -> None:
    required = {"line_start", "line_end", "text_sha256"}
    if not isinstance(locator, dict) or set(locator) != required:
        raise ProjectError(f"{label}.prd_locator fields are invalid")
    start = locator.get("line_start")
    end = locator.get("line_end")
    lines = prd_path.read_bytes().splitlines(keepends=True)
    if (
        type(start) is not int
        or type(end) is not int
        or start < 1
        or end < start
        or end > len(lines)
    ):
        raise ProjectError(f"{label}.prd_locator line range is invalid")
    digest = locator.get("text_sha256")
    actual = _sha_bytes(b"".join(lines[start - 1 : end]))
    if digest != actual:
        raise ProjectError(f"{label}.prd_locator text hash mismatch")


def _validate_manifest(
    root: Path,
    manifest: Dict[str, Any],
    intent: Dict[str, Any],
    intent_sha256: str,
    prd_path: Path,
) -> List[str]:
    required = {
        "schema_version",
        "project_id",
        "intent_sha256",
        "prd_sha256",
        "requirements",
        "non_goals",
        "constraints",
        "risks",
        "dependencies",
        "deliverables",
        "open_decisions",
    }
    if set(manifest) != required:
        raise ProjectError("PRD manifest fields do not match the portable schema")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ProjectError("PRD manifest schema_version must be 1")
    if manifest.get("project_id") != intent["project_id"]:
        raise ProjectError("PRD manifest project_id mismatch")
    if manifest.get("intent_sha256") != intent_sha256:
        raise ProjectError("PRD manifest intent hash mismatch")
    if manifest.get("prd_sha256") != _sha_file(prd_path):
        raise ProjectError("PRD manifest PRD hash mismatch")
    for name in ("non_goals", "constraints", "dependencies", "open_decisions"):
        _string_list(manifest.get(name), f"PRD manifest {name}")
    _string_list(manifest.get("deliverables"), "PRD manifest deliverables", nonempty=True)
    risks = manifest.get("risks")
    if not isinstance(risks, list):
        raise ProjectError("PRD manifest risks must be a list")
    for index, risk in enumerate(risks):
        if (
            not isinstance(risk, dict)
            or set(risk) != {"risk", "mitigation"}
            or not all(isinstance(value, str) and value.strip() for value in risk.values())
        ):
            raise ProjectError(f"PRD manifest risks[{index}] is invalid")
    requirements = manifest.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        raise ProjectError("PRD manifest requirements must be a non-empty list")
    identifiers = []
    for index, requirement in enumerate(requirements):
        label = f"PRD manifest requirements[{index}]"
        if not isinstance(requirement, dict) or set(requirement) != {
            "id",
            "text",
            "acceptance",
            "sources",
            "prd_locator",
        }:
            raise ProjectError(f"{label} fields are invalid")
        identifier = requirement.get("id")
        text = requirement.get("text")
        if not isinstance(identifier, str) or not identifier.strip():
            raise ProjectError(f"{label}.id is required")
        if not isinstance(text, str) or not text.strip():
            raise ProjectError(f"{label}.text is required")
        _string_list(requirement.get("acceptance"), f"{label}.acceptance", nonempty=True)
        sources = requirement.get("sources")
        if not isinstance(sources, list) or not sources:
            raise ProjectError(f"{label}.sources must be a non-empty list")
        source_digests = []
        for source_index, source in enumerate(sources):
            _validate_source(root, source, text, intent, f"{label}.sources[{source_index}]")
            source_digests.append(_sha_bytes(_canonical(source)))
        if len(source_digests) != len(set(source_digests)):
            raise ProjectError(f"{label}.sources must not contain duplicates")
        _validate_prd_locator(prd_path, requirement.get("prd_locator"), label)
        identifiers.append(identifier)
    if len(identifiers) != len(set(identifiers)):
        raise ProjectError("PRD requirement ids must be unique")
    return identifiers


def _validate_reinforcement(
    report: Dict[str, Any],
    *,
    project_id: str,
    drafter: str,
    prd_sha256: str,
    manifest_sha256: str,
) -> str:
    required = {
        "schema_version",
        "project_id",
        "critic_identity",
        "prd_sha256",
        "manifest_sha256",
        "checks",
        "issues",
        "open_decisions",
    }
    if set(report) != required or report.get("schema_version") != SCHEMA_VERSION:
        raise ProjectError("reinforcement report fields do not match schema version 1")
    if report.get("project_id") != project_id:
        raise ProjectError("reinforcement report project_id mismatch")
    critic = report.get("critic_identity")
    if not isinstance(critic, str) or not critic.strip() or critic == drafter:
        raise ProjectError("reinforcement critic must be distinct from the drafter")
    if report.get("prd_sha256") != prd_sha256:
        raise ProjectError("reinforcement report PRD hash mismatch")
    if report.get("manifest_sha256") != manifest_sha256:
        raise ProjectError("reinforcement report manifest hash mismatch")
    issues = _string_list(report.get("issues"), "reinforcement issues")
    decisions = _string_list(report.get("open_decisions"), "reinforcement open_decisions")
    if issues or decisions:
        raise ProjectError("reinforcement report retains unresolved issues or decisions")
    checks = report.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(REINFORCEMENT_CHECKS):
        raise ProjectError("reinforcement report must contain every required check")
    for name in REINFORCEMENT_CHECKS:
        check = checks[name]
        if not isinstance(check, dict) or set(check) != {"passed", "evidence"}:
            raise ProjectError(f"reinforcement check {name} is invalid")
        evidence = _string_list(
            check.get("evidence"), f"reinforcement check {name} evidence", nonempty=True
        )
        if check.get("passed") is not True or not evidence:
            raise ProjectError(f"reinforcement check {name} did not pass")
    return critic


def _validate_reviewer(
    root: Path, reviewer: Any, drafter: str, critic: str
) -> Dict[str, Any]:
    if not isinstance(reviewer, dict):
        raise ProjectError("reviewer contract must be an object")
    owner = reviewer.get("owner")
    if not isinstance(owner, str) or not owner.strip():
        raise ProjectError("reviewer.owner is required")
    if owner in {drafter, critic}:
        raise ProjectError("reviewer must be distinct from drafter and critic")
    try:
        positive = _validate_command(reviewer, "reviewer", root, require_files=True)
        negative = _validate_command(
            reviewer.get("negative_control"), "reviewer.negative_control", root
        )
    except EnforcementError as exc:
        raise ProjectError(f"invalid reviewer contract: {exc}") from exc
    if positive["argv"] == negative["argv"]:
        raise ProjectError("reviewer negative control must use a distinct invocation")
    shared = 2 if positive["argv"][0] == "{python}" else 1
    if positive["argv"][:shared] != negative["argv"][:shared]:
        raise ProjectError("negative control must exercise the same reviewer program")
    for name in [*positive["files"], *negative["files"]]:
        _safe_path(root, name, "reviewer file")
    positive["negative_control"] = negative
    positive["owner"] = owner
    positive["all_files"] = sorted(set(positive["files"] + negative["files"]))
    return positive


def _parse_review_output(output: str, label: str) -> Dict[str, Any]:
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ProjectError(f"{label} did not return one JSON object") from exc
    if not isinstance(value, dict):
        raise ProjectError(f"{label} did not return one JSON object")
    return value


def _target_digest(root: Path) -> Dict[str, str]:
    """Bind the complete target while a read-only reviewer runs."""
    result = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if _is_link_or_reparse(path):
            result[relative] = "link-or-reparse"
        elif path.is_file():
            result[relative] = _sha_file(path)
        elif path.is_dir():
            result[relative + "/"] = "directory"
    return result


def _run_review(
    root: Path,
    reviewer: Dict[str, Any],
    *,
    project_id: str,
    intent_sha256: str,
    prd: Path,
    manifest: Path,
    reinforcement: Path,
    requirement_ids: List[str],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    values = {
        "project_id": project_id,
        "intent_sha256": intent_sha256,
        "prd": str(prd),
        "prd_sha256": _sha_file(prd),
        "manifest": str(manifest),
        "manifest_sha256": _sha_file(manifest),
        "reinforcement": str(reinforcement),
        "reinforcement_sha256": _sha_file(reinforcement),
    }
    environment = os.environ.copy()
    environment.update(
        {"TRUSTED_PROJECT_" + key.upper(): value for key, value in values.items()}
    )
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    before = _target_digest(root)
    try:
        negative, positive = _run_verifier(root, reviewer, values, environment)
    except EnforcementError as exc:
        raise ProjectError(f"independent PRD review failed: {exc}") from exc
    if before != _target_digest(root):
        raise ProjectError("independent PRD reviewer changed target files")
    negative_value = _parse_review_output(negative["stdout"], "reviewer negative control")
    if negative_value.get("verdict") != "negative_control_pass":
        raise ProjectError("reviewer negative control did not prove rejection")
    if negative_value.get("reviewer_identity") != reviewer["owner"]:
        raise ProjectError("reviewer negative-control identity mismatch")
    if positive["exit_code"] != 0:
        detail = positive["stderr"] or positive["stdout"] or "no diagnostic"
        raise ProjectError(f"independent reviewer rejected PRD: {detail[-1000:]}")
    approved = _parse_review_output(positive["stdout"], "independent reviewer")
    expected = {
        "verdict": "approved",
        "reviewer_identity": reviewer["owner"],
        "project_id": project_id,
        "intent_sha256": intent_sha256,
        "prd_sha256": values["prd_sha256"],
        "manifest_sha256": values["manifest_sha256"],
        "reinforcement_sha256": values["reinforcement_sha256"],
        "requirement_ids": requirement_ids,
        "open_decisions": [],
    }
    if approved != expected:
        raise ProjectError("independent reviewer output does not bind the exact candidate")
    return negative, positive


def _receipt_body(receipt: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in receipt.items() if key != "record_sha256"}


def _write_bytes_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ProjectError(f"refusing to overwrite immutable PRD artifact: {path}") from exc


def _build_stage(
    root: Path,
    project_dir: Path,
    contract_path: Path,
    prd_path: Path,
    manifest_path: Path,
    reinforcement_path: Path,
    receipt: Dict[str, Any],
) -> Path:
    stage = project_dir / f".prd-stage-{uuid.uuid4().hex}"
    stage.mkdir(parents=False, exist_ok=False)
    sources = {
        FINAL_NAMES["contract"]: contract_path,
        FINAL_NAMES["prd"]: prd_path,
        FINAL_NAMES["manifest"]: manifest_path,
        FINAL_NAMES["reinforcement"]: reinforcement_path,
    }
    for name, source in sources.items():
        _write_bytes_new(stage / name, source.read_bytes())
    receipt_bytes = json.dumps(
        receipt, indent=2, sort_keys=True, ensure_ascii=False
    ).encode("utf-8") + b"\n"
    _write_bytes_new(stage / FINAL_NAMES["receipt"], receipt_bytes)
    return stage


def _verify_receipt_at(
    root: Path,
    project_dir: Path,
    intent: Dict[str, Any],
    intent_sha256: str,
    receipt_path: Path,
) -> Dict[str, Any]:
    if receipt_path != project_dir / "prd" / FINAL_NAMES["receipt"]:
        raise ProjectError("review receipt path is not canonical")
    receipt_path = _safe_path(
        root, receipt_path.relative_to(root).as_posix(), "review receipt"
    )
    receipt = _read_object(receipt_path, "review receipt")
    if receipt.get("record_sha256") != _sha_bytes(_canonical(_receipt_body(receipt))):
        raise ProjectError("review receipt self-hash is invalid")
    if (
        receipt.get("schema_version") != SCHEMA_VERSION
        or receipt.get("receipt_type") != "reviewed_prd"
        or receipt.get("status") != "reviewed"
        or receipt.get("authority_cap") != "reviewed_prd_only_no_execution"
        or receipt.get("project_id") != project_dir.name
        or receipt.get("intent_sha256") != intent_sha256
    ):
        raise ProjectError("review receipt identity or authority is invalid")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {
        "contract",
        "prd",
        "manifest",
        "reinforcement",
    }:
        raise ProjectError("review receipt artifact set is invalid")
    artifact_paths = {}
    for name, record in artifacts.items():
        path = _validate_record(root, record, f"reviewed {name}")
        if path.parent != project_dir / "prd" or path.name != FINAL_NAMES[name]:
            raise ProjectError(f"reviewed {name} path is not canonical")
        artifact_paths[name] = path
    reviewer = receipt.get("reviewer")
    if not isinstance(reviewer, dict) or not isinstance(reviewer.get("files"), list):
        raise ProjectError("review receipt has no reviewer file pins")
    for index, record in enumerate(reviewer["files"]):
        _validate_record(root, record, f"reviewer file {index}")
    contract = _read_object(artifact_paths["contract"], "reviewed admission contract")
    drafter = contract.get("drafter_identity")
    if contract.get("project_id") != project_dir.name or not isinstance(drafter, str):
        raise ProjectError("reviewed admission contract identity is invalid")
    manifest = _read_object(artifact_paths["manifest"], "reviewed PRD manifest")
    requirement_ids = _validate_manifest(
        root,
        manifest,
        intent,
        intent_sha256,
        artifact_paths["prd"],
    )
    if manifest["open_decisions"]:
        raise ProjectError("reviewed PRD retains unresolved material decisions")
    reinforcement = _read_object(
        artifact_paths["reinforcement"], "reviewed reinforcement report"
    )
    critic = _validate_reinforcement(
        reinforcement,
        project_id=project_dir.name,
        drafter=drafter,
        prd_sha256=_sha_file(artifact_paths["prd"]),
        manifest_sha256=_sha_file(artifact_paths["manifest"]),
    )
    reviewed_reviewer = _validate_reviewer(root, contract.get("reviewer"), drafter, critic)
    if reviewer.get("owner") != reviewed_reviewer["owner"]:
        raise ProjectError("review receipt reviewer owner mismatch")
    recorded_files = sorted(record.get("path") for record in reviewer["files"])
    if recorded_files != reviewed_reviewer["all_files"]:
        raise ProjectError("review receipt does not pin every reviewer file")
    if receipt.get("requirement_ids") != requirement_ids:
        raise ProjectError("review receipt requirement coverage mismatch")
    return receipt


def verify_review_event(
    root: Path,
    project_dir: Path,
    intent: Dict[str, Any],
    intent_sha256: str,
    event: Dict[str, Any],
) -> Dict[str, Any]:
    details = event.get("details")
    if not isinstance(details, dict):
        raise ProjectError("PRD review event details are invalid")
    receipt_path = _safe_path(root, details.get("receipt_path"), "review receipt")
    if details.get("receipt_sha256") != _sha_file(receipt_path):
        raise ProjectError("PRD review event receipt hash mismatch")
    return _verify_receipt_at(root, project_dir, intent, intent_sha256, receipt_path)


def _candidate_paths(
    root: Path, contract: Dict[str, Any]
) -> Tuple[Path, Path, Path]:
    return (
        _safe_path(root, contract.get("prd_path"), "contract prd_path"),
        _safe_path(root, contract.get("manifest_path"), "contract manifest_path"),
        _safe_path(
            root,
            contract.get("reinforcement_path"),
            "contract reinforcement_path",
        ),
    )


def _assert_unchanged(records: Iterable[Dict[str, Any]], root: Path) -> None:
    for record in records:
        _validate_record(root, record, "candidate input")


def admit_prd(root: Path, project_id: str, contract_file: Path) -> Dict[str, Any]:
    """Validate and publish one reviewed PRD checkpoint without compiling stages."""
    root = _target_root(root)
    project_dir, intent_path, intent = _load_intent(root, project_id)
    intent_sha256 = _sha_file(intent_path)
    events = project_status(root, project_id)
    if events["state"] == "prd_reviewed":
        events["idempotent"] = True
        return events
    if events["state"] != "intent_captured":
        raise ProjectError(f"PRD admission is held while project state is {events['state']}")
    if intent["open_decisions"]:
        raise ProjectError("intent retains unresolved material decisions")

    final_dir = project_dir / "prd"
    if final_dir.is_dir():
        receipt_path = final_dir / FINAL_NAMES["receipt"]
        receipt = _verify_receipt_at(
            root, project_dir, intent, intent_sha256, receipt_path
        )
        with _project_lock(root, project_id):
            current_events = project_status(root, project_id)
            if current_events["state"] == "intent_captured":
                _append_event(
                    project_dir,
                    intent_sha256,
                    "prd_reviewed",
                    {
                        "receipt_path": receipt_path.relative_to(root).as_posix(),
                        "receipt_sha256": _sha_file(receipt_path),
                        "recovered_after_publish": True,
                    },
                )
        result = project_status(root, project_id)
        result["idempotent"] = True
        result["receipt_sha256"] = receipt["record_sha256"]
        return result
    if os.path.lexists(final_dir):
        raise ProjectError("canonical PRD checkpoint path is not a directory")

    unresolved_contract = contract_file if contract_file.is_absolute() else root / contract_file
    try:
        contract_relative = unresolved_contract.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise ProjectError("PRD admission contract escapes target root") from exc
    contract_path = _safe_path(root, contract_relative, "PRD admission contract")
    contract = _read_object(contract_path, "PRD admission contract")
    required_contract = {
        "schema_version",
        "project_id",
        "drafter_identity",
        "prd_path",
        "manifest_path",
        "reinforcement_path",
        "reviewer",
    }
    if set(contract) != required_contract or contract.get("schema_version") != SCHEMA_VERSION:
        raise ProjectError("PRD admission contract fields do not match schema version 1")
    if contract.get("project_id") != project_id:
        raise ProjectError("PRD admission contract project_id mismatch")
    drafter = contract.get("drafter_identity")
    if not isinstance(drafter, str) or not drafter.strip():
        raise ProjectError("drafter_identity is required")
    prd_path, manifest_path, reinforcement_path = _candidate_paths(root, contract)
    if len({prd_path, manifest_path, reinforcement_path, contract_path}) != 4:
        raise ProjectError("PRD candidate inputs must be separate files")
    prd_sha256 = _sha_file(prd_path)
    manifest = _read_object(manifest_path, "PRD manifest")
    requirement_ids = _validate_manifest(root, manifest, intent, intent_sha256, prd_path)
    if manifest["open_decisions"]:
        raise ProjectError("PRD manifest retains unresolved material decisions")
    reinforcement = _read_object(reinforcement_path, "reinforcement report")
    critic = _validate_reinforcement(
        reinforcement,
        project_id=project_id,
        drafter=drafter,
        prd_sha256=prd_sha256,
        manifest_sha256=_sha_file(manifest_path),
    )
    reviewer = _validate_reviewer(root, contract.get("reviewer"), drafter, critic)
    pinned_inputs = [
        _file_record(root, path)
        for path in (contract_path, prd_path, manifest_path, reinforcement_path)
    ]
    negative, positive = _run_review(
        root,
        reviewer,
        project_id=project_id,
        intent_sha256=intent_sha256,
        prd=prd_path,
        manifest=manifest_path,
        reinforcement=reinforcement_path,
        requirement_ids=requirement_ids,
    )
    _assert_unchanged(pinned_inputs, root)

    artifact_records = {
        "contract": {
            "path": (project_dir / "prd" / FINAL_NAMES["contract"])
            .relative_to(root)
            .as_posix(),
            "size": contract_path.stat().st_size,
            "sha256": _sha_file(contract_path),
        },
        "prd": {
            "path": (project_dir / "prd" / FINAL_NAMES["prd"])
            .relative_to(root)
            .as_posix(),
            "size": prd_path.stat().st_size,
            "sha256": _sha_file(prd_path),
        },
        "manifest": {
            "path": (project_dir / "prd" / FINAL_NAMES["manifest"])
            .relative_to(root)
            .as_posix(),
            "size": manifest_path.stat().st_size,
            "sha256": _sha_file(manifest_path),
        },
        "reinforcement": {
            "path": (project_dir / "prd" / FINAL_NAMES["reinforcement"])
            .relative_to(root)
            .as_posix(),
            "size": reinforcement_path.stat().st_size,
            "sha256": _sha_file(reinforcement_path),
        },
    }
    reviewer_files = _files(root, reviewer["all_files"], require=True)
    receipt_body = {
        "schema_version": SCHEMA_VERSION,
        "receipt_type": "reviewed_prd",
        "status": "reviewed",
        "authority_cap": "reviewed_prd_only_no_execution",
        "project_id": project_id,
        "intent_sha256": intent_sha256,
        "requirement_ids": requirement_ids,
        "artifacts": artifact_records,
        "reviewer": {
            "owner": reviewer["owner"],
            "files": reviewer_files,
            "negative_control": {
                "argv": negative["argv"],
                "exit_code": negative["exit_code"],
                "stdout_sha256": _sha_bytes(negative["stdout"].encode("utf-8")),
            },
            "positive": {
                "argv": positive["argv"],
                "exit_code": positive["exit_code"],
                "stdout_sha256": _sha_bytes(positive["stdout"].encode("utf-8")),
            },
        },
    }
    receipt = {
        **receipt_body,
        "record_sha256": _sha_bytes(_canonical(receipt_body)),
    }
    stage = _build_stage(
        root,
        project_dir,
        contract_path,
        prd_path,
        manifest_path,
        reinforcement_path,
        receipt,
    )
    try:
        with _project_lock(root, project_id):
            _assert_unchanged(pinned_inputs, root)
            current = project_status(root, project_id)
            if current["state"] != "intent_captured":
                raise ProjectError(
                    f"project state changed before PRD publication: {current['state']}"
                )
            if os.path.lexists(final_dir):
                raise ProjectError("canonical PRD checkpoint appeared during review")
            os.replace(stage, final_dir)
            receipt_path = final_dir / FINAL_NAMES["receipt"]
            _append_event(
                project_dir,
                intent_sha256,
                "prd_reviewed",
                {
                    "receipt_path": receipt_path.relative_to(root).as_posix(),
                    "receipt_sha256": _sha_file(receipt_path),
                    "recovered_after_publish": False,
                },
            )
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    result = project_status(root, project_id)
    result["idempotent"] = False
    result["receipt_sha256"] = receipt["record_sha256"]
    return result
