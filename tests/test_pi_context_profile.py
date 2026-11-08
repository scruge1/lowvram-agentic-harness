"""Read-only Pi context telemetry contract; no model or provider call."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tests/test_pi_context_profile.mjs"


class PiContextProfileTests(unittest.TestCase):
    def test_telemetry_never_exposes_prompt_or_requires_persistence(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node required to qualify native Pi extension")
        version = subprocess.run(
            [node, "--version"], capture_output=True, text=True, check=True
        ).stdout.strip()
        if tuple(map(int, version.lstrip("v").split(".")[:2])) < (22, 13):
            self.skipTest("Node 22.13 or newer required")
        output = subprocess.run(
            [node, "--experimental-vm-modules", str(SCRIPT)],
            cwd=ROOT, capture_output=True, text=True, timeout=45,
        )
        self.assertEqual(output.returncode, 0, output.stdout + output.stderr)
        result = json.loads(output.stdout)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["capability_stable"])
        self.assertTrue(result["default_history_unchanged"])
        self.assertEqual(result["opt_in_appends"], 1)
        self.assertEqual(result["network_calls"], 0)


if __name__ == "__main__":
    unittest.main()
