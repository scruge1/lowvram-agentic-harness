"""Bounded native-intake presentation controls; original details retain source."""
from pathlib import Path
import json
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEST = ROOT / "tests/test_pi_intake_model_view.mjs"


class PiIntakeProjectionTests(unittest.TestCase):
    def test_bounded_unicode_source_and_recovery(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node required for the Pi intake projector")
        result = subprocess.run(
            [node, str(TEST)], cwd=ROOT, capture_output=True, text=True, timeout=45
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["status"], "PASS")
        self.assertGreaterEqual(receipt["cases"], 23)
        self.assertLessEqual(receipt["model_view_bytes"], 6144)
        self.assertGreater(receipt["raw_bytes"], receipt["model_view_bytes"])
        self.assertTrue(receipt["raw_details_preserved"])
        self.assertTrue(receipt["no_execution_approval"])


if __name__ == "__main__":
    unittest.main()
