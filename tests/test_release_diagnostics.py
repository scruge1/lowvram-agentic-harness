import sys
import unittest
import contextlib
import io
import time
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from scripts.verify_ssot_release import UNSETTLED_CHILDREN, output_snapshot, run, unit_test_commands


class ReleaseDiagnosticsTests(unittest.TestCase):
    def test_native_discovery_groups_assign_each_test_file_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("test_agent.py", "test_model.py", "test_native.py", "test_zero.py"):
                (root / name).touch()
            commands = unit_test_commands(root)
        self.assertEqual([command[-2] for command in commands], ["test_[a-m]*.py", "test_[n-z]*.py"])
        for command in commands:
            self.assertEqual(command[:6], [sys.executable, "-m", "unittest", "discover", "-s", "tests"])

    def test_unassigned_or_overlapping_test_file_refuses_before_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "testUnexpected.py"
            source.touch()
            with self.assertRaisesRegex(RuntimeError, "exactly one"):
                unit_test_commands(root)
            source.unlink()
            (root / "test_agent.py").touch()
            with mock.patch("scripts.verify_ssot_release.UNIT_TEST_PATTERNS", ("test*.py", "test_a*.py")):
                with self.assertRaisesRegex(RuntimeError, "exactly one"):
                    unit_test_commands(root)

    def test_tail_truncation_and_snapshot_preserve_writer_offset(self):
        with tempfile.TemporaryFile(mode="w+b") as stream:
            stream.write(b"x" * 30000)
            stream.flush()
            snapshot = output_snapshot(stream)
            self.assertEqual(stream.tell(), 30000)
        self.assertTrue(snapshot["truncated"])
        self.assertEqual(snapshot["sampled_bytes"], 30000)
        self.assertEqual(len(snapshot["tail"]), 20000)

    def test_unsettled_child_remains_owned_after_kill_denial(self):
        child = mock.Mock(returncode=None)
        child.wait.side_effect = subprocess.TimeoutExpired(["fixture"], 1)
        child.kill.side_effect = PermissionError("fixture denial")
        with mock.patch("scripts.verify_ssot_release.subprocess.Popen", return_value=child):
            with contextlib.redirect_stderr(io.StringIO()):
                result = run(["fixture"], timeout=1)
        self.addCleanup(UNSETTLED_CHILDREN.remove, child)
        self.assertIs(UNSETTLED_CHILDREN[-1], child)
        self.assertFalse(result["child_settled"])
        self.assertIsNone(result["child_exit_code"])
        self.assertEqual(result["kill_error"], "PermissionError")
        self.assertEqual([call.kwargs["timeout"] for call in child.wait.call_args_list], [1, 3])

    def test_changing_snapshot_cannot_pass_release(self):
        def changed(stream):
            snapshot = output_snapshot(stream)
            snapshot["stable"] = False
            return snapshot

        with mock.patch("scripts.verify_ssot_release.output_snapshot", side_effect=changed):
            with contextlib.redirect_stderr(io.StringIO()):
                result = run([sys.executable, "-c", "pass"])
        self.assertEqual(result["child_exit_code"], 0)
        self.assertEqual(result["exit_code"], 125)

    def test_timeout_does_not_wait_for_descendant_pipe_eof(self):
        descendant = "import time; time.sleep(5)"
        parent = (
            "import subprocess,sys,time; "
            f"subprocess.Popen([sys.executable,'-c',{descendant!r}]); "
            "print('before-timeout',flush=True); time.sleep(60)"
        )
        start = time.monotonic()
        with contextlib.redirect_stderr(io.StringIO()):
            result = run([sys.executable, "-c", parent], timeout=1)
        self.assertLess(time.monotonic() - start, 4)
        self.assertEqual(result["exit_code"], 124)
        self.assertTrue(result["child_settled"])
        self.assertIn("before-timeout", result["stdout_tail"])

    def test_success_does_not_wait_for_descendant_pipe_eof(self):
        with tempfile.TemporaryDirectory() as directory:
            ready = str(Path(directory) / "ready")
            descendant = (
                "import pathlib,sys,time; "
                "pathlib.Path(sys.argv[1]).write_text('ready'); time.sleep(5)"
            )
            # Establish the fixture's quiet held handles before parent exit.
            # A descendant's delayed interpreter-startup warning is a real
            # concurrent write and correctly makes the release snapshot refuse.
            parent = (
                "import pathlib,subprocess,sys,time\n"
                f"subprocess.Popen([sys.executable,'-c',{descendant!r},{ready!r}])\n"
                f"while not pathlib.Path({ready!r}).exists(): time.sleep(.001)\n"
                "print('complete',flush=True)\n"
            )
            start = time.monotonic()
            result = run([sys.executable, "-c", parent], timeout=1)
        self.assertLess(time.monotonic() - start, 4)
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("complete", result["stdout_tail"])

    def test_large_output_has_bounded_tail_and_explicit_truncation(self):
        result = run([sys.executable, "-c", "import sys; sys.stdout.write('x'*100000+'END')"])
        snapshot = result["output_snapshots"]["stdout"]
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(snapshot["observed_bytes"], 100003)
        self.assertEqual(snapshot["sampled_bytes"], 80000)
        self.assertTrue(snapshot["truncated"])
        self.assertTrue(snapshot["stable"])
        self.assertEqual(len(result["stdout_tail"]), 20000)
        self.assertTrue(result["stdout_tail"].endswith("END"))

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
