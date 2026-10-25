#!/usr/bin/env python3
"""Bind MemPalace search results to reviewed, source-bound atomic claims.

Derived from reviewed parent SHA-256
fccc72f4dafa6d8da1e49860d27936ab8c81742ccf9bb46d9fc602606152957a.
The registry is external reviewed input; no personal registry ships here.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from memory_retrieval_policy import apply_policy

JSON_FD = os.dup(1)
HASH = re.compile(r"^[a-f0-9]{64}$")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalized_text(value: str) -> str:
    return " ".join(value.split())


def claim_sha256(value: str) -> str:
    return sha256_bytes(normalized_text(value).encode("utf-8"))


def emit_json(value: dict) -> None:
    os.write(JSON_FD, (json.dumps(value, sort_keys=True) + "\n").encode("utf-8"))


def drawer_source_path(drawer_id: str) -> str:
    return f"mempalace://drawer/{drawer_id}"


def resolve_search_sources(search_result: dict, drawers: list[dict]) -> dict:
    """Add stable drawer provenance only when all available fields match exactly."""
    by_identity: dict[tuple[str, str, str, str], list[dict]] = {}
    for drawer in drawers:
        content = drawer.get("content")
        drawer_id = drawer.get("drawer_id")
        if not isinstance(content, str) or not isinstance(drawer_id, str):
            continue
        metadata = drawer.get("metadata") or {}
        identity = (
            str(drawer.get("wing", "")),
            str(drawer.get("room", "")),
            str(metadata.get("filed_at", "")),
            claim_sha256(content),
        )
        by_identity.setdefault(identity, []).append(drawer)
    resolved = dict(search_result)
    resolved_results = []
    for result in search_result.get("results", []):
        item = dict(result)
        source = item.get("source_path", "")
        if isinstance(source, str) and source.startswith("mempalace://drawer/"):
            # Search metadata cannot vouch for its own old drawer hash.
            item["source_sha256"] = None
            matches = [drawer for drawer in drawers
                       if drawer_source_path(str(drawer.get("drawer_id", ""))) == source
                       and isinstance(drawer.get("content"), str)
                       and claim_sha256(drawer["content"]) == claim_sha256(str(item.get("text", "")))]
            if len(matches) == 1:
                item["source_sha256"] = sha256_bytes(matches[0]["content"].encode("utf-8"))
        if not item.get("source_path") and isinstance(item.get("text"), str):
            identity = (
                str(item.get("wing", "")),
                str(item.get("room", "")),
                str(item.get("created_at", "")),
                claim_sha256(item["text"]),
            )
            matches = by_identity.get(identity, [])
            if len(matches) == 1:
                drawer = matches[0]
                item["source_path"] = drawer_source_path(drawer["drawer_id"])
                item["source_sha256"] = sha256_bytes(drawer["content"].encode("utf-8"))
                item["drawer_id"] = drawer["drawer_id"]
        resolved_results.append(item)
    resolved["results"] = resolved_results
    return resolved


def load_claim_registry(path: Path) -> dict[tuple[str, str], dict]:
    records: dict[tuple[str, str], dict] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record, dict):
            raise ValueError(f"registry row {number} must be an object")
        required = {
            "claim_sha256",
            "source_path",
            "source_sha256",
            "safe_text",
            "safe_text_sha256",
            "state",
            "evidence_class",
            "observed_at",
        }
        missing = sorted(required - set(record))
        if missing:
            raise ValueError(f"registry row {number} missing: {', '.join(missing)}")
        if any(not isinstance(record.get(key), str) or not HASH.fullmatch(record[key])
               for key in ("claim_sha256", "source_sha256", "safe_text_sha256")):
            raise ValueError(f"registry row {number} has an invalid hash")
        if not isinstance(record["source_path"], str) or not record["source_path"]:
            raise ValueError(f"registry row {number} source_path is required")
        if not isinstance(record["safe_text"], str) or not record["safe_text"].strip():
            raise ValueError(f"registry row {number} safe_text is required")
        if sha256_bytes(record["safe_text"].encode("utf-8")) != record["safe_text_sha256"]:
            raise ValueError(f"registry row {number} safe_text hash mismatch")
        key = (record["source_path"], record["claim_sha256"])
        if key in records:
            raise ValueError(f"duplicate registry identity at row {number}")
        records[key] = record
    return records


def bind_candidates(search_result: dict, registry: dict[tuple[str, str], dict]) -> list[dict]:
    bound = []
    for rank, result in enumerate(search_result.get("results", []), 1):
        text = result.get("text")
        source_path = result.get("source_path")
        if not isinstance(text, str) or not isinstance(source_path, str):
            continue
        digest = claim_sha256(text)
        record = registry.get((source_path, digest))
        if record is None:
            bound.append(
                {
                    "identity": f"unbound:{rank}:{digest}",
                    "state": "unknown",
                    "evidence_class": "unknown",
                    "semantic_score": result.get("similarity", 0.0),
                }
            )
            continue
        observed_source_sha = result.get("source_sha256")
        if source_path and not source_path.startswith("mempalace://"):
            try:
                current_source_sha = sha256_bytes(Path(source_path).read_bytes())
                observed_source_sha = current_source_sha if not observed_source_sha or observed_source_sha == current_source_sha else None
            except OSError:
                observed_source_sha = None
        if observed_source_sha != record["source_sha256"]:
            bound.append(
                {
                    "identity": record.get("claim_id", digest),
                    "state": "unknown",
                    "evidence_class": "unknown",
                    "semantic_score": result.get("similarity", 0.0),
                }
            )
            continue
        candidate = {
            "identity": record.get("claim_id", digest),
            "text": record["safe_text"],
            "claim_sha256": digest,
            "source_path": source_path,
            "source_sha256": record["source_sha256"],
            "state": record["state"],
            "valid_to": record.get("valid_to"),
            "evidence_class": record["evidence_class"],
            "observed_at": record["observed_at"],
            "semantic_score": result.get("similarity", 0.0),
            "matched_via": result.get("matched_via"),
            "registry_receipt_sha256": record.get("registry_receipt_sha256"),
        }
        bound.append(candidate)
    return bound


def live_search(query: str, limit: int) -> dict:
    palace = os.environ.get("MEMPALACE_PALACE_PATH", "")
    config = os.environ.get("MEMPALACE_CONFIG_DIR", "")
    if not palace or not Path(palace).is_absolute() or not Path(palace).is_dir():
        raise ValueError("MEMPALACE_PALACE_PATH must name the explicit existing palace directory")
    if not config or not Path(config).is_absolute() or not Path(config).is_dir():
        raise ValueError("MEMPALACE_CONFIG_DIR must name the explicit existing configuration directory")
    # Set the exact target before MemPalace can resolve an ambient default.
    os.environ["MEMPALACE_PALACE_PATH"] = str(Path(palace).resolve(strict=True))
    os.environ["MEMPALACE_CONFIG_DIR"] = str(Path(config).resolve(strict=True))
    with contextlib.redirect_stdout(sys.stderr):
        from mempalace.mcp_server import tool_get_drawer, tool_list_drawers, tool_search
        search_result = tool_search(query, limit=limit)
    if not isinstance(search_result, dict) or "error" in search_result or not isinstance(search_result.get("results"), list):
        raise ValueError("MemPalace did not return a successful search result")
    if len(search_result["results"]) > limit:
        raise ValueError("MemPalace search exceeded the requested result bound")
    drawers = []
    for item in search_result["results"]:
        source = item.get("source_path", "")
        if isinstance(source, str) and source.startswith("mempalace://drawer/"):
            with contextlib.redirect_stdout(sys.stderr):
                drawers.append(tool_get_drawer(source.removeprefix("mempalace://drawer/")))
    scopes = sorted(
        {
            (str(item.get("wing", "")), str(item.get("room", "")))
            for item in search_result.get("results", [])
            if not item.get("source_path")
        }
    )
    for wing, room in scopes:
        with contextlib.redirect_stdout(sys.stderr):
            listing = tool_list_drawers(wing=wing or None, room=room or None, limit=100)
            for item in listing.get("drawers", []):
                drawers.append(tool_get_drawer(item["drawer_id"]))
    return resolve_search_sources(search_result, drawers)


def live_validated_query(query: str, registry: dict[tuple[str, str], dict], limit: int = 5) -> dict:
    preflight = apply_policy(query, [], limit)
    if preflight.get("reason") == "sensitive_query":
        preflight.update(
            {
                "schema": "validated-memory-query/v1",
                "raw_result_count": 0,
                "bound_result_count": 0,
                "authority": "verified_retrieval_only",
            }
        )
        return preflight
    if not registry:
        preflight.update({"schema": "validated-memory-query/v1", "raw_result_count": 0,
                          "bound_result_count": 0, "authority": "verified_retrieval_only"})
        return preflight
    return validated_query(query, live_search(query, max(limit * 4, 20)), registry, limit)


def validated_query(query: str, search_result: dict, registry: dict[tuple[str, str], dict], limit: int = 5) -> dict:
    preflight = apply_policy(query, [], limit)
    if preflight.get("reason") == "sensitive_query":
        preflight.update({"schema": "validated-memory-query/v1", "raw_result_count": 0,
                          "bound_result_count": 0, "authority": "verified_retrieval_only"})
        return preflight
    candidates = bind_candidates(search_result, registry)
    result = apply_policy(query, candidates, limit)
    result.update(
        {
            "schema": "validated-memory-query/v1",
            "raw_result_count": len(search_result.get("results", [])),
            "bound_result_count": sum(not str(c.get("identity", "")).startswith("unbound:") for c in candidates),
            "authority": "verified_retrieval_only",
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--search-result", type=Path)
    source.add_argument("--live", action="store_true")
    parser.add_argument("--claim-registry", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    preflight = apply_policy(args.query, [], args.limit)
    if preflight.get("reason") == "sensitive_query":
        result = validated_query(args.query, {}, {}, args.limit)
    elif args.live:
        registry = load_claim_registry(args.claim_registry)
        result = live_validated_query(args.query, registry, args.limit)
    else:
        registry = load_claim_registry(args.claim_registry)
        search_result = json.loads(args.search_result.read_text(encoding="utf-8-sig"))
        result = validated_query(args.query, search_result, registry, args.limit)
    if args.output:
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(args.output)
        emit_json({"output": str(args.output), "results": len(result["results"]), "abstained": result["abstained"]})
    else:
        emit_json(result)


if __name__ == "__main__":
    main()
