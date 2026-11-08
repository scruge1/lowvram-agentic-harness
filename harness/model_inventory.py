#!/usr/bin/env python3
"""Opt-in, read-only dynamic GGUF and physical NVIDIA GPU inventory.

This is a bounded discovery view, NOT a GPU scheduler, inference fit check,
model loader, SHA-verified weight catalogue or authorization to use a device.
A user supplies each model root explicitly; no private rig paths are embedded.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

SCHEMA = "pi-readonly-local-inventory/v1"
SHARD = re.compile(r"^(.*)-(\d{5})-of-(\d{5})\.gguf$", re.IGNORECASE)
UUID = re.compile(r"^GPU-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$", re.IGNORECASE)
MAX_ROOTS = 16
MAX_FILES = 20000
MAX_ASSETS = 2048
MAX_DEPTH = 6
MAX_SECONDS = 15.0


class InventoryError(ValueError):
    """The bounded inventory is unavailable; refuse rather than use partial data."""


def _label(value: str, maximum: int = 220) -> str:
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", value)[:maximum]


def _within(candidate: Path, root: Path) -> bool:
    return candidate == root or root in candidate.parents


def _fingerprint(index: int, paths: list[tuple[str, os.stat_result]]) -> str:
    # A change detector ONLY. This is NOT a digest of model-file contents.
    values = [(name, int(st.st_size), int(st.st_mtime_ns), int(st.st_dev), int(st.st_ino))
              for name, st in paths]
    return hashlib.sha256(json.dumps([index, values], separators=(",", ":")).encode()).hexdigest()


def discover_gguf(roots, *, max_files=MAX_FILES, max_assets=MAX_ASSETS,
                  max_depth=MAX_DEPTH, max_seconds=MAX_SECONDS, clock=time.monotonic):
    """List candidate GGUF assets under explicit roots; never open weight bytes.

    No directory symlinks are traversed and no file symlinks accepted.
    Incomplete/mismatched GGUF shards are exposed as non-runnable discoveries.
    """
    if not isinstance(roots, (tuple, list)) or not 1 <= len(roots) <= MAX_ROOTS:
        raise InventoryError("Supply between 1 and 16 explicit model directories")
    if (not isinstance(max_files, int) or not 1 <= max_files <= MAX_FILES
            or not isinstance(max_assets, int) or not 1 <= max_assets <= MAX_ASSETS
            or not isinstance(max_depth, int) or not 0 <= max_depth <= MAX_DEPTH
            or not isinstance(max_seconds, (int, float)) or not 0 < max_seconds <= MAX_SECONDS):
        raise InventoryError("Invalid discovery bounds")
    canonical_roots: list[Path] = []
    for root in roots:
        raw = Path(root)
        if raw.is_symlink() or not raw.is_dir():
            raise InventoryError("Model root is unavailable or a symlink")
        resolved = raw.resolve(strict=True)
        if resolved in canonical_roots:
            raise InventoryError("Duplicate canonical model root")
        canonical_roots.append(resolved)
    started = clock()
    examined = 0
    grouped: dict[tuple[int, str, int | None], dict] = {}
    errors: list[str] = []

    for index, root in enumerate(canonical_roots):
        def fail_walk(error):
            raise InventoryError("Model root traversal failed") from error

        for current, dirs, filenames in os.walk(root, topdown=True, followlinks=False, onerror=fail_walk):
            if clock() - started > max_seconds:
                raise InventoryError("Model discovery exceeded its time budget")
            here = Path(current)
            if not _within(here.resolve(strict=True), root):
                raise InventoryError("Model directory escaped its allowed root")
            depth = len(here.relative_to(root).parts)
            dirs[:] = ([name for name in sorted(dirs) if not name.startswith(".")
                        and not (here / name).is_symlink()]
                       if depth < max_depth else [])
            for name in sorted(filenames):
                examined += 1
                if examined > max_files or clock() - started > max_seconds:
                    raise InventoryError("Model discovery exceeded its file/time budget")
                path = here / name
                if path.suffix.lower() != ".gguf":
                    continue
                if path.is_symlink():
                    errors.append("symlink_asset_ignored")
                    continue
                if not path.is_file():
                    errors.append("nonregular_asset_ignored")
                    continue
                low = name.lower()
                if "mmproj" in low or "projector" in low:
                    continue
                canonical = path.resolve(strict=True)
                if not _within(canonical, root):
                    raise InventoryError("Model asset escaped its allowed root")
                st = os.stat(path, follow_symlinks=False)
                rel = path.relative_to(root).as_posix()
                match = SHARD.fullmatch(name)
                if match:
                    prefix, ordinal, count = match.group(1), int(match.group(2)), int(match.group(3))
                    if not 1 <= count <= 999 or not 1 <= ordinal <= count:
                        errors.append("invalid_shard_number")
                        continue
                    group_name = (Path(rel).parent / prefix).as_posix()
                    group_key = (index, group_name, count)
                else:
                    ordinal, count = 1, 1
                    group_name = rel[:-5]  # remove .gguf, case-insensitive
                    group_key = (index, group_name, None)
                group = grouped.setdefault(group_key, {"root_index": index, "group_name": group_name,
                    "expected_shards": count, "members": {}})
                if ordinal in group["members"]:
                    raise InventoryError("Duplicate model shard ordinal")
                group["members"][ordinal] = (rel, st)
                if len(grouped) > max_assets:
                    raise InventoryError("Model discovery exceeded its asset budget")

    assets = []
    for (index, group_name, _), group in sorted(grouped.items()):
        expected = group["expected_shards"]
        members = group["members"]
        complete = set(members) == set(range(1, expected + 1))
        ordered = sorted(members.items())
        identities = [item[1] for item in ordered]
        assets.append({
            "id": "asset_" + _fingerprint(index, identities)[:20],
            "root_index": index,
            "name": _label(Path(group_name).name),
            "format": "gguf",
            "state": "installed_unqualified" if complete else "incomplete_shards",
            "paths": [entry[0] for entry in identities] if complete else [],
            "listed_shards": len(ordered),
            "expected_shards": expected,
            "size_bytes": sum(st.st_size for _, st in identities),
            "source_stat_sha256": _fingerprint(index, identities),
            "metadata_read": False,
            "runnable": False,
            "execution_authority": "none",
        })
    return {"schema": SCHEMA, "status": "observed", "authority": "none",
            "model_roots_supplied": len(canonical_roots), "files_examined": examined,
            "assets": assets, "warnings": sorted(set(errors)),
            "notes": "Filesystem size is not VRAM fit. IDs bind source stat metadata, not weight bytes; revalidate a selected file before use. No model or GPU is touched."}


def parse_gpu_inventory(stdout: str):
    """Strict point-in-time GPU inventory; absence or ambiguity fails closed."""
    if not isinstance(stdout, str) or not stdout.strip() or len(stdout) > 128000:
        raise InventoryError("GPU observation is missing or oversized")
    rows = list(csv.reader(stdout.splitlines(), skipinitialspace=True))
    if not 1 <= len(rows) <= 64:
        raise InventoryError("GPU count is unavailable or oversized")
    cards = []
    seen_uuid, seen_index = set(), set()
    for row in rows:
        if len(row) != 6:
            raise InventoryError("Malformed GPU inventory row")
        index, uuid, name, total, used, free = (value.strip() for value in row)
        if not index.isdecimal() or not UUID.fullmatch(uuid) or not name:
            raise InventoryError("GPU identity is invalid")
        if not all(item.isdecimal() for item in (total, used, free)):
            raise InventoryError("GPU memory counters are invalid")
        index_n, total_n, used_n, free_n = map(int, (index, total, used, free))
        if (index_n in seen_index or uuid.lower() in seen_uuid or total_n <= 0
                or used_n > total_n or free_n > total_n
                or abs(total_n - used_n - free_n) > 256):
            raise InventoryError("GPU identity/memory reading is inconsistent")
        seen_index.add(index_n)
        seen_uuid.add(uuid.lower())
        cards.append({"index": index_n, "uuid": uuid, "name": _label(name),
                      "total_mib": total_n, "used_mib": used_n, "free_mib": free_n,
                      "process_owner": "unknown", "available_for_tasks": "not_established"})
    return sorted(cards, key=lambda row: row["index"])


def gpu_inventory(*, run=subprocess.run):
    command = ["/usr/bin/nvidia-smi" if os.name != "nt" else "nvidia-smi",
               "--query-gpu=index,uuid,name,memory.total,memory.used,memory.free",
               "--format=csv,noheader,nounits"]
    try:
        result = run(command, check=False, capture_output=True, text=True, timeout=7)
        if result.returncode != 0:
            raise InventoryError("nvidia-smi failed")
        cards = parse_gpu_inventory(result.stdout)
        return {"status": "observed", "devices": cards, "authority": "none",
                "safe_to_allocate": False, "observation": "point_in_time_only"}
    except (OSError, subprocess.TimeoutExpired, InventoryError):
        return {"status": "unavailable", "devices": [], "authority": "none",
                "safe_to_allocate": False, "observation": "not_verified"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--root", dest="roots", action="append", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=512)
    parser.add_argument("--no-gpu-probe", action="store_true")
    opts = parser.parse_args(argv)
    try:
        catalogue = discover_gguf(opts.roots, max_assets=opts.limit)
    except (InventoryError, OSError, ValueError):
        print(json.dumps({"schema": SCHEMA, "status": "unavailable", "authority": "none",
                          "error": "Model inventory unavailable; inspect explicit roots and source bounds."}))
        return 1
    catalogue["gpu"] = ({"status": "not_requested", "devices": [], "safe_to_allocate": False}
                        if opts.no_gpu_probe else gpu_inventory())
    print(json.dumps(catalogue, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
