"""Portable source-bound Pi system_tool_query model projection controls."""
from pathlib import Path
import json
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "adapters/pi/project-workflow/test-system-tool-query-projection.mjs"


class SystemToolProjectionTests(unittest.TestCase):
    def test_bounded_source_pinned_lossless_paging(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node required for the Pi projection contract")
        result = subprocess.run(
            [node, str(SCRIPT)], cwd=ROOT, capture_output=True, text=True, timeout=30
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["result"], "PASS")
        self.assertEqual(receipt["result_count"], 80)
        self.assertLessEqual(receipt["first_page_bytes"], 4096)
        self.assertGreater(receipt["raw_bytes"], receipt["first_page_bytes"])

    def test_actual_extension_transport_preserves_backend_evidence(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node required for actual TypeScript extension integration")
        version = subprocess.run(
            [node, "--version"], capture_output=True, text=True, check=True
        ).stdout.strip()
        if tuple(int(part) for part in version.lstrip("v").split(".")[:2]) < (22, 13):
            self.skipTest("Node 22.13+ required for TypeScript stripping")
        script = ROOT / "adapters/pi/project-workflow/test-system-tool-integration.mjs"
        result = subprocess.run(
            [node, "--experimental-vm-modules", str(script)], cwd=ROOT,
            capture_output=True, text=True, timeout=30
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["result"], "PASS")
        self.assertTrue(receipt["backend_preserved"])
        self.assertTrue(receipt["helper_drift_refused"])
        self.assertEqual(receipt["real_model_calls"], 0)


if __name__ == "__main__":
    unittest.main()
