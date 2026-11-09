"""Source-backed public media proof: run real offline fixture, refuse false authority."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
MEDIA = REPO / "examples/media/source-backed-workflow/capture.py"
spec = importlib.util.spec_from_file_location("public_media_fixture", MEDIA)
assert spec and spec.loader
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class MediaFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = capture.capture(REPO)

    def test_actual_scripted_retry_rejected_then_verified(self):
        data = self.data
        self.assertEqual(data["schema"], "stuaim-offline-workflow-capture/v1")
        self.assertEqual(data["kind"], "scripted_offline_fixture")
        self.assertFalse(data["live_model_invoked"])
        self.assertFalse(data["product_ui_captured"])
        self.assertEqual(data["project"], "enforced-task-example")
        self.assertEqual(data["task"], "offline-enforced-example")
        self.assertEqual(
            [step["step"] for step in data["workflow"]],
            [
                "source_bound_task",
                "worker_attempt_1",
                "corrective_feedback",
                "worker_attempt_2",
                "independent_project_acceptance",
            ],
        )
        self.assertEqual(data["workflow"][1]["status"], "rejected")
        self.assertEqual(data["workflow"][1]["verifier_exit_code"], 1)
        self.assertEqual(data["workflow"][3]["status"], "accepted")
        self.assertEqual(data["workflow"][3]["verifier_exit_code"], 0)
        self.assertEqual(data["workflow"][4]["state"], "tested")
        self.assertTrue(data["result"]["accepted"])
        self.assertTrue(data["result"]["complete"])
        self.assertEqual(data["result"]["authority_cap"], "tested")
        self.assertEqual(data["result"]["stage_state"], "verified")

    def test_published_source_pins_and_scoping(self):
        published = json.loads(
            (REPO / "docs/media/workflow-evidence.json").read_text(encoding="utf-8")
        )
        self.assertEqual(self.data["source_hash_mode"], "canonical_lf_text_sha256")
        self.assertEqual(published["source_hash_mode"], self.data["source_hash_mode"])
        self.assertEqual(self.data["source"], published["source"])
        self.assertEqual(
            self.data["result"]["result_text"], published["result"]["result_text"]
        )
        self.assertEqual(self.data["workflow"], published["workflow"])
        self.assertEqual(
            self.data["result"]["authority_cap"], published["result"]["authority_cap"]
        )
        self.assertNotIn("blessed", self.data["result"]["authority_cap"])
        for relative, digest in self.data["source"].items():
            self.assertFalse(Path(relative).is_absolute())
            self.assertEqual(
                hashlib.sha256(
                    (REPO / relative).read_bytes().replace(b"\r\n", b"\n")
                ).hexdigest(),
                digest,
            )

    def test_public_output_does_not_expose_original_run_details(self):
        payload = json.dumps(self.data, sort_keys=True)
        published = (REPO / "docs/media/workflow-evidence.json").read_text(
            encoding="utf-8"
        )
        for value in (payload, published):
            for prohibited in (
                "/home/",
                "/tmp/",
                "process_trace",
                "run_id",
                "worker_pid",
                "model_api_key",
                "customer_email",
                "conversation_body",
                "original_session",
            ):
                self.assertNotIn(prohibited, value)
            self.assertNotRegex(value, r"[A-Za-z]:\\")
            self.assertIn('"live_model_invoked": false', value)
            self.assertIn('"product_ui_captured": false', value)
        self.assertEqual(len(self.data["source"]), 5)

    def test_invalid_source_directory_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "real public harness"):
                capture.capture(Path(tmp))


if __name__ == "__main__":
    unittest.main()
