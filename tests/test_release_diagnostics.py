import sys
import unittest

from scripts.verify_ssot_release import run


class ReleaseDiagnosticsTests(unittest.TestCase):
    def test_timeout_preserves_output_and_fails(self):
        code = (
            "import sys,time; "
            "print('stdout-before-timeout',flush=True); "
            "print('stderr-before-timeout',file=sys.stderr,flush=True); "
            "time.sleep(60)"
        )
        result = run([sys.executable, "-c", code], timeout=2)
        self.assertEqual(result["exit_code"], 124)
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["timeout_seconds"], 2)
        self.assertIn("stdout-before-timeout", result["stdout_tail"])
        self.assertIn("stderr-before-timeout", result["stderr_tail"])


if __name__ == "__main__":
    unittest.main()
