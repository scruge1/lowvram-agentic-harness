"""Synthetic native Pi 1.4 structured prompt policy regression for optional Codex consultation."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tests" / "test_pi_codex_sections.mjs"


class PiCodexSectionsTests(unittest.TestCase):
    def test_optional_advice_is_stable_nonblocking_named_policy(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is needed for Pi extension fixture")
        version = subprocess.run([node, "--version"], capture_output=True, text=True, check=True).stdout.strip()
        if tuple(map(int, version.lstrip("v").split(".")[:2])) < (22, 13):
            self.skipTest("Node 22.13+ required")
        proc = subprocess.run(
            [node, "--experimental-vm-modules", str(SCRIPT)],
            cwd=ROOT, text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        record = json.loads(proc.stdout.strip())
        self.assertTrue(record["passed"])
        self.assertEqual(record["transport_calls"], 0)


if __name__ == "__main__":
    unittest.main()
