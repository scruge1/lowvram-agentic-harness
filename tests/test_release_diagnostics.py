import sys
import unittest
import contextlib
import io

from scripts.verify_ssot_release import run


class ReleaseDiagnosticsTests(unittest.TestCase):
    def test_timeout_preserves_output_and_fails(self):
        code = (
            "import sys,time; "
            "print('stdout-before-timeout',flush=True); "
            "print('stderr-before-timeout',file=sys.stderr,flush=True); "
            "time.sleep(60)"
        )
        diagnostic = io.StringIO()
        with contextlib.redirect_stderr(diagnostic):
            result = run([sys.executable, "-c", code], timeout=2)
        self.assertEqual(result["exit_code"], 124)
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["timeout_seconds"], 2)
        self.assertIn("stdout-before-timeout", result["stdout_tail"])
        self.assertIn("stderr-before-timeout", result["stderr_tail"])
        self.assertIn('"exit_code": 124', diagnostic.getvalue())

    def test_nonzero_command_is_reported_before_later_checks(self):
        diagnostic = io.StringIO()
        with contextlib.redirect_stderr(diagnostic):
            result = run([sys.executable, "-c", "raise SystemExit(7)"])
        self.assertEqual(result["exit_code"], 7)
        self.assertIn('"exit_code": 7', diagnostic.getvalue())


if __name__ == "__main__":
    unittest.main()
