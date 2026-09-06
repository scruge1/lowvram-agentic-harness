#!/usr/bin/env python3
"""Compile one reviewed PRD into a lossless, independently reviewed SSOT."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from harness.enforcement import (
    EnforcementError,
    _files,
    _run_verifier,
    validate_contract,
)
from harness.prd import (
    _file_record,
    _read_object,
    _receipt_body,
    _safe_path,
    _target_digest,
    _validate_record,
    _validate_reviewer,
    _write_bytes_new,
)
from harness.project import (
    ProjectError,
    _append_event,
    _canonical,
    _load_intent,
    _project_lock,
    _sha_bytes,
    _sha_file,
    _surface_record,
    _target_root,
    project_status,
)
from ssot.control import SSOTError, _validate_project


SCHEMA_VERSION = 1
FINAL_NAMES = {
    "contract": "compiler-contract.json",
    "seed": "unresolved-seed.json",
    "manifest": "ssot-project.json",
    "verifiers": "verifier-candidates.json",
    "receipt": "compile-receipt.json",
}


def _reviewed_paths(project_dir: Path) -> Tuple[Path, Path, Path]:
    prd_dir = project_dir / "prd"
    return (
        prd_dir / "PRD.md",
        prd_dir / "prd-manifest.json",
        prd_dir / "review-receipt.json",
    )


def _read_reviewed(project_dir: Path) -> Tuple[Path, Dict[str, Any], Path]:
    prd_path, manifest_path, receipt_path = _reviewed_paths(project_dir)
    root = project_dir.parents[2]
    prd = _safe_path(
        root,
        prd_path.relative_to(root).as_posix(),
        "reviewed PRD",
    )
    manifest_path = _safe_path(
        root,
        manifest_path.relative_to(root).as_posix(),
        "reviewed PRD manifest",
    )
    manifest = _read_object(manifest_path, "reviewed PRD manifest")
    _safe_path(
        root,
        receipt_path.relative_to(root).as_posix(),
        "reviewed PRD receipt",
    )
    return prd, manifest, receipt_path


def _expected_requirement(
    root: Path, prd_path: Path, requirement: Dict[str, Any]
) -> Dict[str, Any]:
    locator = requirement["prd_locator"]
    return {
        "id": requirement["id"],
        "text": requirement["text"],
        "source": {
            "path": prd_path.relative_to(root).as_posix(),
            "locator": f"line:{locator['line_start']}-{locator['line_end']}",
            "sha256": _sha_file(prd_path),
        },
        "acceptance_evidence": requirement["acceptance"],
    }


def _build_seed(
    root: Path,
    project_id: str,
    prd_path: Path,
    reviewed_manifest: Dict[str, Any],
) -> Dict[str, Any]:
    requirements = []
    for reviewed in reviewed_manifest["requirements"]:
        expected = _expected_requirement(root, prd_path, reviewed)
        requirements.append(
            {
                **expected,
                "scope_class": "not_yet_understood",
                "disposition": "unresolved",
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "authority_cap": "tested",
        "initialization": {
            "state": "all_unresolved",
            "instruction": (
                "Adjudicate every conserved requirement and promote verifier "
                "candidates through independent review before publication."
            ),
        },
        "target": {"files": [prd_path.relative_to(root).as_posix()]},
        "requirements": requirements,
        "stages": [],
        "acceptance": None,
    }


def _validate_requirement_conservation(
    root: Path,
    candidate: Dict[str, Any],
    prd_path: Path,
    reviewed_manifest: Dict[str, Any],
) -> List[str]:
    requirements = candidate.get("requirements")
    if not isinstance(requirements, list):
        raise ProjectError("SSOT candidate requirements must be a list")
    reviewed = {
        row["id"]: _expected_requirement(root, prd_path, row)
        for row in reviewed_manifest["requirements"]
    }
    identifiers = [row.get("id") for row in requirements if isinstance(row, dict)]
    if len(identifiers) != len(requirements) or len(identifiers) != len(set(identifiers)):
        raise ProjectError("SSOT candidate requirement ids are missing or duplicated")
    if set(identifiers) != set(reviewed):
        missing = sorted(set(reviewed) - set(identifiers))
        extra = sorted(set(identifiers) - set(reviewed))
        raise ProjectError(
            f"SSOT requirement coverage mismatch; missing={missing}, extra={extra}"
        )
    stage_map = {stage["id"]: stage for stage in candidate.get("stages", [])}
    for row in requirements:
        expected = reviewed[row["id"]]
        for field in ("text", "source", "acceptance_evidence"):
            if row.get(field) != expected[field]:
                raise ProjectError(f"{row['id']} does not conserve reviewed {field}")
        if row.get("disposition") != "applicable":
            raise ProjectError(f"{row['id']} must be explicitly applicable")
        owner = row.get("owner_stage")
        if owner not in stage_map:
            raise ProjectError(f"{row['id']} has no valid owner stage")
        properties = stage_map[owner].get("properties", [])
        if not set(expected["acceptance_evidence"]) <= set(properties):
            raise ProjectError(
                f"{row['id']} acceptance evidence is not bound to owner-stage properties"
            )
    return [row["id"] for row in reviewed_manifest["requirements"]]


def _action_rows(root: Path, candidate: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    required = {
        "kind",
        "producer",
        "verifier_owner",
        "contract",
        "contract_sha256",
        "receipt_output",
        "usage_mode",
        "effects",
        "runtime_profile",
        "runtime_profile_sha256",
    }
    for stage in candidate["stages"]:
        action = stage.get("action")
        if not isinstance(action, dict) or set(action) != required:
            raise ProjectError(f"{stage['id']}.action fields do not match schema version 1")
        if action.get("kind") != "harness.enforcement":
            raise ProjectError(f"{stage['id']}.action must use harness.enforcement")
        if action.get("usage_mode") not in {"script_no_model", "host_metered"}:
            raise ProjectError(
                f"{stage['id']}.action.usage_mode must be script_no_model or host_metered"
            )
        runtime_record = None
        if action["usage_mode"] == "script_no_model":
            if (
                action.get("runtime_profile") is not None
                or action.get("runtime_profile_sha256") is not None
            ):
                raise ProjectError(
                    f"{stage['id']} script action cannot claim a runtime profile"
                )
        else:
            runtime_path = _safe_path(
                root, action.get("runtime_profile"), f"{stage['id']} runtime profile"
            )
            if action.get("runtime_profile_sha256") != _sha_file(runtime_path):
                raise ProjectError(f"{stage['id']} runtime profile hash changed")
            runtime_record = _file_record(root, runtime_path)
        effects = action.get("effects")
        if (
            not isinstance(effects, list)
            or len(effects) != len(set(effects))
            or not all(isinstance(item, str) and item.strip() for item in effects)
        ):
            raise ProjectError(f"{stage['id']}.action.effects must be unique strings")
        producer = action.get("producer")
        verifier_owner = action.get("verifier_owner")
        if not isinstance(producer, str) or not producer.strip():
            raise ProjectError(f"{stage['id']}.action.producer is required")
        if not isinstance(verifier_owner, str) or not verifier_owner.strip():
            raise ProjectError(f"{stage['id']}.action.verifier_owner is required")
        if producer.casefold() == verifier_owner.casefold():
            raise ProjectError(f"{stage['id']} action producer and verifier must differ")
        contract_path = _safe_path(
            root, action.get("contract"), f"{stage['id']} enforcement contract"
        )
        if action.get("contract_sha256") != _sha_file(contract_path):
            raise ProjectError(f"{stage['id']} enforcement contract hash changed")
        try:
            contract = validate_contract(
                root, _read_object(contract_path, f"{stage['id']} enforcement contract")
            )
        except EnforcementError as exc:
            raise ProjectError(f"{stage['id']} enforcement contract is invalid: {exc}") from exc
        stage_outputs = set(stage["outputs"])
        if not set(contract["outputs"]) < stage_outputs:
            raise ProjectError(
                f"{stage['id']} stage outputs must include task outputs plus controller evidence"
            )
        if action.get("receipt_output") != contract["receipt_output"]:
            raise ProjectError(f"{stage['id']} action receipt does not match task contract")
        required_outputs = {contract["receipt_output"]}
        research = contract["research"]
        if research["required"]:
            required_outputs.add(research["receipt_output"])
        trace_output = stage.get("trace_output")
        if not isinstance(trace_output, str) or not trace_output:
            raise ProjectError(f"{stage['id']}.trace_output is required")
        required_outputs.add(trace_output)
        if not required_outputs <= stage_outputs:
            raise ProjectError(
                f"{stage['id']} outputs omit enforcement receipt, research receipt, or trace"
            )
        names = set(contract["worker"]["files"])
        names.update(contract["verifier"]["files"])
        names.update(contract["verifier"]["negative_control"]["files"])
        if research["required"]:
            names.update(research["files"])
        rows.append(
            {
                "stage_id": stage["id"],
                "kind": action["kind"],
                "producer": producer,
                "verifier_owner": verifier_owner,
                "contract": _file_record(root, contract_path),
                "receipt_output": contract["receipt_output"],
                "usage_mode": action["usage_mode"],
                "effects": effects,
                "runtime_profile": runtime_record,
                "task_outputs": contract["outputs"],
                "trace_output": trace_output,
                "control_files": [
                    _file_record(root, _safe_path(root, name, "action control file"))
                    for name in sorted(names)
                ],
            }
        )
    return rows


def _verifier_rows(root: Path, candidate: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    contracts = []
    for stage in candidate["stages"]:
        contracts.append((f"stage:{stage['id']}", stage["verifier"]))
        action = stage["action"]
        action_contract = validate_contract(
            root,
            _read_object(
                _safe_path(root, action["contract"], "action verifier contract"),
                "action verifier contract",
            ),
        )
        contracts.append(
            (
                f"action:{stage['id']}",
                {**action_contract["verifier"], "owner": action["verifier_owner"]},
            )
        )
    contracts.append(("acceptance", candidate["acceptance"]))
    for scope, verifier in contracts:
        names = sorted(
            set(verifier.get("files", []))
            | set(verifier.get("negative_control", {}).get("files", []))
        )
        rows.append(
            {
                "scope": scope,
                "owner": verifier["owner"],
                "argv": verifier["argv"],
                "negative_control_argv": verifier["negative_control"]["argv"],
                "files": [_file_record(root, _safe_path(root, name, "verifier file")) for name in names],
            }
        )
    return rows


def _validate_verifier_candidates(
    root: Path,
    value: Dict[str, Any],
    project_id: str,
    compiler: str,
    candidate_hash: str,
    expected_rows: List[Dict[str, Any]],
) -> List[str]:
    required = {
        "schema_version",
        "project_id",
        "status",
        "generated_by",
        "candidate_manifest_sha256",
        "verifiers",
    }
    if set(value) != required or value.get("schema_version") != SCHEMA_VERSION:
        raise ProjectError("verifier candidate fields do not match schema version 1")
    if value.get("project_id") != project_id:
        raise ProjectError("verifier candidate project_id mismatch")
    if value.get("status") != "untrusted_drafts":
        raise ProjectError("verifier candidates must enter as untrusted_drafts")
    if value.get("generated_by") != compiler:
        raise ProjectError("verifier candidate generator must match compiler_identity")
    if value.get("candidate_manifest_sha256") != candidate_hash:
        raise ProjectError("verifier candidates do not bind the exact SSOT candidate")
    if value.get("verifiers") != expected_rows:
        raise ProjectError("verifier candidates do not exactly bind every verifier")
    scopes = [row["scope"] for row in expected_rows]
    if len(scopes) != len(set(scopes)):
        raise ProjectError("verifier candidate scopes are duplicated")
    for index, row in enumerate(expected_rows):
        for file_index, record in enumerate(row["files"]):
            _validate_record(root, record, f"verifier candidate {index} file {file_index}")
    return scopes


def _parse_reviewer_output(output: str, label: str) -> Dict[str, Any]:
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ProjectError(f"{label} did not return one JSON object") from exc
    if not isinstance(value, dict):
        raise ProjectError(f"{label} did not return one JSON object")
    return value


def _run_compile_review(
    root: Path,
    reviewer: Dict[str, Any],
    *,
    project_id: str,
    intent_sha256: str,
    review_receipt: Path,
    candidate: Path,
    verifier_candidates: Path,
    requirement_ids: List[str],
    verifier_scopes: List[str],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    values = {
        "project_id": project_id,
        "intent_sha256": intent_sha256,
        "review_receipt": str(review_receipt),
        "review_receipt_sha256": _sha_file(review_receipt),
        "manifest": str(candidate),
        "manifest_sha256": _sha_file(candidate),
        "verifier_candidates": str(verifier_candidates),
        "verifier_candidates_sha256": _sha_file(verifier_candidates),
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
        raise ProjectError(f"independent SSOT review failed: {exc}") from exc
    if before != _target_digest(root):
        raise ProjectError("independent SSOT reviewer changed target files")
    negative_value = _parse_reviewer_output(
        negative["stdout"], "SSOT reviewer negative control"
    )
    if negative_value != {
        "verdict": "negative_control_pass",
        "reviewer_identity": reviewer["owner"],
    }:
        raise ProjectError("SSOT reviewer negative control did not prove rejection")
    if positive["exit_code"] != 0:
        detail = positive["stderr"] or positive["stdout"] or "no diagnostic"
        raise ProjectError(f"independent SSOT reviewer rejected candidate: {detail[-1000:]}")
    expected = {
        "verdict": "approved",
        "reviewer_identity": reviewer["owner"],
        "project_id": project_id,
        "intent_sha256": intent_sha256,
        "review_receipt_sha256": values["review_receipt_sha256"],
        "manifest_sha256": values["manifest_sha256"],
        "verifier_candidates_sha256": values["verifier_candidates_sha256"],
        "requirement_ids": requirement_ids,
        "verifier_scopes": verifier_scopes,
    }
    if _parse_reviewer_output(positive["stdout"], "independent SSOT reviewer") != expected:
        raise ProjectError("independent reviewer output does not bind the exact SSOT")
    return negative, positive


def _assert_unchanged(records: Iterable[Dict[str, Any]], root: Path) -> None:
    for index, record in enumerate(records):
        _validate_record(root, record, f"compiler input {index}")


def _build_stage(
    project_dir: Path,
    contract_path: Path,
    seed: Dict[str, Any],
    manifest_path: Path,
    verifier_path: Path,
    receipt: Dict[str, Any],
) -> Path:
    stage = project_dir / f".ssot-stage-{uuid.uuid4().hex}"
    stage.mkdir(parents=False, exist_ok=False)
    _write_bytes_new(stage / FINAL_NAMES["contract"], contract_path.read_bytes())
    _write_bytes_new(
        stage / FINAL_NAMES["seed"],
        json.dumps(seed, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n",
    )
    _write_bytes_new(stage / FINAL_NAMES["manifest"], manifest_path.read_bytes())
    _write_bytes_new(stage / FINAL_NAMES["verifiers"], verifier_path.read_bytes())
    _write_bytes_new(
        stage / FINAL_NAMES["receipt"],
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n",
    )
    return stage


def _artifact_paths(project_dir: Path) -> Dict[str, Path]:
    directory = project_dir / "ssot"
    return {name: directory / filename for name, filename in FINAL_NAMES.items()}


def _verify_compile_receipt_at(
    root: Path,
    project_dir: Path,
    intent: Dict[str, Any],
    intent_sha256: str,
    receipt_path: Path,
) -> Dict[str, Any]:
    paths = _artifact_paths(project_dir)
    if receipt_path != paths["receipt"]:
        raise ProjectError("compile receipt path is not canonical")
    receipt = _read_object(receipt_path, "compile receipt")
    if receipt.get("record_sha256") != _sha_bytes(_canonical(_receipt_body(receipt))):
        raise ProjectError("compile receipt self-hash is invalid")
    if (
        receipt.get("schema_version") != SCHEMA_VERSION
        or receipt.get("receipt_type") != "compiled_ssot"
        or receipt.get("status") != "compiled"
        or receipt.get("authority_cap") != "compiled_ssot_only_no_execution"
        or receipt.get("project_id") != intent["project_id"]
        or receipt.get("intent_sha256") != intent_sha256
    ):
        raise ProjectError("compile receipt identity or authority is invalid")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(FINAL_NAMES) - {"receipt"}:
        raise ProjectError("compile receipt artifact set is invalid")
    for name, record in artifacts.items():
        path = _validate_record(root, record, f"compiled {name}")
        if path != paths[name]:
            raise ProjectError(f"compiled {name} path is not canonical")
    root_manifest = _validate_record(root, receipt.get("root_manifest"), "root SSOT")
    if root_manifest != root / "ssot-project.json":
        raise ProjectError("compile receipt does not bind the root SSOT")
    if _sha_file(paths["manifest"]) != _sha_file(root_manifest):
        raise ProjectError("root SSOT differs from the reviewed compiled manifest")
    candidate = _read_object(root_manifest, "root SSOT")
    try:
        _validate_project(candidate, root)
    except SSOTError as exc:
        raise ProjectError(f"compiled SSOT is no longer valid: {exc}") from exc
    prd_path, reviewed_manifest, review_receipt = _read_reviewed(project_dir)
    if receipt.get("review_receipt_sha256") != _sha_file(review_receipt):
        raise ProjectError("compile receipt reviewed-PRD binding changed")
    requirement_ids = _validate_requirement_conservation(
        root, candidate, prd_path, reviewed_manifest
    )
    action_rows = _action_rows(root, candidate)
    verifiers = _read_object(paths["verifiers"], "compiled verifier candidates")
    compiler = receipt.get("compiler_identity")
    if not isinstance(compiler, str) or not compiler.strip():
        raise ProjectError("compile receipt compiler identity is invalid")
    scopes = _validate_verifier_candidates(
        root,
        verifiers,
        intent["project_id"],
        compiler,
        _sha_file(paths["manifest"]),
        _verifier_rows(root, candidate),
    )
    if (
        receipt.get("requirement_ids") != requirement_ids
        or receipt.get("verifier_scopes") != scopes
        or receipt.get("actions") != action_rows
    ):
        raise ProjectError("compile receipt coverage changed")
    reviewer = receipt.get("reviewer")
    if not isinstance(reviewer, dict) or not isinstance(reviewer.get("files"), list):
        raise ProjectError("compile receipt reviewer pins are invalid")
    for index, record in enumerate(reviewer["files"]):
        _validate_record(root, record, f"compile reviewer file {index}")
    return receipt


def verify_compile_event(
    root: Path,
    project_dir: Path,
    intent: Dict[str, Any],
    intent_sha256: str,
    event: Dict[str, Any],
) -> Dict[str, Any]:
    details = event.get("details")
    if not isinstance(details, dict) or set(details) != {
        "receipt_path",
        "receipt_sha256",
        "recovered_after_publish",
    }:
        raise ProjectError("SSOT compile event details are invalid")
    receipt_path = _safe_path(root, details.get("receipt_path"), "compile receipt")
    if details.get("receipt_sha256") != _sha_file(receipt_path):
        raise ProjectError("SSOT compile event receipt hash mismatch")
    return _verify_compile_receipt_at(
        root, project_dir, intent, intent_sha256, receipt_path
    )


def _recover_root_manifest(
    root: Path,
    project_dir: Path,
    intent: Dict[str, Any],
    intent_sha256: str,
) -> None:
    """Finish an interrupted absent-only publication from its complete checkpoint."""
    paths = _artifact_paths(project_dir)
    receipt = _read_object(paths["receipt"], "interrupted compile receipt")
    if receipt.get("record_sha256") != _sha_bytes(_canonical(_receipt_body(receipt))):
        raise ProjectError("interrupted compile receipt self-hash is invalid")
    if (
        receipt.get("project_id") != intent["project_id"]
        or receipt.get("intent_sha256") != intent_sha256
        or receipt.get("publication_mode") != "new_project_pending"
    ):
        raise ProjectError("interrupted compile receipt identity is invalid")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict) or "manifest" not in artifacts:
        raise ProjectError("interrupted compile receipt has no manifest")
    checkpoint = _validate_record(
        root, artifacts["manifest"], "interrupted compiled manifest"
    )
    if checkpoint != paths["manifest"]:
        raise ProjectError("interrupted compiled manifest path is not canonical")
    root_record = receipt.get("root_manifest")
    expected = {
        "path": "ssot-project.json",
        "exists": True,
        "size": checkpoint.stat().st_size,
        "sha256": _sha_file(checkpoint),
    }
    if root_record != expected:
        raise ProjectError("interrupted compile root-manifest record is invalid")
    root_manifest = root / "ssot-project.json"
    if os.path.lexists(root_manifest):
        raise ProjectError("refusing to replace a root SSOT during recovery")
    candidate = _read_object(checkpoint, "interrupted compiled manifest")
    try:
        _validate_project(candidate, root)
    except SSOTError as exc:
        raise ProjectError(f"interrupted compiled SSOT is invalid: {exc}") from exc
    _write_bytes_new(root_manifest, checkpoint.read_bytes())


def compile_ssot(root: Path, project_id: str, contract_file: Path) -> Dict[str, Any]:
    """Admit and publish one lossless SSOT without executing project work."""
    root = _target_root(root)
    project_dir, intent_path, intent = _load_intent(root, project_id)
    intent_sha256 = _sha_file(intent_path)
    status = project_status(root, project_id)
    final_dir = project_dir / "ssot"
    paths = _artifact_paths(project_dir)
    if status["state"] in {
        "configured",
        "running",
        "held_execution",
        "held_budget_exhausted",
        "failed",
        "verified",
        "tested",
    }:
        receipt = _verify_compile_receipt_at(
            root, project_dir, intent, intent_sha256, paths["receipt"]
        )
        status["idempotent"] = True
        status["receipt_sha256"] = receipt["record_sha256"]
        return status
    if status["state"] != "prd_reviewed":
        raise ProjectError(f"project is not ready for SSOT compilation: {status['state']}")
    if os.path.lexists(final_dir):
        with _project_lock(root, project_id):
            if not os.path.lexists(root / "ssot-project.json"):
                _recover_root_manifest(root, project_dir, intent, intent_sha256)
            receipt = _verify_compile_receipt_at(
                root, project_dir, intent, intent_sha256, paths["receipt"]
            )
            _append_event(
                project_dir,
                intent_sha256,
                "ssot_compiled",
                {
                    "receipt_path": paths["receipt"].relative_to(root).as_posix(),
                    "receipt_sha256": _sha_file(paths["receipt"]),
                    "recovered_after_publish": True,
                },
            )
        result = project_status(root, project_id)
        result["idempotent"] = True
        result["receipt_sha256"] = receipt["record_sha256"]
        return result

    unresolved = contract_file if contract_file.is_absolute() else root / contract_file
    try:
        relative = unresolved.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise ProjectError("SSOT compiler contract escapes target root") from exc
    contract_path = _safe_path(root, relative, "SSOT compiler contract")
    contract = _read_object(contract_path, "SSOT compiler contract")
    required = {
        "schema_version",
        "project_id",
        "compiler_identity",
        "manifest_path",
        "verifier_candidates_path",
        "reviewer",
    }
    if set(contract) != required or contract.get("schema_version") != SCHEMA_VERSION:
        raise ProjectError("SSOT compiler contract fields do not match schema version 1")
    if contract.get("project_id") != project_id:
        raise ProjectError("SSOT compiler contract project_id mismatch")
    compiler = contract.get("compiler_identity")
    if not isinstance(compiler, str) or not compiler.strip():
        raise ProjectError("compiler_identity is required")
    manifest_path = _safe_path(root, contract.get("manifest_path"), "SSOT candidate")
    verifier_path = _safe_path(
        root, contract.get("verifier_candidates_path"), "verifier candidates"
    )
    if len({contract_path, manifest_path, verifier_path}) != 3:
        raise ProjectError("SSOT compiler inputs must be separate files")
    candidate = _read_object(manifest_path, "SSOT candidate")
    if candidate.get("project_id") != project_id:
        raise ProjectError("SSOT candidate project_id mismatch")
    try:
        _validate_project(candidate, root)
    except SSOTError as exc:
        raise ProjectError(f"SSOT candidate is invalid: {exc}") from exc
    prd_path, reviewed_manifest, review_receipt = _read_reviewed(project_dir)
    requirement_ids = _validate_requirement_conservation(
        root, candidate, prd_path, reviewed_manifest
    )
    action_rows = _action_rows(root, candidate)
    seed = _build_seed(root, project_id, prd_path, reviewed_manifest)
    verifier_value = _read_object(verifier_path, "verifier candidates")
    verifier_scopes = _validate_verifier_candidates(
        root,
        verifier_value,
        project_id,
        compiler,
        _sha_file(manifest_path),
        _verifier_rows(root, candidate),
    )
    reviewer = _validate_reviewer(root, contract.get("reviewer"), compiler, compiler)
    if reviewer["owner"].casefold() == compiler.casefold():
        raise ProjectError("SSOT reviewer must differ from compiler_identity")
    verifier_owners = {row["owner"].casefold() for row in verifier_value["verifiers"]}
    if reviewer["owner"].casefold() in verifier_owners:
        raise ProjectError("SSOT reviewer must differ from verifier owners")
    reviewer_files = _files(root, reviewer["all_files"], require=True)
    verifier_files = [
        record
        for row in verifier_value["verifiers"]
        for record in row["files"]
    ]
    action_files = [
        row["contract"]
        for row in action_rows
    ] + [
        record for row in action_rows for record in row["control_files"]
    ]
    pinned_inputs = [
        _file_record(root, path)
        for path in (
            contract_path,
            manifest_path,
            verifier_path,
            review_receipt,
            prd_path,
            project_dir / "prd" / "prd-manifest.json",
        )
    ] + reviewer_files + verifier_files + action_files
    negative, positive = _run_compile_review(
        root,
        reviewer,
        project_id=project_id,
        intent_sha256=intent_sha256,
        review_receipt=review_receipt,
        candidate=manifest_path,
        verifier_candidates=verifier_path,
        requirement_ids=requirement_ids,
        verifier_scopes=verifier_scopes,
    )
    _assert_unchanged(pinned_inputs, root)
    artifact_records = {
        name: {
            "path": (final_dir / FINAL_NAMES[name]).relative_to(root).as_posix(),
            "size": source.stat().st_size,
            "sha256": _sha_file(source),
        }
        for name, source in {
            "contract": contract_path,
            "manifest": manifest_path,
            "verifiers": verifier_path,
        }.items()
    }
    seed_bytes = json.dumps(
        seed, indent=2, sort_keys=True, ensure_ascii=False
    ).encode("utf-8") + b"\n"
    artifact_records["seed"] = {
        "path": (final_dir / FINAL_NAMES["seed"]).relative_to(root).as_posix(),
        "size": len(seed_bytes),
        "sha256": _sha_bytes(seed_bytes),
    }
    publication_mode = intent["ssot"]["mode"]
    root_manifest = root / "ssot-project.json"
    if publication_mode == "reuse_existing":
        if root_manifest != manifest_path or intent["ssot"].get("manifest_sha256") != _sha_file(root_manifest):
            raise ProjectError("existing SSOT reuse must compile the unchanged root manifest")
    elif publication_mode == "new_project_pending":
        if os.path.lexists(root_manifest):
            raise ProjectError("refusing to overwrite an SSOT that appeared after activation")
    else:
        raise ProjectError(f"unsupported SSOT publication mode: {publication_mode}")
    root_record = {
        "path": "ssot-project.json",
        "exists": True,
        "size": manifest_path.stat().st_size,
        "sha256": _sha_file(manifest_path),
    }
    receipt_body = {
        "schema_version": SCHEMA_VERSION,
        "receipt_type": "compiled_ssot",
        "status": "compiled",
        "authority_cap": "compiled_ssot_only_no_execution",
        "project_id": project_id,
        "intent_sha256": intent_sha256,
        "compiler_identity": compiler,
        "publication_mode": publication_mode,
        "review_receipt_sha256": _sha_file(review_receipt),
        "requirement_ids": requirement_ids,
        "verifier_scopes": verifier_scopes,
        "actions": action_rows,
        "artifacts": artifact_records,
        "root_manifest": root_record,
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
    receipt = {**receipt_body, "record_sha256": _sha_bytes(_canonical(receipt_body))}
    stage = _build_stage(
        project_dir, contract_path, seed, manifest_path, verifier_path, receipt
    )
    try:
        with _project_lock(root, project_id):
            _assert_unchanged(pinned_inputs, root)
            current = project_status(root, project_id)
            if current["state"] != "prd_reviewed":
                raise ProjectError(
                    f"project state changed before SSOT publication: {current['state']}"
                )
            if os.path.lexists(final_dir):
                raise ProjectError("canonical SSOT checkpoint appeared during review")
            if publication_mode == "new_project_pending" and os.path.lexists(root_manifest):
                raise ProjectError("root SSOT appeared during review")
            os.replace(stage, final_dir)
            if publication_mode == "new_project_pending":
                _write_bytes_new(root_manifest, paths["manifest"].read_bytes())
            if _surface_record(root, "ssot-project.json") != root_record:
                raise ProjectError("published root SSOT does not match compile receipt")
            _append_event(
                project_dir,
                intent_sha256,
                "ssot_compiled",
                {
                    "receipt_path": paths["receipt"].relative_to(root).as_posix(),
                    "receipt_sha256": _sha_file(paths["receipt"]),
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
