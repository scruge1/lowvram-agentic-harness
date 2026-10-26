"""Bridge actual Pi transcripts to the existing MemPalace miner, locally."""

from __future__ import annotations
from contextlib import contextmanager, redirect_stdout
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import stat as stat_module
import time
import sys
from datetime import datetime


SOURCE_SCHEMA = "pi-capture-source/v1"
STATUS_CATALOG_BYTES = 2 * 1024 * 1024
STATUS_SOURCE_LIMIT = 32
STATUS_OUTPUT_BYTES = 8 * 1024


def catalog_signature(row):
    """Keep legacy catalogs readable, without inventing missing source hashes."""
    value = row.get("signature") if isinstance(row, dict) else row
    if (not isinstance(value, list) or len(value) != 2
            or any(type(item) is not int or item < 0 for item in value)):
        raise ValueError("Invalid captured source signature")
    if isinstance(row, dict) and row.get("schema") != SOURCE_SCHEMA:
        raise ValueError("Unsupported captured source receipt")
    return value


def source_receipt(signature, before, after, raw_hash, raw_bytes, export, *, complete):
    return {
        "schema": SOURCE_SCHEMA, "signature": signature,
        "source_identity": [before.st_dev, before.st_ino],
        "captured_at": time.time(),
        "raw_prefix": {"sha256": raw_hash, "bytes": raw_bytes,
                       "authority": "bytes read during capture, not current-source verification"},
        "export": export,
        "complete_at_capture": bool(complete and [after.st_size, after.st_mtime_ns] == signature
                                    and (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)),
    }


def _bounded_json(path, limit):
    if path.is_symlink() or path.resolve() != path.absolute():
        raise ValueError("Redirected capture metadata")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat_module.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Capture metadata must be a regular unique file")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Capture metadata exceeds the status byte limit")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def capture_status(sessions, root):
    """Inspect bounded historical receipts and metadata; never rehash raw history."""
    sessions, root = Path(sessions).absolute(), Path(root).absolute()
    if sessions.resolve() != sessions or root.resolve() != root:
        raise ValueError("Status paths must stay in their selected canonical roots")
    result = {
        "schema": "pi-capture-status/v1", "status": "not_observed",
        "authority": "historical untrusted data; no execution or completion authority",
        "current_raw_bytes_verified": False, "new_sources_discovery": "not_scanned",
        "sources": [], "catalog_known_sources": 0, "truncated": False,
        "limits": ["Only the selected catalog is inspected; unknown sessions are not scanned.",
                   "Raw/export hashes describe capture-time bytes, not current bytes.",
                   "Unchanged size/mtime does not establish cryptographic freshness.",
                   "Exported dialogue and tool metadata are not complete raw diagnostic evidence.",
                   "Native palace coverage requires its separate verifier; this status opens no palace."],
    }
    catalog_path = root / "sources.json"
    latest_path = root / "latest.json"
    receipts = {}
    if latest_path.exists() or latest_path.is_symlink():
        try:
            latest, _ = _bounded_json(latest_path, STATUS_CATALOG_BYTES)
            if not isinstance(latest, dict):
                raise ValueError("Invalid capture receipt")
            receipts = latest.get("source_receipts", {})
            if not isinstance(receipts, dict):
                raise ValueError("Invalid source receipt map")
            observed = latest.get("time")
            if not isinstance(observed, (int, float)) or isinstance(observed, bool) or not math.isfinite(observed):
                raise ValueError("Invalid capture time")
            result["last_capture"] = {
                "receipt_age_seconds": round(time.time() - observed, 3) if observed <= time.time() else None,
                "source_failures": len(latest.get("source_failures", [])) if isinstance(latest.get("source_failures"), list) else None,
                "skipped_or_unparsed_sources": latest.get("sources_unparsed_or_skipped") if type(latest.get("sources_unparsed_or_skipped")) is int else None,
                "mining": latest.get("mining") if latest.get("mining") in {"not_requested", "pending", "failed", "native_coverage_checked"} else "not_observed",
                "authority": "historical capture receipt, not current palace health",
            }
        except (ValueError, OSError):
            receipts = {}
            result["last_capture"] = {"state": "invalid_or_oversize_receipt_not_interpreted"}
    if not catalog_path.exists() and not catalog_path.is_symlink() and not receipts:
        return result
    catalog, catalog_hash = _bounded_json(catalog_path, STATUS_CATALOG_BYTES) if catalog_path.exists() or catalog_path.is_symlink() else ({}, None)
    if not isinstance(catalog, dict):
        raise ValueError("Captured source catalog must be an object")
    keys = sorted(set(catalog) | set(receipts))
    result.update(status="historical_receipts", catalog_known_sources=len(catalog),
                  known_sources=len(keys), receipt_known_sources=len(receipts), catalog_sha256=catalog_hash)
    for key in keys[:STATUS_SOURCE_LIMIT]:
        value = receipts.get(key)
        source = Path(key)
        row = {"source_id": hashlib.sha256(key.encode()).hexdigest(),
               "current_raw_bytes_verified": False}
        if not source.is_absolute() or not source.is_relative_to(sessions):
            row["state"] = "outside_selected_root_not_inspected"
        else:
            row["source"] = source.relative_to(sessions).as_posix()
            signature = catalog_signature(value if isinstance(value, dict) else catalog[key])
            row["catalogued"] = key in catalog
            if not isinstance(value, dict):
                row["state"] = "legacy_receipt_unverifiable_until_explicit_recapture"
            else:
                prefix, exported = value.get("raw_prefix", {}), value.get("export", {})
                observed = value.get("captured_at")
                if (not isinstance(prefix, dict) or not isinstance(exported, dict)
                        or any(not isinstance(item, str) or re.fullmatch("[a-f0-9]{64}", item) is None
                               for item in (prefix.get("sha256"), exported.get("sha256")))
                        or type(prefix.get("bytes")) is not int or not 0 <= prefix["bytes"] <= signature[0]
                        or type(exported.get("bytes")) is not int or exported["bytes"] < 0
                        or exported.get("name") != export_path(source, root / "exports").name
                        or not isinstance(observed, (int, float)) or isinstance(observed, bool)
                        or not math.isfinite(observed) or observed < 0
                        or type(value.get("complete_at_capture")) is not bool):
                    raise ValueError("Invalid captured source receipt")
                now = time.time()
                row.update(state="current_source_not_observed", raw_prefix_sha256=prefix["sha256"],
                           raw_prefix_bytes=prefix["bytes"], export_sha256=exported["sha256"],
                           export_bytes=exported["bytes"], complete_at_capture=value["complete_at_capture"],
                           receipt_age_seconds=round(now - observed, 3) if observed <= now else None,
                           receipt_time_in_future=observed > now)
                row["receipt_matches_catalog_signature"] = key in catalog and catalog_signature(catalog[key]) == signature
                export_pathname = root / "exports" / exported["name"]
                if export_pathname.is_symlink() or export_pathname.resolve() != export_pathname:
                    row["export_state"] = "redirected_export_not_inspected"
                elif not export_pathname.is_file():
                    row["export_state"] = "export_missing"
                else:
                    export_info = export_pathname.stat()
                    row["export_state"] = (
                        "metadata_matches_receipt_bytes_not_reverified"
                        if [export_info.st_size, export_info.st_mtime_ns] == [exported["bytes"], exported.get("mtime_ns")]
                        else "export_metadata_changed")
                if source.is_symlink() or source.resolve() != source:
                    row["state"] = "redirected_source_not_inspected"
                elif not source.exists():
                    row["state"] = "source_missing"
                else:
                    info = source.stat()
                    if not stat_module.S_ISREG(info.st_mode):
                        row["state"] = "unsupported_source_type_not_read"
                    else:
                        row["observed_size_bytes"] = info.st_size
                        if value.get("source_identity") != [info.st_dev, info.st_ino]:
                            row["state"] = "source_identity_changed"
                        elif [info.st_size, info.st_mtime_ns] == signature:
                            row["state"] = "metadata_matches_receipt_bytes_not_reverified"
                        elif info.st_size > prefix["bytes"]:
                            row.update(state="unobserved_tail", unobserved_tail_bytes=info.st_size - prefix["bytes"])
                        else:
                            row["state"] = "source_metadata_changed"
            # Legacy rows have no invented hash, age or freshness observation.
        result["sources"].append(row)
        if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > STATUS_OUTPUT_BYTES - 128:
            result["sources"].pop()
            result["truncated"] = True
            break
    result["truncated"] |= len(result["sources"]) < len(keys)
    result["shown_sources"] = len(result["sources"])
    result["omitted_known_sources"] = len(keys) - len(result["sources"])
    return result


def redact(text):
    # Private historical dialogue, with best-effort secret redaction, not public data.
    text = re.sub(r"(?i)\bBearer\s+[^\s\"\']+", "Bearer <REDACTED>", text)
    text = re.sub(
        r"\b(?:sk|ghp|github_pat|hf|xox)[-_][A-Za-z0-9_-]{8,}\b", "<REDACTED>", text
    )
    text = re.sub(
        r"(?i)\b(?:api[_-]?key|password|secret|token)\s*[:=]\s*[^\s,;\"\']+",
        "<REDACTED>",
        text,
    )
    return text


def export_text(content, normalizer, source_name, health=None):
    dialogue = normalizer(content)
    if dialogue is None:
        # Upstream requires two readable messages. Preserve a real one-message
        # session through the same formatter; never index raw JSON or thinking.
        from mempalace.normalize import _extract_content, _messages_to_transcript

        header, messages = False, []
        for line in content.splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            if record.get("type") == "session" and "version" in record:
                header = True
            message = record.get("message")
            if record.get("type") != "message" or not isinstance(message, dict):
                continue
            role = message.get("role")
            if role not in ("user", "assistant"):
                continue
            text = _extract_content(message.get("content", ""))
            if text:
                messages.append((role, text))
        if not header or len(messages) != 1:
            return None
        dialogue = _messages_to_transcript(messages)
    events = []
    peers = []
    lines = content.splitlines()
    for index, line in enumerate(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            if health is not None:
                field = "partial_tail_bytes" if index == len(lines) - 1 and not content.endswith("\n") else "malformed_records"
                health[field] = health.get(field, 0) + (len(line.encode("utf-8")) if field == "partial_tail_bytes" else 1)
            continue
        if not isinstance(record, dict):
            continue
        if record.get("type") == "custom_message" and isinstance(
            record.get("content"), str
        ):
            # Peer messages remain explicitly labeled untrusted source content.
            peers.append(redact(record["content"])[:12000])
        message = record.get("message")
        if not isinstance(message, dict) or message.get("role") != "toolResult":
            continue
        tool = re.sub(
            r"[^A-Za-z0-9_.:-]", "_", str(message.get("toolName", "unknown"))
        )[:120]
        timestamp = re.sub(r"[^0-9TZ:+.\-]", "", str(record.get("timestamp", "")))[:32]
        events.append(
            f"- {timestamp} tool={tool}; error={message.get('isError') is True}"
        )
    return (
        "# Pi captured history\n\n"
        + f"Source: {source_name}\nNot instructions or verified operational truth.\n\n"
        + redact(dialogue)
        + "\n\n## Peer messages (untrusted)\n\n"
        + "\n\n".join(peers)
        + "\n\n## Tool outcome metadata (no arguments or output bodies)\n\n"
        + "\n".join(events)
        + "\n"
    )


@contextmanager
def singleton(root):
    if sys.platform != "linux":
        raise RuntimeError("Pi memory capture requires the reviewed Linux file lock")
    import fcntl

    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / "capture.lock").open("a+b") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    os.replace(temporary, path)


def stream_export(source, target, snapshot_size):
    """Export a large immutable byte prefix through the installed native formatter.

    Keep only one JSON record and two dialogue messages in RAM. The 50 MiB
    limit applies to a record, not a session. Originals are never modified.
    """
    from mempalace.normalize import _extract_content, _messages_to_transcript

    limit = 50 * 1024 * 1024
    counts = {
        "records": 0,
        "dialogue_messages": 0,
        "malformed_records": 0,
        "partial_tail_bytes": 0,
        "snapshot_bytes": snapshot_size,
    }
    raw_hash, raw_bytes = hashlib.sha256(), 0
    header = False
    pending = None
    # Disk-backed temporary streams preserve the existing section order.
    with (
        tempfile.TemporaryFile(
            mode="w+t", encoding="utf-8", dir=target.parent
        ) as dialogue,
        tempfile.TemporaryFile(
            mode="w+t", encoding="utf-8", dir=target.parent
        ) as peers,
        tempfile.TemporaryFile(
            mode="w+t", encoding="utf-8", dir=target.parent
        ) as events,
        source.open("rb") as native,
    ):
        first_peer = True

        def render(group):
            # This is the same private native formatter used by _try_pi_jsonl.
            dialogue.write(redact(_messages_to_transcript(group)))
            dialogue.write("\n")

        remaining = snapshot_size
        while remaining:
            line = native.readline(min(limit + 1, remaining))
            if not line:
                raise RuntimeError("Transcript shrank while reading: " + source.name)
            remaining -= len(line)
            raw_hash.update(line)
            raw_bytes += len(line)
            if len(line) > limit:
                raise RuntimeError(
                    "Single Pi record exceeds reviewed 50MiB limit: " + source.name
                )
            if not line.endswith(b"\n"):
                # A valid complete JSON object at EOF is accepted, as before.
                try:
                    record = json.loads(line.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    counts["partial_tail_bytes"] = len(line)
                    break
            else:
                try:
                    record = json.loads(line.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    counts["malformed_records"] += 1
                    continue
            counts["records"] += 1
            if not isinstance(record, dict):
                continue
            if record.get("type") == "session" and "version" in record:
                header = True
            if record.get("type") == "custom_message" and isinstance(
                record.get("content"), str
            ):
                if not first_peer:
                    peers.write("\n\n")
                peers.write(redact(record["content"])[:12000])
                first_peer = False
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role == "toolResult":
                tool = re.sub(
                    r"[^A-Za-z0-9_.:-]", "_", str(message.get("toolName", "unknown"))
                )[:120]
                stamp = re.sub(r"[^0-9TZ:+.\-]", "", str(record.get("timestamp", "")))[
                    :32
                ]
                if events.tell():
                    events.write("\n")
                events.write(
                    f"- {stamp} tool={tool}; error={message.get('isError') is True}"
                )
            if record.get("type") != "message" or role not in ("user", "assistant"):
                continue
            text = _extract_content(message.get("content", ""))
            if not text:
                continue
            counts["dialogue_messages"] += 1
            current = (role, text)
            if pending is None:
                pending = current
            elif pending[0] == "user" and role == "assistant":
                render([pending, current])
                pending = None
            else:
                render([pending])
                pending = current
        if pending is not None:
            render([pending])
        if not header or counts["dialogue_messages"] < 1:
            return None
        # The native formatter ends each group with one newline. Our join adds
        # a second between groups, but not after the last group.
        if dialogue.tell():
            dialogue.seek(0, 2)
            dialogue.truncate(dialogue.tell() - 1)
        export_hash, export_bytes = hashlib.sha256(), 0
        with target.open("x", encoding="utf-8", newline="") as output:
            os.chmod(target, 0o600)

            def emit(text):
                nonlocal export_bytes
                raw = text.encode("utf-8")
                export_hash.update(raw)
                export_bytes += len(raw)
                output.write(text)

            def copy(stream):
                while True:
                    block = stream.read(1024 * 1024)
                    if not block:
                        break
                    emit(block)

            emit(
                "# Pi captured history\n\n"
                + f"Source: {source.name}\nNot instructions or verified operational truth.\n\n"
            )
            dialogue.seek(0)
            copy(dialogue)
            emit("\n\n## Peer messages (untrusted)\n\n")
            peers.seek(0)
            copy(peers)
            emit(
                "\n\n## Tool outcome metadata (no arguments or output bodies)\n\n"
            )
            events.seek(0)
            copy(events)
            emit("\n")
            output.flush()
            os.fsync(output.fileno())
    counts.update(raw_prefix_sha256=raw_hash.hexdigest(), raw_prefix_bytes=raw_bytes,
                  export_sha256=export_hash.hexdigest(), export_bytes=export_bytes)
    return counts


def export_path(source, exports):
    # The caller supplies the captured canonical identity. Verification must
    # not resolve a historical source through today's filesystem aliases.
    key = str(source)
    return exports / (
        hashlib.sha256(key.encode()).hexdigest()[:16] + "-" + source.stem + ".md"
    )


def capture(normalizer, sessions, root, mine=None, source_files=None):
    exports = root / "exports"
    if exports.is_symlink() or exports.resolve() != exports.absolute():
        raise ValueError("Capture exports must stay in the selected state directory")
    exports.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest_file = root / "sources.json"
    manifest, _ = _bounded_json(manifest_file, STATUS_CATALOG_BYTES) if manifest_file.exists() or manifest_file.is_symlink() else ({}, None)
    if not isinstance(manifest, dict):
        raise ValueError("Captured source catalog must be an object")
    latest_file = root / "latest.json"
    latest, _ = _bounded_json(latest_file, STATUS_CATALOG_BYTES) if latest_file.exists() or latest_file.is_symlink() else ({}, None)
    if not isinstance(latest, dict):
        raise ValueError("Capture latest receipt must be an object")
    receipts = latest.get("source_receipts", {})
    if not isinstance(receipts, dict):
        raise ValueError("Invalid existing capture receipt map")
    changed, skipped = 0, 0
    streamed, failures = [], []
    for source in sorted(
        sessions.rglob("*.jsonl") if source_files is None else source_files
    ):
        if source.is_symlink() or not source.resolve().is_relative_to(
            sessions.resolve()
        ):
            skipped += 1
            continue
        stat = source.stat()
        key = str(source.resolve())
        signature = [stat.st_size, stat.st_mtime_ns]
        previous = receipts.get(key)
        if (isinstance(previous, dict) and catalog_signature(previous) == signature
                and manifest.get(key) == signature
                and previous.get("complete_at_capture") is True
                and previous.get("source_identity") == [stat.st_dev, stat.st_ino]):
            continue
        target = export_path(Path(key), exports)
        if stat.st_size > 50 * 1024 * 1024:
            temporary = target.with_suffix(".stream.tmp")
            # A prior interrupted generated candidate is not source history.
            if temporary.exists():
                temporary.unlink()
            try:
                counts = stream_export(source, temporary, stat.st_size)
                if counts is None:
                    skipped += 1
                    continue
                streamed.append({"source": key, **counts})
                if counts["malformed_records"] or counts["partial_tail_bytes"]:
                    failures.append(
                        {
                            "source": key,
                            "error": "Malformed record or incomplete final record",
                            **counts,
                        }
                    )
                os.replace(temporary, target)
                changed += 1
                after = source.stat()
                receipts[key] = source_receipt(
                    signature, stat, after, counts["raw_prefix_sha256"], counts["raw_prefix_bytes"],
                    {"name": target.name, "sha256": counts["export_sha256"],
                     "bytes": counts["export_bytes"], "mtime_ns": target.stat().st_mtime_ns},
                    complete=not counts["malformed_records"] and not counts["partial_tail_bytes"])
                if receipts[key]["complete_at_capture"]:
                    manifest[key] = signature
            except (RuntimeError, OSError, ValueError) as error:
                failures.append({"source": key, "error": str(error)})
            finally:
                if temporary.exists():
                    temporary.unlink()
            continue
        with source.open("rb") as stream:
            raw = stream.read(stat.st_size)
        if len(raw) != stat.st_size:
            failures.append({"source": key, "error": "Source shrank before its selected prefix was read"})
            continue
        health = {"malformed_records": 0, "partial_tail_bytes": 0}
        text = export_text(raw.decode("utf-8"), normalizer, source.name, health)
        if text is None:
            skipped += 1
            continue
        if not target.exists() or target.read_text(encoding="utf-8") != text:
            temporary = target.with_suffix(".tmp")
            with temporary.open("w", encoding="utf-8", newline="") as stream:
                stream.write(text)
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
            changed += 1
        after = source.stat()
        if health["malformed_records"] or health["partial_tail_bytes"]:
            failures.append({"source": key, "error": "Malformed record or incomplete final record", **health})
        export_raw = text.encode("utf-8")
        receipts[key] = source_receipt(
            signature, stat, after, hashlib.sha256(raw).hexdigest(), len(raw),
            {"name": target.name, "sha256": hashlib.sha256(export_raw).hexdigest(),
             "bytes": len(export_raw), "mtime_ns": target.stat().st_mtime_ns},
            complete=not health["malformed_records"] and not health["partial_tail_bytes"])
        if receipts[key]["complete_at_capture"]:
            manifest[key] = signature
    atomic_json(manifest_file, manifest)
    # Always retry mining retained exports, even when sources have not changed.
    result = {
        "time": time.time(),
        "exports_changed": changed,
        "sources_unparsed_or_skipped": skipped,
        "export_files": len(list(exports.glob("*.md"))),
        "streamed_sources": streamed,
        "source_failures": failures,
        "memory_coverage": None,
        "source_receipts": receipts,
        "mining": "not_requested" if mine is None else "pending",
    }
    atomic_json(latest_file, result)
    if mine is not None:
        try:
            result["memory_coverage"] = mine(exports)
            result["mining"] = "native_coverage_checked"
        except Exception:
            result["mining"] = "failed"
            atomic_json(latest_file, result)
            raise
        atomic_json(latest_file, result)
    return result


def coverage_complete(expected, drawers, closets, mtime, version):
    if not expected:
        return True  # Explicit native below-minimum-size case.
    found = {}
    for meta, document in zip(drawers["metadatas"], drawers["documents"]):
        stamp = meta.get("source_mtime")
        # Native/Chroma float round-trip can differ by one epoch-time ULP.
        # Keep a fixed 1us tolerance, plus exact chunk content/index coverage.
        if (
            isinstance(stamp, bool)
            or not isinstance(stamp, (int, float))
            or not math.isfinite(stamp)
        ):
            return False
        if (
            not math.isclose(stamp, mtime, rel_tol=0, abs_tol=0.000001)
            or meta.get("normalize_version", 0) < version
        ):
            return False
        index = meta.get("chunk_index")
        if index in found:
            return False
        found[index] = document
    wanted = {chunk["chunk_index"]: chunk["content"] for chunk in expected}
    if found != wanted:
        return False
    for meta in closets["metadatas"]:
        try:
            filed = datetime.fromisoformat(meta["filed_at"]).timestamp()
        except (KeyError, ValueError, TypeError):
            continue
        if meta.get("drawer_count") == len(expected) and filed >= mtime:
            return True
    return False


def checked_mine(
    exports, expected_for, fetch_drawers, fetch_closets, run_native, version
):
    files = sorted(exports.glob("*.md"))
    incomplete = []
    for source in files:
        expected = expected_for(source)
        if not coverage_complete(
            expected,
            fetch_drawers(source),
            fetch_closets(source),
            source.stat().st_mtime,
            version,
        ):
            # Native miner treats ANY current-mtime drawer as already mined. Invalidate
            # that skip decision on partial coverage, without deleting memory ourselves.
            previous = source.stat().st_mtime
            stamp = time.time_ns()
            if abs(previous - stamp / 1e9) <= 0.01:
                stamp -= 1000000000
            os.utime(source, ns=(stamp, stamp))
            if abs(source.stat().st_mtime - previous) <= 0.01:
                raise RuntimeError(
                    "Export mtime did not invalidate native skip tolerance"
                )
            incomplete.append(source)
    run_native(exports)
    failures = []
    for source in files:
        if not coverage_complete(
            expected_for(source),
            fetch_drawers(source),
            fetch_closets(source),
            source.stat().st_mtime,
            version,
        ):
            failures.append(source.name)
    if failures:
        raise RuntimeError(
            "Native memory coverage incomplete; retained exports retry next tick: "
            + ",".join(failures)
        )
    return {"files_verified": len(files), "files_retried_or_new": len(incomplete)}


def mine(exports, *, cli, palace):
    from mempalace.config import MempalaceConfig
    from mempalace.miner import chunk_text, NORMALIZE_VERSION
    from mempalace.palace import get_collection, get_closets_collection

    config = MempalaceConfig()
    drawers = get_collection(str(palace))
    closets = get_closets_collection(str(palace))

    def expected(source):
        return chunk_text(
            source.read_text(encoding="utf-8").strip(),
            str(source),
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            min_chunk_size=config.min_chunk_size,
        )

    def fetch(source):
        return drawers.get(
            where={"source_file": str(source)}, include=["metadatas", "documents"]
        )

    def fetch_closets(source):
        return closets.get(where={"source_file": str(source)}, include=["metadatas"])

    def native(directory):
        with tempfile.NamedTemporaryFile(dir=exports.parent, prefix="mining-", suffix=".log", delete=False) as log:
            subprocess.run(
            [
                str(cli),
                "--palace",
                str(palace),
                "mine",
                str(directory),
                "--mode",
                "projects",
                "--wing",
                "pi-sessions",
                "--agent",
                "pi-capture",
            ],
                check=True,
                timeout=180,
                stdout=log,
                stderr=subprocess.STDOUT,
            )

    result = checked_mine(
        exports, expected, fetch, fetch_closets, native, NORMALIZE_VERSION
    )
    return result


def absolute_path(value):
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("Use an explicit absolute path")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions-root", type=absolute_path, required=True)
    parser.add_argument("--state-root", type=absolute_path, required=True)
    parser.add_argument("--palace", type=absolute_path)
    parser.add_argument("--mempalace-cli", type=absolute_path)
    parser.add_argument("--status", action="store_true", help="Read bounded existing receipts and metadata without capture or palace access")
    parser.add_argument(
        "--session-file",
        type=absolute_path,
        help="Capture only this explicitly selected current-session JSONL",
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Format/redact locally without mining or embedding work",
    )
    args = parser.parse_args(argv)
    if args.status:
        if args.session_file or args.export_only or args.palace or args.mempalace_cli:
            parser.error("Status accepts only the explicit sessions/state roots; it does not capture or mine")
        print(json.dumps(capture_status(args.sessions_root, args.state_root), ensure_ascii=False))
        return 0
    if args.palace is None or args.mempalace_cli is None:
        parser.error("Capture requires --palace and --mempalace-cli; status does not open memory")
    if sys.platform != "linux":
        parser.error("Pi memory capture requires the reviewed Linux file lock")
    sessions = args.sessions_root.resolve(strict=True)
    if not sessions.is_dir():
        parser.error("--sessions-root must be an existing directory")
    state = args.state_root.parent.resolve(strict=True) / args.state_root.name
    if state.is_symlink():
        parser.error("--state-root must not be a redirected directory")
    palace = args.palace.resolve(strict=False)
    cli = args.mempalace_cli.resolve(strict=True)
    if not cli.is_file():
        parser.error("--mempalace-cli must name the selected executable")
    sources = None
    if args.session_file:
        source = args.session_file
        if (
            source.is_symlink()
            or not source.is_file()
            or source.suffix != ".jsonl"
            or not source.resolve().is_relative_to(sessions)
        ):
            parser.error(
                "--session-file must be a regular JSONL source inside --sessions-root"
            )
        sources = [source]
    os.umask(0o077)
    with singleton(state):
        miner = (
            None
            if args.export_only
            else lambda exports: mine(exports, cli=cli, palace=palace)
        )
        with redirect_stdout(sys.stderr):
            from mempalace.normalize import _try_pi_jsonl
            result = capture(_try_pi_jsonl, sessions, state, mine=miner, source_files=sources)
        # Per-source receipts stay in the existing private latest.json, not a
        # potentially unbounded model-visible callback result.
        print(json.dumps({key: value for key, value in result.items() if key != "source_receipts"}))
        if result["source_failures"]:
            raise RuntimeError(
                "Some source prefixes remain incomplete; see latest.json. Originals retained."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
