"""Private transcript export conservation and native readback admission controls."""

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "adapters" / "pi" / "memory-capture" / "capture.py"
SPEC = importlib.util.spec_from_file_location("pi_memory_capture_export", SOURCE)
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


def transcript(records):
    return (
        "\n".join(
            json.dumps(record)
            for record in [{"type": "session", "version": 3}, *records]
        )
        + "\n"
    )


def message(role, text):
    return {
        "type": "message",
        "message": {"role": role, "content": [{"type": "text", "text": text}]},
    }


def native_formatter_fixture():
    module = ModuleType("mempalace.normalize")
    module._extract_content = (
        lambda value: value
        if isinstance(value, str)
        else "\n".join(
            block.get("text", "") for block in value if block.get("type") == "text"
        )
    )
    module._messages_to_transcript = (
        lambda values: "\n".join(role + ": " + text for role, text in values) + "\n"
    )
    return {"mempalace": ModuleType("mempalace"), "mempalace.normalize": module}


class PiMemoryCaptureTests(unittest.TestCase):
    def receipt(self, state, source):
        return json.loads((state / "latest.json").read_text())["source_receipts"][str(source)]

    def fixture(self, directory):
        root = Path(directory).resolve()
        sessions = root / "sessions"
        sessions.mkdir()
        source = sessions / "current.jsonl"
        source.write_text(transcript([message("user", "Synthetic owned history")]), encoding="utf-8")
        state = root / "state"
        result = capture.capture(lambda _: "user: Synthetic owned history", sessions, state, source_files=[source])
        return sessions, source, state, result

    def test_capture_receipts_bind_actual_raw_prefix_and_export_without_new_state_store(self):
        with tempfile.TemporaryDirectory() as directory:
            sessions, source, state, _ = self.fixture(directory)
            row = self.receipt(state, source)
            self.assertEqual(row["schema"], capture.SOURCE_SCHEMA)
            self.assertEqual(row["raw_prefix"]["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(row["raw_prefix"]["bytes"], source.stat().st_size)
            exported = state / "exports" / row["export"]["name"]
            self.assertEqual(row["export"]["sha256"], hashlib.sha256(exported.read_bytes()).hexdigest())
            self.assertTrue(row["complete_at_capture"])
            self.assertEqual({p.name for p in state.iterdir()}, {"sources.json", "latest.json", "exports"})
            legacy_row = json.loads((state / "sources.json").read_text())[str(source)]
            self.assertEqual(legacy_row, [source.stat().st_size, source.stat().st_mtime_ns])
            status = capture.capture_status(sessions, state)
            self.assertEqual(status["sources"][0]["state"], "metadata_matches_receipt_bytes_not_reverified")
            self.assertFalse(status["current_raw_bytes_verified"])

    def test_status_reopen_is_readonly_and_does_not_read_raw_history_or_claim_cryptographic_freshness(self):
        with tempfile.TemporaryDirectory() as directory:
            sessions, source, state, _ = self.fixture(directory)
            before = {p: p.read_bytes() for p in state.rglob("*") if p.is_file()}
            saved = source.stat()
            raw = source.read_bytes()
            source.write_bytes(raw.replace(b"owned", b"other"))  # Same byte count, deliberately restored mtime.
            os.utime(source, ns=(saved.st_atime_ns, saved.st_mtime_ns))
            original_open = Path.open
            original_os_open = capture.os.open

            def readonly_metadata(path, *args, **kwargs):
                self.assertNotEqual(path, source, "Status must not read raw source bodies")
                return original_open(path, *args, **kwargs)

            def readonly_descriptor(path, *args, **kwargs):
                self.assertNotEqual(Path(path), source, "Status must not open a raw-source descriptor")
                return original_os_open(path, *args, **kwargs)

            with mock.patch.object(Path, "open", readonly_metadata), mock.patch.object(capture.os, "open", readonly_descriptor):
                first = capture.capture_status(sessions, state)
                second = capture.capture_status(sessions, state)
            self.assertEqual(first["catalog_sha256"], second["catalog_sha256"])
            self.assertEqual(first["sources"][0]["state"], "metadata_matches_receipt_bytes_not_reverified")
            self.assertFalse(first["sources"][0]["current_raw_bytes_verified"])
            self.assertNotEqual(first["sources"][0]["raw_prefix_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_growing_source_retains_only_observed_prefix_and_explicit_next_capture_catches_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            sessions = root / "sessions"
            sessions.mkdir()
            source = sessions / "growing.jsonl"
            old = transcript([message("user", "First synthetic prompt")]).encode()
            source.write_bytes(old)

            def grow(_):
                with source.open("ab") as stream:
                    stream.write((json.dumps(message("assistant", "Later synthetic reply")) + "\n").encode())
                return "user: First synthetic prompt"

            state = root / "state"
            capture.capture(grow, sessions, state, source_files=[source])
            row = self.receipt(state, source)
            self.assertEqual(row["raw_prefix"]["sha256"], hashlib.sha256(old).hexdigest())
            self.assertFalse(row["complete_at_capture"])
            status = capture.capture_status(sessions, state)["sources"][0]
            self.assertEqual(status["state"], "unobserved_tail")
            self.assertEqual(status["unobserved_tail_bytes"], source.stat().st_size - len(old))
            grown = source.read_bytes()
            capture.capture(lambda _: "user: First synthetic prompt\nassistant: Later synthetic reply", sessions, state, source_files=[source])
            row = self.receipt(state, source)
            self.assertTrue(row["complete_at_capture"])
            self.assertEqual(row["raw_prefix"]["sha256"], hashlib.sha256(grown).hexdigest())
            self.assertEqual(source.read_bytes(), grown)

    def test_repeat_capture_is_noop_without_refreshing_receipt_age_but_retries_existing_miner(self):
        with tempfile.TemporaryDirectory() as directory:
            sessions, source, state, _ = self.fixture(directory)
            before = (state / "sources.json").read_bytes()
            before_receipt = self.receipt(state, source)
            miner = mock.Mock(return_value={"fixture": True})
            result = capture.capture(lambda _: self.fail("Unchanged source must not be reparsed"),
                                     sessions, state, mine=miner, source_files=[source])
            self.assertEqual(result["exports_changed"], 0)
            self.assertEqual((state / "sources.json").read_bytes(), before)
            self.assertEqual(self.receipt(state, source), before_receipt)
            miner.assert_called_once_with(state / "exports")

    def test_mining_failure_preserves_capture_receipts_without_claiming_native_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            sessions, source, state, _ = self.fixture(directory)
            before = self.receipt(state, source)
            with self.assertRaisesRegex(RuntimeError, "Controlled miner failure"):
                capture.capture(lambda _: self.fail("Unchanged source must not be reread"), sessions, state,
                                mine=mock.Mock(side_effect=RuntimeError("Controlled miner failure")), source_files=[source])
            latest = json.loads((state / "latest.json").read_text())
            self.assertEqual(latest["mining"], "failed")
            self.assertIsNone(latest["memory_coverage"])
            self.assertEqual(self.receipt(state, source), before)
            self.assertEqual(capture.capture_status(sessions, state)["last_capture"]["mining"], "failed")

    def test_malformed_metadata_refuses_capture_before_source_read_or_mining(self):
        for filename in ("sources.json", "latest.json"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                sessions, source, state, _ = self.fixture(directory)
                (state / filename).write_text("[]")
                before = {p: p.read_bytes() for p in state.rglob("*") if p.is_file()}
                miner = mock.Mock()
                with self.assertRaisesRegex(ValueError, "must be an object"):
                    capture.capture(lambda _: self.fail("No source read on invalid metadata"),
                                    sessions, state, mine=miner, source_files=[source])
                miner.assert_not_called()
                self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_legacy_catalog_rows_are_not_upgraded_without_selected_recapture(self):
        with tempfile.TemporaryDirectory() as directory:
            sessions, source, state, _ = self.fixture(directory)
            legacy = [source.stat().st_size, source.stat().st_mtime_ns]
            (state / "sources.json").write_text(json.dumps({str(source): legacy}))
            old_latest = json.loads((state / "latest.json").read_text())
            old_latest.pop("source_receipts")  # Retained older capture replaces its ordinary latest receipt.
            (state / "latest.json").write_text(json.dumps(old_latest))
            row = capture.capture_status(sessions, state)["sources"][0]
            self.assertEqual(row["state"], "legacy_receipt_unverifiable_until_explicit_recapture")
            self.assertNotIn("raw_prefix_sha256", row)
            capture.capture(lambda _: "user: Synthetic owned history", sessions, state, source_files=[source])
            self.assertEqual(self.receipt(state, source)["schema"], capture.SOURCE_SCHEMA)
            self.assertEqual(json.loads((state / "sources.json").read_text())[str(source)], legacy)

    def test_status_limits_catalog_and_serialized_output_without_scanning_unknown_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            sessions, source, state, _ = self.fixture(directory)
            catalog = {str(sessions / (str(i) + "-unread.jsonl")): [1, 1] for i in range(100)}
            catalog[str(source)] = [source.stat().st_size, source.stat().st_mtime_ns]
            (state / "sources.json").write_text(json.dumps(catalog))
            status = capture.capture_status(sessions, state)
            self.assertTrue(status["truncated"])
            self.assertEqual(status["catalog_known_sources"], 101)
            self.assertEqual(status["omitted_known_sources"], 101 - len(status["sources"]))
            self.assertLessEqual(len(json.dumps(status, ensure_ascii=False).encode()), capture.STATUS_OUTPUT_BYTES)
            self.assertEqual(status["new_sources_discovery"], "not_scanned")
            (state / "sources.json").write_bytes(b" " * (capture.STATUS_CATALOG_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "byte limit"):
                capture.capture_status(sessions, state)

    def test_status_refuses_redirected_metadata_and_does_not_inspect_outside_root(self):
        with tempfile.TemporaryDirectory() as directory:
            sessions, source, state, _ = self.fixture(directory)
            outside = Path(directory).resolve() / "outside.jsonl"
            outside.write_bytes(b"Private synthetic unrelated data")
            (state / "sources.json").write_text(json.dumps({str(outside): [1, 1]}))
            status = capture.capture_status(sessions, state)
            self.assertEqual(status["sources"][0]["state"], "outside_selected_root_not_inspected")
            self.assertNotIn("source", status["sources"][0])
            saved = (state / "sources.json").read_bytes()
            (state / "sources.json").unlink()
            try:
                (state / "sources.json").symlink_to(outside)
            except OSError:
                self.skipTest("This platform does not permit owned symlink creation")
            with self.assertRaisesRegex(ValueError, "Redirected"):
                capture.capture_status(sessions, state)
            self.assertEqual(outside.read_bytes(), b"Private synthetic unrelated data")
            self.assertTrue(saved)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "This platform has no owned FIFO control")
    def test_status_rejects_fifo_catalog_before_a_blocking_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            state = root / "state"
            state.mkdir()
            os.mkfifo(state / "sources.json")
            with self.assertRaisesRegex(ValueError, "regular unique"):
                capture.capture_status(root / "sessions", state)

    def test_large_stream_interruption_then_explicit_catchup_preserves_raw_and_prefix_hash(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(sys.modules, native_formatter_fixture()):
            root = Path(directory).resolve()
            sessions = root / "sessions"
            sessions.mkdir()
            source = sessions / "large.jsonl"
            padding = (json.dumps({"type": "synthetic_metadata", "not_exported": "x" * (26 * 1024 * 1024)}) + "\n").encode()
            raw = transcript([message("user", "Readable synthetic prompt"),
                              message("assistant", "Readable synthetic reply")]).encode() + padding + padding
            source.write_bytes(raw)
            original = hashlib.sha256(raw).hexdigest()
            state = root / "state"
            # Exercise the actual streaming reader. The first readable pair
            # reaches its formatter before either large metadata record is read.
            with mock.patch.object(sys.modules["mempalace.normalize"], "_messages_to_transcript",
                                   side_effect=RuntimeError("Controlled formatter interruption during stream")):
                failed = capture.capture(lambda _: self.fail("Large stream must not use whole-file formatter"),
                                         sessions, state, source_files=[source])
            self.assertEqual(len(failed["source_failures"]), 1)
            self.assertEqual(json.loads((state / "sources.json").read_text()), {})
            result = capture.capture(lambda _: self.fail("Large stream must not use whole-file formatter"),
                                     sessions, state, source_files=[source])
            self.assertEqual(result["source_failures"], [])
            row = self.receipt(state, source)
            self.assertTrue(row["complete_at_capture"])
            self.assertEqual(row["raw_prefix"], {"sha256": original, "bytes": len(raw),
                "authority": "bytes read during capture, not current-source verification"})
            exported = state / "exports" / row["export"]["name"]
            self.assertEqual(row["export"]["sha256"], hashlib.sha256(exported.read_bytes()).hexdigest())
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original)
            self.assertNotIn("not_exported", exported.read_text(encoding="utf-8"))

    def test_status_cli_needs_no_palace_or_formatter_and_creates_no_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            result = subprocess.run([sys.executable, "-I", "-B", str(SOURCE), "--status", "--sessions-root", str(root / "sessions"),
                                     "--state-root", str(root / "missing-state")], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "not_observed")
            self.assertEqual(list(root.iterdir()), [])

    def test_platform_refusal_precedes_any_output_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "not-created"
            with mock.patch.object(capture.sys, "platform", "win32"):
                with self.assertRaisesRegex(RuntimeError, "Linux"):
                    with capture.singleton(state):
                        self.fail("Unsupported platform admitted a writer")
            self.assertFalse(state.exists())

    def test_selected_source_does_not_import_other_sessions_or_change_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root / "sessions"
            sessions.mkdir()
            selected, other = sessions / "current.jsonl", sessions / "older.jsonl"
            selected.write_text(
                transcript([message("user", "Current synthetic prompt")]),
                encoding="utf-8",
            )
            other.write_text(
                transcript([message("user", "Unselected old prompt")]), encoding="utf-8"
            )
            originals = {path: path.read_bytes() for path in (selected, other)}
            result = capture.capture(
                lambda _: "user: Current synthetic prompt",
                sessions,
                root / "state",
                source_files=[selected],
            )
            self.assertEqual(result["export_files"], 1)
            catalog = json.loads((root / "state" / "sources.json").read_text())
            self.assertEqual(set(catalog), {str(selected.resolve())})
            self.assertEqual({path: path.read_bytes() for path in originals}, originals)
            self.assertNotIn(
                "Unselected",
                next((root / "state" / "exports").glob("*.md")).read_text(),
            )

    def test_streaming_single_prompt_and_partial_prefix_keep_original_bytes(self):
        # Explicit formatter fixture tests streaming boundaries; separate native
        # MemPalace qualification establishes the formatter API and semantics.
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.dict(sys.modules, native_formatter_fixture()),
        ):
            root = Path(directory)
            source, output = root / "one.jsonl", root / "export.md"
            raw = (
                transcript([message("user", "One actual readable prompt")]).encode()
                + b'{"type":"message"'
            )
            source.write_bytes(raw)
            result = capture.stream_export(source, output, len(raw))
            self.assertEqual(result["dialogue_messages"], 1)
            self.assertGreater(result["partial_tail_bytes"], 0)
            self.assertIn("One actual readable prompt", output.read_text())
            self.assertEqual(source.read_bytes(), raw)
            self.assertEqual(result["raw_prefix_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(result["export_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())

    def test_no_readable_dialogue_remains_raw_only(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.dict(sys.modules, native_formatter_fixture()),
        ):
            root = Path(directory)
            source, output = root / "thinking.jsonl", root / "export.md"
            raw = transcript(
                [
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "thinking",
                                    "thinking": "PRIVATE_REASONING_MUST_STAY_RAW",
                                }
                            ],
                        },
                    }
                ]
            ).encode()
            source.write_bytes(raw)
            self.assertIsNone(capture.stream_export(source, output, len(raw)))
            self.assertFalse(output.exists())
            self.assertEqual(source.read_bytes(), raw)

    def test_coverage_requires_exact_unique_chunks_and_fresh_closet(self):
        expected = [{"chunk_index": 0, "content": "Canonical text"}]
        drawers = {
            "metadatas": [
                {"chunk_index": 0, "source_mtime": 0.0, "normalize_version": 4}
            ],
            "documents": ["Canonical text"],
        }
        closets = {
            "metadatas": [{"drawer_count": 1, "filed_at": "1970-01-01T00:00:01+00:00"}]
        }
        self.assertTrue(capture.coverage_complete(expected, drawers, closets, 0.0, 4))
        self.assertFalse(
            capture.coverage_complete(expected, drawers, {"metadatas": []}, 0.0, 4)
        )
        changed = {**drawers, "documents": ["Different text"]}
        self.assertFalse(capture.coverage_complete(expected, changed, closets, 0.0, 4))
        duplicate = {key: value * 2 for key, value in drawers.items()}
        self.assertFalse(
            capture.coverage_complete(expected, duplicate, closets, 0.0, 4)
        )

    def test_historical_export_identity_does_not_require_original_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "removed-original.jsonl"
            self.assertFalse(old.exists())
            path = capture.export_path(old, root / "exports")
            self.assertTrue(path.name.endswith("-removed-original.md"))
            self.assertFalse(old.exists())


if __name__ == "__main__":
    unittest.main()
