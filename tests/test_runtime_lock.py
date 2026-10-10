from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from harness.runtime_lock import check_runtime_lock, read_lock

ROOT = Path(__file__).resolve().parents[1]


class RuntimeLockTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def write(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def pin(self, name="example", version="1.0", digest="a"):
        return f"{name}=={version} \\\n    --hash=sha256:{digest * 64}\n"

    def test_shared_hashes_allow_additional_ci_packages(self):
        runtime = self.write("runtime", self.pin("Example_Package"))
        ci = self.write("ci", self.pin("example-package") + self.pin("test-only"))
        self.assertEqual(check_runtime_lock(runtime, ci), 1)

    def test_missing_or_changed_runtime_pin_is_refused(self):
        runtime = self.write("runtime", self.pin())
        for text in (self.pin("another"), self.pin(version="2.0")):
            with self.subTest(text=text), self.assertRaises(ValueError):
                check_runtime_lock(runtime, self.write("ci", text))

    def test_missing_runtime_distribution_hash_is_refused(self):
        runtime = self.write("runtime", self.pin())
        with self.assertRaises(ValueError):
            check_runtime_lock(runtime, self.write("ci", self.pin(digest="b")))

    def test_additional_distribution_hash_is_allowed(self):
        runtime = self.write("runtime", self.pin())
        ci = self.write("ci", self.pin() + "    --hash=sha256:" + "b" * 64 + "\n")
        self.assertEqual(check_runtime_lock(runtime, ci), 1)

    def test_ambiguous_or_unhashed_input_is_refused(self):
        for text in ("", "example==1.0\n", self.pin() + self.pin(),
                     self.pin("Example_Package") + self.pin("example-package"),
                     "-r external.txt\n", "example>=1.0\n",
                     "example==https://invalid.example/package.whl\n",
                     "example==1.0; sys_platform == 'win32'\n",
                     "--hash=sha256:" + "a" * 64 + "\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                read_lock(self.write("invalid", text))

    def test_oversized_input_is_refused(self):
        path = self.write("oversized", self.pin())
        with patch("harness.runtime_lock.MAX_LOCK_BYTES", 8):
            with self.assertRaises(ValueError):
                read_lock(path)

    def test_cli_exit_and_read_only_inputs(self):
        runtime = self.write("runtime", self.pin())
        ci = self.write("ci", self.pin())
        before = (runtime.read_bytes(), ci.read_bytes())
        command = [sys.executable, "-m", "harness.runtime_lock", "--runtime", str(runtime),
                   "--ci", str(ci)]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1 shared packages", result.stdout)
        self.assertEqual((runtime.read_bytes(), ci.read_bytes()), before)
        self.write("ci", self.pin(version="2.0"))
        refused = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("version mismatch", refused.stderr)

    def test_unreadable_cli_input_is_refused(self):
        result = subprocess.run(
            [sys.executable, "-m", "harness.runtime_lock", "--runtime", str(self.root / "missing"),
             "--ci", str(self.root / "also-missing")], cwd=ROOT, capture_output=True,
            text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
