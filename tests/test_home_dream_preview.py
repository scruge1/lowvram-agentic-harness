"""Owner-bound, read-only Home CLI integration for the source-checked Dream preview."""

from contextlib import nullcontext, redirect_stdout, redirect_stderr
from io import BytesIO, StringIO, TextIOWrapper
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from harness import home as agent_home
from harness import home_entry
from harness import claude_memory


class HomeDreamPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="home-dream-preview-")
        root = Path(self.temp.name).resolve(strict=True)
        self.home = root / "home"
        self.home.mkdir()
        (self.home / "home.json").write_text(
            json.dumps({"schema": "agent-home/v1", "home": str(self.home)}),
            encoding="utf-8",
        )
        self.project = root / "project"
        self.project.mkdir()
        (self.project / ".icm").mkdir()
        self.pid = "p_home_dream_fixture_0123456789"
        identity = {
            "project_id": self.pid,
            "board_id": "project:" + self.pid,
            "canonical_root": str(self.project),
            "state_root": str(self.home / "state/projects" / self.pid),
        }
        (self.project / ".icm/project.json").write_text(
            json.dumps(identity), encoding="utf-8"
        )
        self.claim = "Project review requires verification against original evidence."
        self.source = self.project / "CURRENT.md"
        self.source.write_text("# Current\n" + self.claim + "\n", encoding="utf-8")
        self.packet = {
            "schema": "agent-home-dream-evidence/v1",
            "project_id": self.pid,
            "evidence": [
                {
                    "project_id": self.pid,
                    "source_id": "icm-source-one",
                    "source_kind": "icm",
                    "claim_key": "project.provenance",
                    "claim_text": self.claim,
                    "source_path": str(self.source),
                    "source_sha256": hashlib.sha256(
                        self.source.read_bytes()
                    ).hexdigest(),
                    "source_quote": self.claim,
                    "observed_at": "2026-11-08T18:00:00Z",
                    "verification": "retrieval_only",
                }
            ],
        }

    def tearDown(self):
        self.temp.cleanup()

    def call(self, operation, *, packet=None, bound_home=None):
        raw = json.dumps(self.packet if packet is None else packet).encode()
        stdin = TextIOWrapper(BytesIO(raw), encoding="utf-8")
        stdout, stderr = StringIO(), StringIO()
        with (
            mock.patch.object(
                agent_home, "load", return_value=(self.home, {})
            ) as loaded,
            mock.patch.object(
                home_entry, "consumer", return_value=nullcontext()
            ) as consumer,
            mock.patch.object(
                claude_memory,
                "invoke",
                side_effect=AssertionError("Claude-mem may not be invoked"),
            ) as observer,
            mock.patch("sys.stdin", stdin),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            result = agent_home.main(
                ["--home", str(self.home), "memory", *operation],
                bound_home=bound_home,
            )
        return result, stdout.getvalue(), stderr.getvalue(), consumer, loaded, observer

    def test_actual_existing_home_consumer_without_staging_a_new_memory_store(self):
        # Exercise the actual Home identity and consumer implementation on
        # this OS. The separate lifecycle-guard tests cover pinned Linux FDs.
        stream = TextIOWrapper(
            BytesIO(json.dumps(self.packet).encode()), encoding="utf-8"
        )
        output, error = StringIO(), StringIO()
        before = hashlib.sha256((self.home / "home.json").read_bytes()).hexdigest()
        with (
            mock.patch("sys.stdin", stream),
            mock.patch.object(
                claude_memory,
                "invoke",
                side_effect=AssertionError("unrelated observer"),
            ),
            redirect_stdout(output),
            redirect_stderr(error),
        ):
            rc = agent_home.main(
                [
                    "--home",
                    str(self.home),
                    "memory",
                    "dream-preview",
                    "--project",
                    str(self.project),
                ],
                bound_home=self.home,
            )
        self.assertEqual(rc, 0, error.getvalue())
        report = json.loads(output.getvalue())
        self.assertEqual(report["status"], "CANDIDATES_NOT_PROMOTED")
        self.assertEqual(report["exact_source_count"], 1)
        self.assertEqual(
            hashlib.sha256((self.home / "home.json").read_bytes()).hexdigest(),
            before,
        )
        self.assertFalse((self.home / "memory").exists(), "No new memory store")
        self.assertFalse((self.home / "agent").exists(), "No Pi session writer")

    def test_only_reviewed_project_and_native_consumer_no_new_store(self):
        before = {
            p.relative_to(self.temp.name).as_posix(): hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
            for p in Path(self.temp.name).rglob("*")
            if p.is_file()
        }
        code, output, error, consumer, loaded, observer = self.call(
            ["dream-preview", "--project", str(self.project)]
        )
        self.assertEqual(code, 0, error)
        report = json.loads(output)
        self.assertEqual(report["schema"], "agent-home-dream-review/v1")
        self.assertEqual(report["status"], "CANDIDATES_NOT_PROMOTED")
        self.assertEqual(report["last_known_best"], "UNASSESSED_NOT_INFERRED")
        self.assertEqual(report["exact_source_count"], 1)
        self.assertEqual(report["authority"], "retrieval_only")
        self.assertNotIn(self.claim, output)
        self.assertNotIn(str(self.project), output)
        consumer.assert_called_once_with(self.home)
        loaded.assert_called_once()
        observer.assert_not_called()
        after = {
            p.relative_to(self.temp.name).as_posix(): hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
            for p in Path(self.temp.name).rglob("*")
            if p.is_file()
        }
        self.assertEqual(
            before, after, "Preview cannot mutate source or create a second store"
        )

    def test_missing_project_or_query_refuses_before_home_consumer(self):
        for options in (
            ["dream-preview"],
            ["dream-preview", "--project", str(self.project), "--query", "extra"],
        ):
            with self.subTest(options=options):
                code, out, error, consumer, loaded, observer = self.call(options)
                self.assertEqual(code, 1)
                self.assertEqual(out, "")
                self.assertIn("failed", error)
                consumer.assert_not_called()
                loaded.assert_not_called()
                observer.assert_not_called()

    def test_normal_memory_modes_never_accept_project_injection(self):
        for operation in ("start", "stop", "status", "search"):
            with self.subTest(operation=operation):
                code, output, error, consumer, loaded, observer = self.call(
                    [operation, "--project", str(self.project)]
                )
                self.assertEqual(code, 1)
                self.assertEqual(output, "")
                self.assertIn("project is reserved", error)
                consumer.assert_not_called()
                observer.assert_not_called()

    def test_foreign_project_packet_fails_inside_original_source_review(self):
        invalid = dict(self.packet, project_id="p_foreign")
        code, output, _err, consumer, _loaded, observer = self.call(
            ["dream-preview", "--project", str(self.project)], packet=invalid
        )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output)["status"], "unavailable")
        self.assertNotIn(self.claim, output)
        consumer.assert_called_once()
        observer.assert_not_called()

    def test_lifecycle_home_binding_cannot_be_bypassed(self):
        another = self.home.parent / "other-home"
        another.mkdir()
        code, output, error, consumer, loaded, observer = self.call(
            ["dream-preview", "--project", str(self.project)], bound_home=another
        )
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertIn("different agent home", error)
        consumer.assert_not_called()
        loaded.assert_not_called()
        observer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
