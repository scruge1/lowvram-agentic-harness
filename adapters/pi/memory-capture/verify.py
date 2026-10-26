"""Read back captured exports against their source catalog and native chunk coverage."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from capture import absolute_path, _bounded_json, catalog_signature, coverage_complete, export_path, STATUS_CATALOG_BYTES


def verify(state: Path, palace: Path) -> dict:
    from mempalace.config import MempalaceConfig
    from mempalace.miner import chunk_text, NORMALIZE_VERSION
    from mempalace.palace import get_collection, get_closets_collection

    state = state.resolve(strict=True)
    palace = palace.resolve(strict=True)
    catalog = json.loads((state / "sources.json").read_text())
    if not isinstance(catalog, dict):
        raise ValueError("Captured source catalog must be an object")
    latest_file = state / "latest.json"
    latest, _ = _bounded_json(latest_file, STATUS_CATALOG_BYTES) if latest_file.exists() or latest_file.is_symlink() else ({}, None)
    if not isinstance(latest, dict):
        raise ValueError("Capture latest receipt must be an object")
    receipts = latest.get("source_receipts", {})
    if not isinstance(receipts, dict):
        raise ValueError("Invalid captured source receipt map")
    config = MempalaceConfig()
    drawers = get_collection(str(palace), create=False, read_only=True)
    closets = get_closets_collection(str(palace), create=False, read_only=True)
    exports = state / "exports"
    source_catalog = []
    for source, supplied_signature in sorted(catalog.items()):
        signature = catalog_signature(supplied_signature)
        receipt = receipts.get(source)
        matched = isinstance(receipt, dict) and catalog_signature(receipt) == signature
        prefix = receipt.get("raw_prefix") if matched else None
        exported = receipt.get("export") if matched else None
        if matched and (prefix is None or not isinstance(exported, dict)
                        or not isinstance(exported.get("sha256"), str)
                        or re.fullmatch("[a-f0-9]{64}", exported["sha256"]) is None):
            raise ValueError("Invalid captured export receipt")
        if prefix is not None and (not isinstance(prefix, dict)
                                   or type(prefix.get("bytes")) is not int or not 0 <= prefix["bytes"] <= signature[0]
                                   or not isinstance(prefix.get("sha256"), str)
                                   or re.fullmatch("[a-f0-9]{64}", prefix["sha256"]) is None):
            raise ValueError("Invalid captured source-prefix receipt")
        if (
            not isinstance(source, str)
            or not Path(source).is_absolute()
            or not isinstance(signature, list)
            or len(signature) != 2
            or any(type(item) is not int or item < 0 for item in signature)
        ):
            raise ValueError("Invalid captured source identity or signature")
        expected = export_path(Path(source), exports)
        source_catalog.append(
            {
                "source": source,
                "signature": signature,
                "export": expected.name,
                "export_present": expected.is_file(),
                "raw_prefix_receipt": {"sha256": prefix["sha256"], "bytes": prefix["bytes"]} if prefix is not None else None,
                "source_provenance": "capture_time_prefix_only" if matched else "legacy_or_mismatched_receipt_unverifiable",
                "receipt_known": isinstance(receipt, dict),
                "receipt_matches_catalog": matched,
                "export_receipt_sha256": exported["sha256"] if matched else None,
            }
        )
    expected_names = {row["export"] for row in source_catalog}
    results = []
    for source in sorted(exports.glob("*.md")):
        if source.is_symlink():
            raise ValueError("Captured export must not be a symlink")
        before = source.stat()
        raw = source.read_bytes()
        expected = chunk_text(
            raw.decode("utf-8").strip(),
            str(source),
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            min_chunk_size=config.min_chunk_size,
        )
        stored = drawers.get(
            where={"source_file": str(source)}, include=["metadatas", "documents"]
        )
        witnesses = closets.get(
            where={"source_file": str(source)}, include=["metadatas"]
        )
        after = source.stat()
        conserved = (before.st_mtime_ns, before.st_size) == (
            after.st_mtime_ns,
            after.st_size,
        )
        complete = (
            conserved
            and source.name in expected_names
            and coverage_complete(
                expected, stored, witnesses, before.st_mtime, NORMALIZE_VERSION
            )
        )
        identities = [row for row in source_catalog if row["export"] == source.name]
        identity = identities[0] if len(identities) == 1 else None
        if identity is not None and identity["receipt_known"]:
            complete = complete and identity["receipt_matches_catalog"] and identity["export_receipt_sha256"] == hashlib.sha256(raw).hexdigest()
        record = {
            "export": source.name,
            "expected_chunks": len(expected),
            "stored_chunks": len(stored["ids"]),
            "complete": complete,
            "capture_receipt_matches_catalog": identity["receipt_matches_catalog"] if identity else False,
        }
        if not complete:
            wanted = {chunk["chunk_index"]: chunk["content"] for chunk in expected}
            record.update(
                in_source_catalog=source.name in expected_names,
                content_mismatch_count=sum(
                    wanted.get(meta.get("chunk_index")) != document
                    for meta, document in zip(stored["metadatas"], stored["documents"])
                ),
                stale_version_count=sum(
                    meta.get("normalize_version", 0) < NORMALIZE_VERSION
                    for meta in stored["metadatas"]
                ),
                closet_counts=sorted(
                    {meta.get("drawer_count", -1) for meta in witnesses["metadatas"]}
                ),
                closet_time_delta_seconds=[
                    datetime.fromisoformat(meta["filed_at"]).timestamp()
                    - before.st_mtime
                    for meta in witnesses["metadatas"][:3]
                    if "filed_at" in meta
                ],
            )
        results.append(record)
    return {
        "exports": len(results),
        "source_catalog": source_catalog,
        "catalog_missing_exports": [
            row["source"] for row in source_catalog if not row["export_present"]
        ],
        "expected_chunks": sum(row["expected_chunks"] for row in results),
        "stored_chunks": sum(row["stored_chunks"] for row in results),
        "failures": [row for row in results if not row["complete"]],
        "authority": "exact retained export coverage only; historical claims are not verified truth",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=absolute_path, required=True)
    parser.add_argument("--palace", type=absolute_path, required=True)
    args = parser.parse_args(argv)
    result = verify(args.state_root, args.palace)
    print(json.dumps(result))
    return (
        0
        if result["exports"]
        and not result["failures"]
        and not result["catalog_missing_exports"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
