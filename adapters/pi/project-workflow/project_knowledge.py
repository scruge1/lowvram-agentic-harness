#!/usr/bin/env python3
"""Build and query a hash-bound, rebuildable project knowledge index."""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

from project_identity import ProjectIdentityError, load_identity


SOURCES_SCHEMA = "pi-project-knowledge-sources/v1"
MANIFEST_SCHEMA = "pi-project-knowledge-manifest/v1"
INDEX_SCHEMA = "pi-project-knowledge-index/v1"
PARSER_VERSION = "plain-text-chunks/v1"
CONFIG_PATH = Path(".icm/knowledge-sources.json")
DEFAULT_CONFIG: dict[str, Any] = {
    "schema": SOURCES_SCHEMA,
    "include": [
        "AGENTS.md",
        "README*",
        "PROJECT-*.md",
        "docs/**/*",
        "wiki/**/*",
        ".icm/workspace/AGENTS.md",
        ".icm/workspace/PROJECT-SSOT.md",
        ".icm/workspace/ACTIVE-CHECKPOINT.md",
        ".icm/workspace/DIARY.md",
        ".icm/workspace/COVERAGE-MATRIX.md",
        ".icm/workspace/wiki/**/*",
        ".icm/skills/**/*",
    ],
    "exclude": [
        "**/.env*",
        "**/*secret*",
        "**/*credential*",
        "**/*token*",
        "**/.git/**",
        "**/node_modules/**",
        "**/__pycache__/**",
        "**/artifacts/**",
        "**/OPERATION-RECEIPTS/**",
    ],
    "extensions": [".json", ".jsonl", ".md", ".rst", ".toml", ".txt", ".yaml", ".yml"],
    "max_file_bytes": 2097152,
}


class KnowledgeError(RuntimeError):
    pass


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ensure_source_config(root: Path) -> tuple[dict[str, Any], bool]:
    path = root / CONFIG_PATH
    if path.exists():
        return load_source_config(root), False
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(DEFAULT_CONFIG, indent=2, sort_keys=True) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        return load_source_config(root), False
    return dict(DEFAULT_CONFIG), True


def load_source_config(root: Path) -> dict[str, Any]:
    path = root / CONFIG_PATH
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KnowledgeError(f"cannot read source policy {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != SOURCES_SCHEMA:
        raise KnowledgeError("unsupported project knowledge source policy")
    required = {"schema", "include", "exclude", "extensions", "max_file_bytes"}
    if set(value) != required:
        raise KnowledgeError("project knowledge source policy fields differ")
    if not all(isinstance(value[name], list) and all(isinstance(item, str) for item in value[name]) for name in ("include", "exclude", "extensions")):
        raise KnowledgeError("include, exclude, and extensions must be text lists")
    if not isinstance(value["max_file_bytes"], int) or not 1 <= value["max_file_bytes"] <= 16 * 1024 * 1024:
        raise KnowledgeError("max_file_bytes is invalid")
    return value


def _matches(path: str, patterns: Iterable[str]) -> bool:
    normalized = path.replace("\\", "/")
    return any(fnmatch.fnmatchcase(normalized.lower(), pattern.lower()) for pattern in patterns)


def discover_sources(root: Path, config: dict[str, Any]) -> tuple[list[Path], list[dict[str, str]]]:
    found: dict[str, Path] = {}
    skipped: list[dict[str, str]] = []
    for pattern in config["include"]:
        for candidate in root.glob(pattern):
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(root).as_posix()
            if _matches(relative, config["exclude"]):
                skipped.append({"path": relative, "reason": "excluded"})
                continue
            if candidate.suffix.lower() not in set(config["extensions"]):
                skipped.append({"path": relative, "reason": "unsupported_extension"})
                continue
            resolved = candidate.resolve(strict=True)
            try:
                resolved.relative_to(root)
            except ValueError:
                skipped.append({"path": relative, "reason": "outside_project_root"})
                continue
            if candidate.stat().st_size > config["max_file_bytes"]:
                skipped.append({"path": relative, "reason": "too_large"})
                continue
            found[relative] = candidate
    return [found[key] for key in sorted(found)], sorted(skipped, key=lambda item: (item["path"], item["reason"]))


def _chunks(text: str, maximum: int = 4000) -> list[tuple[int, int, str]]:
    lines = text.splitlines()
    chunks: list[tuple[int, int, str]] = []
    start = 1
    buffer: list[str] = []
    length = 0
    for number, line in enumerate(lines, 1):
        addition = len(line) + 1
        if buffer and length + addition > maximum:
            chunks.append((start, number - 1, "\n".join(buffer)))
            buffer = []
            length = 0
            start = number
        buffer.append(line)
        length += addition
    if buffer:
        chunks.append((start, len(lines), "\n".join(buffer)))
    return chunks


def _state_root(identity: dict[str, Any]) -> Path:
    return Path(identity["state_root"]).expanduser()


def build(root: Path) -> dict[str, Any]:
    root = root.expanduser().resolve(strict=True)
    identity = load_identity(root)
    config, config_created = ensure_source_config(root)
    sources, skipped = discover_sources(root, config)
    built_at = _utc_now()
    records: list[dict[str, Any]] = []
    decoded: list[tuple[dict[str, Any], str]] = []
    for source in sources:
        data = source.read_bytes()
        relative = source.relative_to(root).as_posix()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            skipped.append({"path": relative, "reason": "not_utf8"})
            continue
        record = {
            "path": relative,
            "sha256": _sha256(data),
            "size": len(data),
            "role": "project_knowledge_source",
            "indexed_at": built_at,
            "parser": PARSER_VERSION,
        }
        records.append(record)
        decoded.append((record, text))

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "project_id": identity["project_id"],
        "canonical_root": str(root),
        "built_at": built_at,
        "source_policy": CONFIG_PATH.as_posix(),
        "source_policy_sha256": _sha256((root / CONFIG_PATH).read_bytes()),
        "parser": PARSER_VERSION,
        "sources": records,
        "skipped": sorted(skipped, key=lambda item: (item["path"], item["reason"])),
        "authority": "retrieval_only",
    }
    manifest_path = root / identity["knowledge_manifest"]
    manifest_payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"

    state_root = _state_root(identity)
    state_root.mkdir(parents=True, exist_ok=True)
    index_path = state_root / "knowledge.db"
    handle, temporary_name = tempfile.mkstemp(prefix="knowledge-", suffix=".db", dir=state_root)
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        connection = sqlite3.connect(temporary)
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("CREATE TABLE sources (path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, size INTEGER NOT NULL)")
        connection.execute("CREATE VIRTUAL TABLE chunks USING fts5(path UNINDEXED, sha256 UNINDEXED, line_start UNINDEXED, line_end UNINDEXED, content)")
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            (("schema", INDEX_SCHEMA), ("project_id", identity["project_id"]), ("manifest_sha256", _sha256(manifest_payload.encode("utf-8"))), ("built_at", built_at)),
        )
        for record, text in decoded:
            connection.execute("INSERT INTO sources(path, sha256, size) VALUES (?, ?, ?)", (record["path"], record["sha256"], record["size"]))
            connection.executemany(
                "INSERT INTO chunks(path, sha256, line_start, line_end, content) VALUES (?, ?, ?, ?, ?)",
                ((record["path"], record["sha256"], start, end, content) for start, end, content in _chunks(text)),
            )
        connection.commit()
        connection.close()
        temporary.replace(index_path)
        manifest_path.write_text(manifest_payload, encoding="utf-8", newline="\n")
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "ok": True,
        "schema": INDEX_SCHEMA,
        "project_id": identity["project_id"],
        "manifest": str(manifest_path),
        "manifest_sha256": _sha256(manifest_payload.encode("utf-8")),
        "index": str(index_path),
        "source_count": len(records),
        "skipped_count": len(skipped),
        "source_policy_created": config_created,
        "authority": "retrieval_only",
    }


def query(root: Path, terms: str, limit: int) -> dict[str, Any]:
    root = root.expanduser().resolve(strict=True)
    identity = load_identity(root)
    index = _state_root(identity) / "knowledge.db"
    if not index.is_file():
        raise KnowledgeError("project knowledge index does not exist; run build")
    connection = sqlite3.connect(f"file:{index.as_posix()}?mode=ro", uri=True)
    metadata = dict(connection.execute("SELECT key, value FROM metadata"))
    if metadata.get("schema") != INDEX_SCHEMA or metadata.get("project_id") != identity["project_id"]:
        raise KnowledgeError("project knowledge index identity differs")
    tokens = re.findall(r"[A-Za-z0-9_]+", terms)
    if not tokens:
        connection.close()
        raise KnowledgeError("knowledge query has no searchable terms")
    fts_query = " ".join(f'"{token}"' for token in tokens[:32])
    rows = connection.execute(
        "SELECT path, sha256, line_start, line_end, snippet(chunks, 4, '[', ']', '...', 24), bm25(chunks) FROM chunks WHERE chunks MATCH ? ORDER BY bm25(chunks) LIMIT ?",
        (fts_query, limit),
    ).fetchall()
    connection.close()
    return {
        "ok": True,
        "schema": INDEX_SCHEMA,
        "project_id": identity["project_id"],
        "query": terms,
        "results": [
            {"path": row[0], "sha256": row[1], "line_start": row[2], "line_end": row[3], "snippet": row[4], "rank": row[5]}
            for row in rows
        ],
        "authority": "retrieval_only",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "query"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--terms")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            result = build(args.root)
        else:
            if not args.terms or not 1 <= args.limit <= 50:
                raise KnowledgeError("query requires --terms and a limit from 1 through 50")
            result = query(args.root, args.terms, args.limit)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (KnowledgeError, ProjectIdentityError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
