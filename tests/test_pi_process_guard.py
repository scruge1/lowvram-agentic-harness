"""Exercise the exported Linux owner guard without Pi, inference or a GPU."""

import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock


WORKFLOW = Path(__file__).resolve().parents[1] / "adapters" / "pi" / "project-workflow"
GUARD = WORKFLOW / "pi-task-worker.py"
sys.path.insert(0, str(WORKFLOW))
SPEC = importlib.util.spec_from_file_location("pi_process_guard", GUARD)
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)
from pi_native_events import tool_results  # noqa: E402


try:
    guard.require_process_ownership()
    LINUX_OWNERSHIP = True
except (OSError, ValueError):
    LINUX_OWNERSHIP = False


class PortableGuardTests(unittest.TestCase):
    def test_unsupported_platform_refuses_before_process_start(self):
        with mock.patch.object(guard.sys, "platform", "win32"), mock.patch.object(
            guard.subprocess, "Popen"
        ) as start:
            with self.assertRaisesRegex(ValueError, "requires Linux"):
                guard.guarded_pi([sys.executable, "-c", "raise SystemExit(0)"])
            start.assert_not_called()

    def test_reused_pid_is_not_killed_after_descriptor_reopen(self):
        identities = iter(["100", "101"])

        def proc_text(file, *args, **kwargs):
            if file.name == "status":
                return "State:\tT (stopped)\n"
            return "1 (fixture) " + " ".join(["T"] + ["0"] * 18 + [next(identities)])

        with mock.patch.object(guard.PIDFD, "pidfd_open", side_effect=[91, 92]), \
             mock.patch.object(guard.os, "fstat", return_value=SimpleNamespace(st_dev=6, st_ino=7)), \
             mock.patch.object(guard.os, "close") as close, \
             mock.patch.object(guard.PIDFD, "pidfd_send_signal") as send, \
             mock.patch.object(guard.signal, "SIGSTOP", 19, create=True), \
             mock.patch.object(guard.signal, "SIGKILL", 9, create=True), \
             mock.patch.object(guard.Path, "read_text", proc_text), \
             mock.patch.object(guard, "owned_children", return_value=set()):
            guard.stop_owned_tree(123)
        self.assertEqual(send.call_args_list, [mock.call(91, 0), mock.call(91, 19), mock.call(92, 0)])
        self.assertEqual(close.call_args_list, [mock.call(91), mock.call(92)])

    def test_inspection_failure_unwinds_known_parent_and_stays_failed(self):
        def proc_text(file, *args, **kwargs):
            if file.name == "status":
                return "State:\tT (stopped)\n"
            return "1 (fixture) " + " ".join(["T"] + ["0"] * 18 + ["100"])

        with mock.patch.object(guard.PIDFD, "pidfd_open", side_effect=[91, PermissionError("denied"), 92]), \
             mock.patch.object(guard.os, "fstat", return_value=SimpleNamespace(st_dev=6, st_ino=7)), \
             mock.patch.object(guard.os, "close"), \
             mock.patch.object(guard.PIDFD, "pidfd_send_signal") as send, \
             mock.patch.object(guard.signal, "SIGSTOP", 19, create=True), \
             mock.patch.object(guard.signal, "SIGKILL", 9, create=True), \
             mock.patch.object(guard.Path, "read_text", proc_text), \
             mock.patch.object(guard, "owned_children", return_value={456}):
            with self.assertRaisesRegex(PermissionError, "denied"):
                guard.stop_owned_tree(123)
        self.assertIn(mock.call(92, 9), send.call_args_list)

    def test_final_hook_modified_tool_result_replaces_earlier_event(self):
        events = [
            {"type": "tool_execution_end", "toolCallId": "one", "toolName": "read",
             "result": {"content": "old"}, "isError": False},
            {"type": "message_end", "message": {
                "role": "toolResult", "toolCallId": "one", "toolName": "read",
                "content": [{"type": "text", "text": "refused"}], "isError": True}},
            {"type": "message_end", "message": {
                "role": "assistant", "content": "I called read successfully"}},
        ]
        result = tool_results(events)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["is_error"])
        self.assertEqual(result[0]["result"]["content"][0]["text"], "refused")

    def test_message_only_completion_is_retained(self):
        message = {"role": "toolResult", "toolCallId": "two", "toolName": "ls",
                   "content": [{"type": "text", "text": "files"}]}
        self.assertEqual(tool_results([{"type": "message_end", "message": message}]), [
            {"tool_call_id": "two", "tool_name": "ls", "result": message,
             "is_error": False}
        ])


@unittest.skipUnless(LINUX_OWNERSHIP, "requires Linux /proc and pidfd support")
class LinuxGuardTests(unittest.TestCase):
    def start(self, source, timeout="3", nofile=None):
        def limits():
            import resource
            resource.setrlimit(resource.RLIMIT_NOFILE, (nofile, nofile))
        return subprocess.Popen(
            [sys.executable, str(GUARD), "--guard", sys.executable, "-u", "-c", source],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, "PI_TASK_TIMEOUT": timeout},
            preexec_fn=limits if nofile is not None else None,
        )

    def finish(self, process, limit=12):
        # communicate() would close the ownership pipe and cancel the workload.
        ownership = process.stdin
        process.stdin = None
        try:
            stdout, stderr = process.communicate(timeout=limit)
        finally:
            ownership.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
        return process.returncode, stdout, stderr

    def wait_file(self, path):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if path.exists():
                return int(path.read_text())
            time.sleep(0.01)
        self.fail("Owned workload did not produce its PID")

    def assert_gone(self, pid):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if not Path(f"/proc/{pid}").exists():
                return
            time.sleep(0.01)
        self.fail(f"Owned process {pid} is still present")

    def test_exit_status_and_both_streams_are_preserved(self):
        process = self.start("import sys; print('owned stdout'); print('owned stderr', file=sys.stderr); sys.exit(7)")
        code, stdout, stderr = self.finish(process)
        self.assertEqual(code, 7, stderr)
        self.assertEqual(stdout, b"owned stdout\n")
        self.assertEqual(stderr, b"owned stderr\n")

    def test_invalid_timeout_refuses_before_workload(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "should-not-exist"
            for timeout in ("0", "-1", "nan", "inf", "bad"):
                with self.subTest(timeout=timeout):
                    process = self.start(f"from pathlib import Path; Path({str(marker)!r}).touch()", timeout)
                    code, _, stderr = self.finish(process)
                    self.assertEqual(code, 2, stderr)
                    self.assertFalse(marker.exists())

    def test_timeout_cleans_descendant_after_parent_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "descendant.pid"
            descendant = f"import os,time; from pathlib import Path; Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(30)"
            source = f"import subprocess,sys; subprocess.Popen([sys.executable,'-u','-c',{descendant!r}]); print('parent ended')"
            process = self.start(source, timeout="0.5")
            pid = self.wait_file(marker)
            code, stdout, stderr = self.finish(process)
            self.assertEqual(code, 124, stderr)
            self.assertIn(b"parent ended", stdout)
            self.assert_gone(pid)

    def test_owner_pipe_loss_cancels_only_owned_process(self):
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            with tempfile.TemporaryDirectory() as directory:
                marker = Path(directory) / "worker.pid"
                source = f"import os,time; from pathlib import Path; Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(30)"
                process = self.start(source, timeout="20")
                pid = self.wait_file(marker)
                process.stdin.close()
                process.stdin = None
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 125, (stdout, stderr))
                self.assert_gone(pid)
                self.assertIsNone(unrelated.poll())
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=3)

    def test_termination_signal_cancels_owned_process(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "worker.pid"
            source = f"import os,time; from pathlib import Path; Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(30)"
            process = self.start(source, timeout="20")
            pid = self.wait_file(marker)
            process.send_signal(signal.SIGTERM)
            code, stdout, stderr = self.finish(process)
            self.assertEqual(code, 125, (stdout, stderr))
            self.assert_gone(pid)

    def test_deep_tree_cleanup_stays_below_descriptor_limit(self):
        # More process levels than the guard's descriptor limit reproduces the
        # former failure without an unrelated workload or a host ulimit change.
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "deep-tree.json"
            source = f"""import json,os,time
from pathlib import Path
pids=[os.getpid()]
for _ in range(96):
    child=os.fork()
    if child:
        time.sleep(30)
        os._exit(0)
    pids.append(os.getpid())
Path({str(marker)!r}).write_text(json.dumps(pids))
time.sleep(30)
"""
            process = self.start(source, timeout="1.5", nofile=64)
            deadline = time.monotonic() + 5
            pids = None
            while time.monotonic() < deadline:
                try:
                    pids = json.loads(marker.read_text())
                    break
                except (FileNotFoundError, json.JSONDecodeError):
                    time.sleep(0.01)
            code, stdout, stderr = self.finish(process)
            self.assertEqual(code, 124, (stdout, stderr))
            self.assertIsNotNone(pids, "Deep process chain did not finish starting")
            self.assertEqual(len(pids), 97)
            for pid in pids:
                self.assert_gone(pid)


if __name__ == "__main__":
    unittest.main()
