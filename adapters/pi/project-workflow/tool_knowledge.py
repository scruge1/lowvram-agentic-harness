#!/usr/bin/env python3
"""Build and query a hash-bound SQLite FTS catalog of system tools."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path

SCHEMA = "pi-system-tool-knowledge/v1"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def record_text(value: dict) -> str:
    fields = []
    for key in ("token", "name", "kind", "tier", "desc", "description", "when_to_use", "purpose", "text"):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            fields.append(item.strip())
    tags = value.get("tags")
    if isinstance(tags, list):
        fields.extend(str(item) for item in tags if isinstance(item, (str, int, float)))
    return " ".join(" ".join(fields).split())[:12000]


def build(database: Path, sources: list[Path]) -> dict:
    if not sources:
        raise ValueError("at least one source is required")
    source_rows = []
    records = []
    for source in sources:
        source = source.resolve(strict=True)
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"source is not a regular file: {source}")
        data = source.read_bytes()
        source_digest = sha256(data)
        source_rows.append((str(source), source_digest, len(data)))
        for line_number, line in enumerate(data.decode("utf-8-sig").splitlines(), 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {source}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"record is not an object at {source}:{line_number}")
            text = record_text(value)
            if not text:
                continue
            payload = canonical(value)
            records.append((str(source), source_digest, line_number, sha256(payload), text, payload.decode().rstrip("\n")))
    manifest = {
        "schema": SCHEMA,
        "sources": [{"path": path, "sha256": digest, "size": size} for path, digest, size in source_rows],
        "record_count": len(records),
        "authority": "retrieval_only",
    }
    database.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix="tool-knowledge-", suffix=".db", dir=database.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        connection = sqlite3.connect(temporary)
        connection.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("CREATE TABLE sources(path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, size INTEGER NOT NULL)")
        connection.execute("CREATE TABLE records(id INTEGER PRIMARY KEY, source_path TEXT NOT NULL, source_sha256 TEXT NOT NULL, line_number INTEGER NOT NULL, record_sha256 TEXT NOT NULL, text TEXT NOT NULL, payload TEXT NOT NULL)")
        connection.execute("CREATE VIRTUAL TABLE records_fts USING fts5(text, content='records', content_rowid='id')")
        connection.execute("CREATE TRIGGER records_ai AFTER INSERT ON records BEGIN INSERT INTO records_fts(rowid,text) VALUES(new.id,new.text); END")
        connection.executemany("INSERT INTO sources(path,sha256,size) VALUES(?,?,?)", source_rows)
        connection.executemany("INSERT INTO records(source_path,source_sha256,line_number,record_sha256,text,payload) VALUES(?,?,?,?,?,?)", records)
        manifest_sha = sha256(canonical(manifest))
        connection.executemany("INSERT INTO metadata(key,value) VALUES(?,?)", (("schema", SCHEMA), ("manifest_sha256", manifest_sha), ("record_count", str(len(records)))))
        connection.commit()
        connection.close()
        os.replace(temporary, database)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {"ok": True, **manifest, "manifest_sha256": manifest_sha, "database": str(database)}


def checked_connection(database: Path) -> tuple[sqlite3.Connection, dict]:
    connection = sqlite3.connect(f"file:{database.resolve(strict=True).as_posix()}?mode=ro", uri=True)
    metadata = dict(connection.execute("SELECT key,value FROM metadata"))
    if metadata.get("schema") != SCHEMA:
        connection.close()
        raise ValueError("unsupported tool knowledge schema")
    return connection, metadata


def query(database: Path, terms: str, limit: int) -> dict:
    tokens = re.findall(r"[A-Za-z0-9_.+-]+", terms)
    if not tokens:
        raise ValueError("query has no searchable terms")
    expression = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens[:24])
    connection, metadata = checked_connection(database)
    rows = connection.execute(
        "SELECT r.source_path,r.source_sha256,r.line_number,r.record_sha256,r.text,r.payload,bm25(records_fts) "
        "FROM records_fts JOIN records r ON r.id=records_fts.rowid WHERE records_fts MATCH ? ORDER BY bm25(records_fts) LIMIT 500",
        (expression,),
    ).fetchall()
    lifecycle_rows = connection.execute("SELECT payload FROM records").fetchall()
    lifecycle_by_path = {}
    lifecycle_by_name = {}
    for (payload,) in lifecycle_rows:
        value = json.loads(payload)
        if value.get("kind") != "tool-lifecycle":
            continue
        state = value.get("lifecycle")
        if state not in {"active", "candidate", "retired", "unknown"}:
            continue
        if value.get("target_path"):
            lifecycle_by_path[value["target_path"]] = state
        if value.get("target_name"):
            lifecycle_by_name[value["target_name"]] = state
    connection.close()
    normalized_tokens = list(dict.fromkeys(token.lower() for token in tokens[:24]))
    ranked = []
    for row in rows:
        value = json.loads(row[5])
        if value.get("kind") == "tool-lifecycle":
            continue
        text_lower = row[4].lower()
        matched = [token for token in normalized_tokens if token in text_lower]
        name = value.get("name") or value.get("token") or value.get("path") or "unnamed"
        path = value.get("path")
        if row[0].endswith("/rig_capabilities.jsonl"):
            lifecycle = "active"
            lifecycle_evidence = "observed_installed_inventory"
        else:
            lifecycle = lifecycle_by_path.get(path) or lifecycle_by_name.get(name) or "unknown"
            lifecycle_evidence = "maintained_overlay" if lifecycle != "unknown" else "not_classified"
        priority = {"active": 0, "unknown": 1, "candidate": 2, "retired": 3}[lifecycle]
        ranked.append((priority, len(matched), row[6], matched, row, lifecycle, lifecycle_evidence))
    ranked.sort(key=lambda item: (-item[1], item[0], item[2]))
    results = []
    for _priority, coverage, score, matched, row, lifecycle, lifecycle_evidence in ranked[:limit]:
        path, source_sha, line, record_sha, _text, payload, _score = row
        value = json.loads(payload)
        results.append({
            "name": value.get("name") or value.get("token") or value.get("path") or "unnamed",
            "kind": value.get("kind") or value.get("tier") or "record",
            "description": value.get("when_to_use") or value.get("desc") or value.get("purpose") or value.get("text") or "",
            "path": value.get("path"),
            "source_file": path,
            "source_sha256": source_sha,
            "source_line": line,
            "record_sha256": record_sha,
            "matched_terms": matched,
            "matched_term_count": coverage,
            "score": score,
            "lifecycle": lifecycle,
            "lifecycle_evidence": lifecycle_evidence,
            "usable_for_planning": lifecycle != "retired",
        })
    return {"ok": True, "schema": SCHEMA, "query": terms, "manifest_sha256": metadata["manifest_sha256"], "results": results, "authority": "retrieval_only"}


def status(database: Path) -> dict:
    connection, metadata = checked_connection(database)
    sources = [{"path": p, "sha256": h, "size": s} for p, h, s in connection.execute("SELECT path,sha256,size FROM sources ORDER BY path")]
    count = connection.execute("SELECT count(*) FROM records").fetchone()[0]
    connection.close()
    return {"ok": True, "schema": SCHEMA, "manifest_sha256": metadata["manifest_sha256"], "record_count": count, "sources": sources, "authority": "retrieval_only"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser("build")
    build_parser.add_argument("sources", nargs="+", type=Path)
    query_parser = sub.add_parser("query")
    query_parser.add_argument("terms")
    query_parser.add_argument("--limit", type=int, default=8)
    sub.add_parser("status")
    args = parser.parse_args()
    try:
        if args.command == "build":
            result = build(args.database, args.sources)
        elif args.command == "query":
            if not 1 <= args.limit <= 50:
                raise ValueError("limit must be between 1 and 50")
            result = query(args.database, args.terms, args.limit)
        else:
            result = status(args.database)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except Exception as exc:
        print(json.dumps({"ok": False, "schema": SCHEMA, "error": str(exc)}, sort_keys=True))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
