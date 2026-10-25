#!/usr/bin/env python3
"""Deterministic policy for normalized memory candidates."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

SENSITIVE = re.compile(r"\b(plaintext|password|passcode|access[ -]?code|api[ -]?key|secret|token|credential)\b", re.I)
AUTHORITY = {
    "current_source": 4,
    "verified_closeout": 3,
    "validated_lesson": 2,
    "raw_history": 1,
}
REJECTED_STATES = {"invalidated", "obsolete", "retired", "superseded", "failed"}


def apply_policy(query: str, candidates: list[dict], limit: int = 5) -> dict:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query is required")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    if SENSITIVE.search(query):
        return {
            "results": [],
            "abstained": True,
            "reason": "sensitive_query",
            "rejected_count": len(candidates),
            "authority": "retrieval_filter_only",
        }
    accepted = []
    rejected = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            rejected.append({"reason": "invalid_candidate"})
            continue
        state = str(candidate.get("state", "unknown")).lower()
        valid_to = candidate.get("valid_to")
        evidence_class = candidate.get("evidence_class")
        if state in REJECTED_STATES or valid_to:
            rejected.append({"identity": candidate.get("identity"), "reason": "not_current"})
            continue
        if evidence_class not in AUTHORITY:
            rejected.append({"identity": candidate.get("identity"), "reason": "unknown_evidence_class"})
            continue
        if not candidate.get("source_path") or not candidate.get("source_sha256"):
            rejected.append({"identity": candidate.get("identity"), "reason": "missing_provenance"})
            continue
        if not isinstance(candidate.get("text"), str) or SENSITIVE.search(candidate["text"]):
            rejected.append({"identity": candidate.get("identity"), "reason": "unsafe_summary"})
            continue
        try:
            semantic_score = float(candidate.get("semantic_score", 0.0))
        except (TypeError, ValueError):
            semantic_score = float("nan")
        if not math.isfinite(semantic_score):
            rejected.append({"identity": candidate.get("identity"), "reason": "invalid_score"})
            continue
        observed_at = str(candidate.get("observed_at", ""))
        accepted.append((AUTHORITY[evidence_class], observed_at, semantic_score, candidate))
    accepted.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    results = [item[3] for item in accepted[:limit]]
    return {
        "results": results,
        "abstained": not results,
        "reason": "no_current_provenanced_result" if not results else None,
        "rejected_count": len(rejected),
        "rejections": rejected,
        "authority": "retrieval_filter_only",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    rows = []
    for number, line in enumerate(args.input.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not value.get("case_id"):
            raise SystemExit(f"row {number}: case_id is required")
        result = apply_policy(value.get("query", ""), value.get("candidates", []), args.limit)
        rows.append({"case_id": value["case_id"], **result})
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({"cases": len(rows), "output": str(args.output), "authority": "retrieval_filter_only"}, sort_keys=True))


if __name__ == "__main__":
    main()
