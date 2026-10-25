"""Run the portable model-view contract fixtures without third-party packages."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PiKanbanProjectionTests(unittest.TestCase):
    def test_bounded_model_projection_retains_controller_evidence(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is required for the Pi reply projection tests")
        version = subprocess.run([node, "--version"], capture_output=True, text=True,
                                 timeout=5, check=True).stdout.strip()
        if int(version.lstrip("v").split(".")[0]) < 18:
            self.skipTest("Node18+ is required for the portable projection fixture syntax")
        result = subprocess.run([node, str(ROOT / "tests/test_pi_kanban_projection.mjs")],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(receipt["failed"], 0)
        self.assertEqual(receipt["passed"], 21)
        self.assertEqual(len(receipt["tests"]), receipt["passed"])
        self.assertIn("not backend transport/host details", receipt["scope"])


if __name__ == "__main__":
    unittest.main()
