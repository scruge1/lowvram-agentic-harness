"""Exercise the generated portable Pi verifier's real subprocess exit contract."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "pi_negative_helper",
    ROOT / "adapters" / "pi" / "project-workflow" / "everyday_workflow.py",
)
HELPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPER)


class PiNegativeControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        # This fixture forwards a real child status. It supplies no production
        # resource ownership, timeout, cancellation, or platform qualification.
        self.guard = self.root / "guard.py"
        self.guard.write_text(
            "import subprocess,sys\n"
            "raise SystemExit(subprocess.run(sys.argv[2:]).returncode)\n",
            encoding="utf-8",
        )
        self.wrapper = self.root / "verifier.py"
        self.wrapper.write_text(HELPER.VERIFIER, encoding="utf-8")
        self.predicate = self.root / "predicate.py"
        self.predicate.write_text(
            "from pathlib import Path\n"
            "raise SystemExit(0 if Path('output.txt').exists() else 1)\n",
            encoding="utf-8",
        )

    def invoke(self, argv, negative=True):
        config = self.root / "check.json"
        config.write_text(json.dumps({
            "guard": str(self.guard),
            "guard_sha256": hashlib.sha256(self.guard.read_bytes()).hexdigest(),
            "argv": argv,
            "timeout": 5,
        }), encoding="utf-8")
        command = [sys.executable, str(self.wrapper), str(config)]
        if negative:
            command.append("--negative-control")
        return subprocess.run(command, cwd=self.root, capture_output=True,
                              text=True, timeout=10)

    def test_real_output_predicate_passes_positive_and_rejects_empty_directory(self):
        (self.root / "output.txt").write_text("accepted fixture", encoding="utf-8")
        argv = [sys.executable, str(self.predicate)]
        self.assertEqual(self.invoke(argv, negative=False).returncode, 0)
        self.assertEqual(self.invoke(argv).returncode, 0)

    def test_relative_missing_script_is_not_semantic_rejection(self):
        argv = [sys.executable, self.predicate.name]
        self.assertEqual(self.invoke(argv, negative=False).returncode, 1)
        result = self.invoke(argv)
        self.assertEqual(result.returncode, 1)
        self.assertIn("exit 2", result.stderr)

    def test_non_rejection_statuses_fail_negative_control(self):
        # These are actual child exit statuses, not real timeout/cancel events.
        for status in (0, 2, 3, 124, 125, 130):
            with self.subTest(status=status):
                result = self.invoke([sys.executable, "-c",
                                      "raise SystemExit(%d)" % status])
                self.assertEqual(result.returncode, 1)
                self.assertIn("exit " + str(status), result.stderr)


if __name__ == "__main__":
    unittest.main()
