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
import stat
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))

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


def load_source_config(root: Path, *, raw: bytes | None = None) -> dict[str, Any]:
    path = root / CONFIG_PATH
    try:
        value = json.loads(raw.decode("utf-8") if raw is not None else path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
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


def discover_sources(root: Path, config: dict[str, Any], *, deadline: float | None = None) -> tuple[list[Path], list[dict[str, str]]]:
    found: dict[str, Path] = {}
    skipped: list[dict[str, str]] = []
    for pattern in config["include"]:
        candidates = root.glob(pattern) if deadline is None else _current_candidates(root, pattern, config, deadline)
        for candidate in candidates:
            if deadline is not None:
                _current_time(deadline)
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
    """Legacy index snapshot retrieval; current source freshness is not checked."""
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
        "freshness": "indexed_snapshot_not_current_validated",
    }


class CurrentDeferred(KnowledgeError):
    """The caller's bounded inspection could not establish current state."""


def _current_time(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise CurrentDeferred("Current-source inspection reached its caller deadline")


def _stamp(path: Path) -> tuple:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or path.resolve(strict=True) != path:
        raise KnowledgeError("Current sources must be direct regular files with one link")
    return _stat_stamp(info)


def _stat_stamp(info: os.stat_result) -> tuple:
    return tuple(getattr(info, key) for key in ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns"))


def _current_bytes(path: Path, maximum: int, deadline: float) -> tuple[bytes, tuple]:
    _current_time(deadline)
    before = _stamp(path)
    if before[3] > maximum:
        raise CurrentDeferred("Current-source file exceeds the selected inspection bound")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = _stat_stamp(os.fstat(stream.fileno()))
        # Windows path ctime can mean creation time while descriptor ctime
        # means change time. Keep full stamps within each native API channel.
        if opened[:5] != before[:5]:
            raise CurrentDeferred("Current source changed before opening")
        raw = stream.read(maximum + 1)
        if _stat_stamp(os.fstat(stream.fileno())) != opened:
            raise CurrentDeferred("Current source changed during reading")
    _current_time(deadline)
    if len(raw) > maximum or len(raw) != before[3] or _stamp(path) != before:
        raise CurrentDeferred("Current source changed or exceeded its bound during inspection")
    return raw, before


def _relative(value: str) -> str:
    if not isinstance(value, str) or not value or any(char in value for char in ("\\", ":", "\0")):
        raise KnowledgeError("Use one selected project-relative source path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in (".", "..") for part in value.split("/")) or path.as_posix() != value:
        raise KnowledgeError("Use one canonical project-relative source path")
    return value


def _current_candidates(root: Path, pattern: str, config: dict[str, Any], deadline: float) -> Iterable[Path]:
    """Bound default policy discovery and prune excluded directories, without a new index."""
    _current_time(deadline)
    _relative(pattern)
    if "**" not in pattern:
        parent, _, leaf = pattern.rpartition("/")
        if any(char in parent for char in "*?["):
            raise CurrentDeferred("Complex source policy needs a separately bounded inspection")
        selected = root / parent
        if not selected.exists():
            return
        if selected.resolve(strict=True) != selected or not selected.is_dir():
            raise CurrentDeferred("Selected source directory is not direct")
        for candidate in selected.glob(leaf):
            _current_time(deadline)
            yield candidate
        return
    prefix = pattern[:-5] if pattern.endswith("/**/*") else ""
    if not prefix or any(char in prefix for char in "*?["):
        raise CurrentDeferred("Complex recursive source policy needs a separately bounded inspection")
    selected = root / prefix
    if not selected.exists():
        return
    if selected.resolve(strict=True) != selected or not selected.is_dir():
        raise CurrentDeferred("Selected source directory is not direct")
    def failed(_error):
        raise CurrentDeferred("Selected source directory could not be inspected")
    for directory, names, files in os.walk(selected, followlinks=False, onerror=failed):
        _current_time(deadline)
        folder = Path(directory)
        names[:] = [name for name in names if not _matches((folder / name).relative_to(root).as_posix() + "/_", config["exclude"])]
        for name in names:
            if (folder / name).is_symlink():
                raise CurrentDeferred("Selected source directory is not direct")
        for name in files:
            _current_time(deadline)
            yield folder / name


def _inspect_current(root: Path, *, terms: str | None = None, limit: int = 10,
                     source: str | None = None, start_line: int = 1, line_limit: int = 50,
                     expected_sha256: str | None = None, seconds: float = 10) -> dict[str, Any]:
    """One bounded, read-only source/index snapshot. Never builds or changes data."""
    if isinstance(seconds, bool) or not isinstance(seconds, (float, int)) or not 0 < seconds <= 10:
        raise KnowledgeError("Inspection seconds must fit the existing10-second adapter ceiling")
    deadline = time.monotonic() + seconds
    root = root.expanduser().resolve(strict=True)
    identity = load_identity(root)
    identity_raw, identity_stamp = _current_bytes(root / ".icm/project.json", DEFAULT_CONFIG["max_file_bytes"], deadline)
    if json.loads(identity_raw.decode("utf-8")) != identity:
        raise CurrentDeferred("Project identity changed before source inspection")
    policy_raw, policy_stamp = _current_bytes(root / CONFIG_PATH, DEFAULT_CONFIG["max_file_bytes"], deadline)
    config = load_source_config(root, raw=policy_raw)
    maximum = min(config["max_file_bytes"], DEFAULT_CONFIG["max_file_bytes"])
    if source is not None:
        source = _relative(source)
        if type(start_line) is not int or start_line < 1 or type(line_limit) is not int or not 1 <= line_limit <= 50:
            raise KnowledgeError("Read requires a positive first line and1..50 lines")
        if expected_sha256 is not None and (not isinstance(expected_sha256, str) or not re.fullmatch("[a-f0-9]{64}", expected_sha256)):
            raise KnowledgeError("Expected source SHA256 must be64 lowercase hex digits")
    if terms is not None and (not isinstance(terms, str) or not re.findall(r"[A-Za-z0-9_]+", terms)
                              or type(limit) is not int or not 1 <= limit <= 50):
        raise KnowledgeError("Current query requires searchable terms and a limit from1 through50")
    reasons = []
    manifest_path = root / _relative(identity["knowledge_manifest"])
    manifest_raw = b""
    manifest = {}
    manifest_stamp = None
    try:
        manifest_raw, manifest_stamp = _current_bytes(manifest_path, maximum, deadline)
        manifest = json.loads(manifest_raw.decode("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeError):
        reasons.append("manifest_unavailable")
    if not isinstance(manifest, dict):
        raise KnowledgeError("Unsupported knowledge manifest")
    if any(manifest.get(key) != value for key, value in {
        "schema": MANIFEST_SCHEMA, "project_id": identity["project_id"], "canonical_root": str(root),
        "source_policy": CONFIG_PATH.as_posix(), "parser": PARSER_VERSION, "authority": "retrieval_only",
    }.items()):
        reasons.append("manifest_binding")
    policy_hash = _sha256(policy_raw)
    if manifest.get("source_policy_sha256") != policy_hash:
        reasons.append("source_policy_changed")
    declared = {}
    rows = manifest.get("sources", [])
    if not isinstance(rows, list):
        raise KnowledgeError("Unsupported manifest source list")
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("sha256"), str) or type(row.get("size")) is not int:
            raise KnowledgeError("Unsupported manifest source record")
        path = _relative(row.get("path"))
        if path in declared or not re.fullmatch("[a-f0-9]{64}", row["sha256"]) or row["size"] < 0:
            raise KnowledgeError("Ambiguous manifest source binding")
        declared[path] = {"sha256": row["sha256"], "size": row["size"]}
        _current_time(deadline)
    paths, skipped = discover_sources(root, config, deadline=deadline)
    unsupported = [row for row in skipped if row["reason"] != "excluded"]
    current = {}
    stamps = {}
    window = None
    connection = None
    index = _state_root(identity) / "knowledge.db"
    index_stamp = None
    expected_chunks = 0
    try:
        if not index.is_file():
            reasons.append("index_unavailable")
        else:
            index_stamp = _stamp(index)
            connection = sqlite3.connect(index.as_uri() + "?mode=ro", uri=True, timeout=0)
            connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            connection.execute("BEGIN")
            metadata_rows = connection.execute("SELECT key,value FROM metadata").fetchmany(5)
            metadata = dict(metadata_rows)
            if len(metadata_rows) != 4 or len(metadata) != 4 or any(metadata.get(key) != value for key, value in {
                "schema": INDEX_SCHEMA, "project_id": identity["project_id"], "manifest_sha256": _sha256(manifest_raw),
            }.items()):
                reasons.append("index_manifest_binding")
            indexed_rows = connection.execute("SELECT path,sha256,size FROM sources").fetchmany(len(declared) + 1)
            indexed = {row[0]: {"sha256": row[1], "size": row[2]} for row in indexed_rows}
            if len(indexed_rows) != len(indexed) or indexed != declared:
                reasons.append("index_source_binding")
        for path in paths:
            relative = path.relative_to(root).as_posix()
            if path.suffix.lower() not in DEFAULT_CONFIG["extensions"]:
                unsupported.append({"path": relative, "reason": "unsupported_format"})
                continue
            raw, stamp = _current_bytes(path, maximum, deadline)
            try:
                text = raw.decode("utf-8")
            except UnicodeError:
                unsupported.append({"path": relative, "reason": "not_utf8"})
                continue
            current[relative] = {"sha256": _sha256(raw), "size": len(raw)}
            stamps[path] = stamp
            if connection is not None and declared.get(relative) == current[relative]:
                expected = [(start, end, body, current[relative]["sha256"]) for start, end, body in _chunks(text)]
                expected_chunks += len(expected)
                saved = connection.execute("SELECT line_start,line_end,content,sha256 FROM chunks WHERE path=? ORDER BY rowid", (relative,)).fetchmany(len(expected) + 1)
                if saved != expected:
                    reasons.append("index_chunk_binding")
            if relative == source:
                if expected_sha256 is not None and expected_sha256 != current[relative]["sha256"]:
                    raise KnowledgeError("Expected source SHA256 differs from the current source")
                lines = text.splitlines(keepends=True)
                if start_line > len(lines):
                    raise KnowledgeError("Requested first line is outside the current source")
                selected = "".join(lines[start_line - 1:start_line - 1 + line_limit])
                body = selected[:4000]
                window = {"path": source, "sha256": current[relative]["sha256"], "source_bytes": len(raw),
                          "line_start": start_line, "line_end": start_line + len(body.splitlines()) - 1,
                          "total_lines": len(lines), "text": body, "text_sha256": _sha256(body.encode("utf-8")),
                          "returned_chars": len(body), "partial": len(body) < len(selected) or start_line - 1 + line_limit < len(lines)}
        added = sorted(set(current) - set(declared))
        removed = sorted(set(declared) - set(current))
        changed = sorted(path for path in set(current) & set(declared) if current[path] != declared[path])
        if added or removed or changed:
            reasons.append("source_set_changed")
        if unsupported:
            reasons.append("unsupported_sources")
        if connection is not None and not (added or removed or changed) and connection.execute("SELECT count(*) FROM chunks").fetchone()[0] != expected_chunks:
            reasons.append("index_chunk_binding")
        results = []
        if terms is not None and not reasons:
            tokens = re.findall(r"[A-Za-z0-9_]+", terms)
            rows = connection.execute(
                "SELECT path,sha256,line_start,line_end,snippet(chunks,4,'[',']','...',24),bm25(chunks) FROM chunks WHERE chunks MATCH ? ORDER BY bm25(chunks) LIMIT ?",
                (" ".join(f'"{token}"' for token in tokens[:32]), limit)).fetchall()
            results = [{"path": row[0], "sha256": row[1], "line_start": row[2], "line_end": row[3],
                        "snippet": row[4][:4000], "snippet_partial": len(row[4]) > 4000, "rank": row[5]} for row in rows]
        final_paths, final_skipped = discover_sources(root, config, deadline=deadline)
        if final_paths != paths or final_skipped != skipped:
            raise CurrentDeferred("Selected source membership changed before delivery")
        for path, stamp in stamps.items():
            final_raw, final_stamp = _current_bytes(path, maximum, deadline)
            relative = path.relative_to(root).as_posix()
            if final_stamp != stamp or _sha256(final_raw) != current[relative]["sha256"]:
                raise CurrentDeferred("Selected source changed before delivery")
        if _stamp(root / ".icm/project.json") != identity_stamp or _stamp(root / CONFIG_PATH) != policy_stamp:
            raise CurrentDeferred("Project or source policy changed before delivery")
        if manifest_stamp is not None and _stamp(manifest_path) != manifest_stamp:
            raise CurrentDeferred("Knowledge manifest changed before delivery")
        if index_stamp is not None and _stamp(index) != index_stamp:
            raise CurrentDeferred("Knowledge index changed before delivery")
        _current_time(deadline)
        fresh = not reasons
        result = {"ok": True, "schema": INDEX_SCHEMA, "project_id": identity["project_id"],
                  "status": "current" if fresh else "stale", "fresh": fresh, "reasons": sorted(set(reasons)),
                  "added": added, "changed": changed, "removed": removed, "unsupported": unsupported,
                  "source_count": len(current), "source_policy_sha256": policy_hash,
                  "manifest_sha256": _sha256(manifest_raw), "authority": "retrieval_only"}
        if source is not None:
            if window is None:
                raise KnowledgeError("Source is absent, unsupported or outside the selected current policy")
            result.update(status="current_source", index_fresh=fresh, source=window)
        if terms is not None:
            result.update(ok=fresh, query=terms, results=results)
        return result
    except sqlite3.Error as exc:
        if time.monotonic() >= deadline:
            raise CurrentDeferred("Current index inspection reached its caller deadline") from exc
        raise
    finally:
        if connection is not None:
            connection.close()


def current(root: Path, **request: Any) -> dict[str, Any]:
    """Typed deferral never delivers a partial query or source window."""
    try:
        return _inspect_current(root, **request)
    except CurrentDeferred as exc:
        return {"ok": False, "schema": INDEX_SCHEMA, "status": "deferred", "fresh": False,
                "reason": str(exc), "authority": "retrieval_only"}
    except sqlite3.Error as exc:
        code = getattr(exc, "sqlite_errorcode", None)
        # Older Python SQLite exceptions omit the native numeric error code.
        busy = (isinstance(code, int) and (code & 255) in (5, 6)) or (code is None and any(
            str(exc) == prefix or str(exc).startswith(prefix + ":") for prefix in (
                "database is locked", "database table is locked", "database schema is locked")))
        return {"ok": False, "schema": INDEX_SCHEMA, "status": "deferred" if busy or code == 9 else "unavailable",
                "fresh": False, "reason": "Current index is busy" if busy else "Current index could not be validated", "authority": "retrieval_only"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("command", choices=("build", "query", "status", "read"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--terms")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--current", action="store_true", help="Require current source/index bindings; legacy query reads an index snapshot")
    parser.add_argument("--source")
    parser.add_argument("--start-line", type=int, default=1)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--seconds", type=float, default=10)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            result = build(args.root)
        elif args.command == "status":
            result = current(args.root, seconds=args.seconds)
        elif args.command == "read":
            if not args.source:
                raise KnowledgeError("read requires --source")
            result = current(args.root, source=args.source, start_line=args.start_line, line_limit=args.limit,
                             expected_sha256=args.expected_sha256, seconds=args.seconds)
        else:
            if not args.terms or not 1 <= args.limit <= 50:
                raise KnowledgeError("query requires --terms and a limit from 1 through 50")
            result = current(args.root, terms=args.terms, limit=args.limit, seconds=args.seconds) if args.current else query(args.root, args.terms, args.limit)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("ok") else 2
    except (KnowledgeError, ProjectIdentityError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
