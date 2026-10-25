"""Read back captured exports against their source catalog and native chunk coverage."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from capture import absolute_path, coverage_complete, export_path


def verify(state: Path, palace: Path) -> dict:
    from mempalace.config import MempalaceConfig
    from mempalace.miner import chunk_text, NORMALIZE_VERSION
    from mempalace.palace import get_collection, get_closets_collection

    state = state.resolve(strict=True)
    palace = palace.resolve(strict=True)
    catalog = json.loads((state / "sources.json").read_text())
    if not isinstance(catalog, dict):
        raise ValueError("Captured source catalog must be an object")
    config = MempalaceConfig()
    drawers = get_collection(str(palace), create=False, read_only=True)
    closets = get_closets_collection(str(palace), create=False, read_only=True)
    exports = state / "exports"
    source_catalog = []
    for source, signature in sorted(catalog.items()):
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
            }
        )
    expected_names = {row["export"] for row in source_catalog}
    results = []
    for source in sorted(exports.glob("*.md")):
        if source.is_symlink():
            raise ValueError("Captured export must not be a symlink")
        before = source.stat()
        expected = chunk_text(
            source.read_text(encoding="utf-8").strip(),
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
        record = {
            "export": source.name,
            "expected_chunks": len(expected),
            "stored_chunks": len(stored["ids"]),
            "complete": complete,
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
