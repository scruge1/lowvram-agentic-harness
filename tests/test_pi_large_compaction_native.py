"""Native Pi 1.4 disposable large-session compaction lifecycle regression.

Only runs with PI_TEST_NATIVE_PACKAGE; no model endpoint, GPU, or external service.
"""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tests/test_pi_large_compaction_native.mjs"


class PiLargeCompactionTests(unittest.TestCase):
    def test_append_only_large_native_session_compaction(self):
        package = os.environ.get("PI_TEST_NATIVE_PACKAGE")
        if not package:
            self.skipTest("Supply the exact installed Pi 1.4 package for native lifecycle qualification")
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is required for native Pi")
        fixture_parent = os.environ.get("PI_TEST_FIXTURE_PARENT") or tempfile.gettempdir()
        result = subprocess.run(
            [node, str(SCRIPT), package, fixture_parent],
            cwd=ROOT, text=True, capture_output=True, timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        evidence = json.loads(result.stdout.strip())
        self.assertEqual(evidence["status"], "success")
        self.assertEqual(evidence["messages_before"], 1200)
        self.assertTrue(evidence["append_only"])
        self.assertEqual(evidence["compaction_records"], 1)
        self.assertTrue(evidence["summary_saved"])
        self.assertTrue(evidence["projection_summary"])
        self.assertEqual([v["kind"] for v in evidence["event_receipt"]], ["before", "after"])
        self.assertEqual(evidence["model_calls"], 0)


if __name__ == "__main__":
    unittest.main()
