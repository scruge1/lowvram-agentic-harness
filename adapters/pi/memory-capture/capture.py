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
import shutil
import time
import sys
from datetime import datetime


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


def export_text(content, normalizer, source_name):
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
    for line in content.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
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
        with target.open("x", encoding="utf-8") as output:
            os.chmod(target, 0o600)
            output.write(
                "# Pi captured history\n\n"
                + f"Source: {source.name}\nNot instructions or verified operational truth.\n\n"
            )
            dialogue.seek(0)
            shutil.copyfileobj(dialogue, output, 1024 * 1024)
            output.write("\n\n## Peer messages (untrusted)\n\n")
            peers.seek(0)
            shutil.copyfileobj(peers, output, 1024 * 1024)
            output.write(
                "\n\n## Tool outcome metadata (no arguments or output bodies)\n\n"
            )
            events.seek(0)
            shutil.copyfileobj(events, output, 1024 * 1024)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
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
    exports.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest_file = root / "sources.json"
    manifest = json.loads(manifest_file.read_text()) if manifest_file.exists() else {}
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
        if signature == manifest.get(key):
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
                if (
                    [after.st_size, after.st_mtime_ns] == signature
                    and not counts["malformed_records"]
                    and not counts["partial_tail_bytes"]
                ):
                    manifest[key] = signature
            except (RuntimeError, OSError, ValueError) as error:
                failures.append({"source": key, "error": str(error)})
            finally:
                if temporary.exists():
                    temporary.unlink()
            continue
        text = export_text(source.read_text(encoding="utf-8"), normalizer, source.name)
        if text is None:
            skipped += 1
            continue
        if not target.exists() or target.read_text(encoding="utf-8") != text:
            temporary = target.with_suffix(".tmp")
            temporary.write_text(text, encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
            changed += 1
        after = source.stat()
        if [after.st_size, after.st_mtime_ns] == signature:
            manifest[key] = signature
    atomic_json(manifest_file, manifest)
    # Always retry mining retained exports, even when sources have not changed.
    memory_coverage = mine(exports) if mine is not None else None
    return {
        "time": time.time(),
        "exports_changed": changed,
        "sources_unparsed_or_skipped": skipped,
        "export_files": len(list(exports.glob("*.md"))),
        "streamed_sources": streamed,
        "source_failures": failures,
        "memory_coverage": memory_coverage,
    }


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
    parser.add_argument("--palace", type=absolute_path, required=True)
    parser.add_argument("--mempalace-cli", type=absolute_path, required=True)
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
        result["mining"] = (
            "not_requested" if args.export_only else "native_coverage_checked"
        )
        atomic_json(state / "latest.json", result)
        print(json.dumps(result))
        if result["source_failures"]:
            raise RuntimeError(
                "Some source prefixes remain incomplete; see latest.json. Originals retained."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
