"""Private transcript export conservation and native readback admission controls."""

import importlib.util
import json
from pathlib import Path
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
