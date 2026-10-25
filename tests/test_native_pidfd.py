"""Actual owned CPU-child pidfd controls; no model or unrelated signals."""
import errno
import importlib.util
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "adapters/pi/project-workflow/native_pidfd.py"


def load_facade():
    spec = importlib.util.spec_from_file_location("qualified_native_pidfd", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(sys.platform == "linux", "Linux public pidfd APIs")
class NativePidfdTests(unittest.TestCase):
    def setUp(self):
        self.api = load_facade()
        self.descriptors = []
        self.children = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for child, descriptor in self.children:
            if child.poll() is None:
                # Only this test's retained child identity is signaled. No
                # os.kill/PID signal fallback is used even for cleanup.
                try:
                    self.api.pidfd_send_signal(descriptor, signal.SIGCONT)
                except OSError:
                    pass
                if child.stdin is not None:
                    child.stdin.close()
                    child.stdin = None
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.api.pidfd_send_signal(descriptor, signal.SIGKILL)
                    child.wait(timeout=3)
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream is not None:
                    stream.close()
        for descriptor in self.descriptors:
            os.close(descriptor)

    def opened(self, pid, flags=0):
        descriptor = self.api.pidfd_open(pid, flags)
        self.descriptors.append(descriptor)
        return descriptor

    def child(self):
        self.api.require_support()  # Never spawn a child on an unsupported host.
        program = "import os,sys;print(os.getpid(),flush=True)\nfor line in sys.stdin:print('echo:'+line.strip(),flush=True)\n"
        child = subprocess.Popen([sys.executable, "-B", "-u", "-c", program], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            descriptor = self.opened(child.pid)
        except BaseException:
            child.stdin.close()
            child.wait(timeout=3)
            child.stdout.close()
            child.stderr.close()
            raise
        self.children.append((child, descriptor))
        self.assertTrue(select.select([child.stdout], [], [], 5)[0], "Owned child did not become ready")
        self.assertEqual(int(child.stdout.readline()), child.pid)
        return child, descriptor

    def test_backend_selection_and_self_probe_close_every_descriptor(self):
        selected = self.api.require_support()
        self.assertEqual(selected["pidfd_open"], "python" if callable(getattr(os, "pidfd_open", None)) else "libc")
        self.assertEqual(selected["pidfd_send_signal"], "python" if callable(getattr(signal, "pidfd_send_signal", None)) else "libc")
        before = len(os.listdir("/proc/self/fd"))
        for _ in range(25):
            self.assertEqual(self.api.require_support(), selected)
        self.assertEqual(len(os.listdir("/proc/self/fd")), before)

    def test_owned_child_stop_continue_exit_and_stale_identity(self):
        child, descriptor = self.child()
        self.assertIsNone(self.api.pidfd_send_signal(descriptor, 0))
        self.api.pidfd_send_signal(descriptor, signal.SIGSTOP)
        deadline = time.monotonic() + 5
        while True:
            pid, status = os.waitpid(child.pid, os.WUNTRACED | os.WNOHANG)
            if pid:
                self.assertTrue(os.WIFSTOPPED(status))
                self.assertEqual(os.WSTOPSIG(status), signal.SIGSTOP)
                break
            self.assertLess(time.monotonic(), deadline, "Owned child did not stop")
            time.sleep(.01)
        self.assertFalse(select.select([descriptor], [], [], 0)[0], "Stopped is not exited")
        self.api.pidfd_send_signal(descriptor, signal.SIGCONT, None, 0)
        child.stdin.write("continued\n")
        child.stdin.flush()
        self.assertTrue(select.select([child.stdout], [], [], 5)[0], "Owned child did not continue")
        self.assertEqual(child.stdout.readline(), "echo:continued\n")
        self.api.pidfd_send_signal(descriptor, signal.SIGTERM)
        self.assertTrue(select.select([descriptor], [], [], 5)[0], "Exit was not visible through the pidfd")
        self.assertEqual(child.wait(timeout=5), -signal.SIGTERM)
        with self.assertRaises(ProcessLookupError) as stale:
            self.api.pidfd_send_signal(descriptor, 0)
        self.assertEqual(stale.exception.errno, errno.ESRCH)
        other, _other_descriptor = self.child()
        with self.assertRaises(ProcessLookupError):
            self.api.pidfd_send_signal(descriptor, signal.SIGSTOP)
        other.stdin.write("still-running\n")
        other.stdin.flush()
        self.assertTrue(select.select([other.stdout], [], [], 5)[0])
        self.assertEqual(other.stdout.readline(), "echo:still-running\n")

    def test_cloexec_is_kernel_descriptor_state_and_survives_no_close_fds_exec(self):
        descriptor = self.opened(os.getpid())
        self.assertFalse(os.get_inheritable(descriptor))
        program = "import json,os,sys\ntry:value=os.readlink('/proc/self/fd/'+sys.argv[1])\nexcept OSError:value=None\nprint(json.dumps(value))"
        result = subprocess.run([sys.executable, "-B", "-c", program, str(descriptor)],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, close_fds=False, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(json.loads(result.stdout), "anon_inode:[pidfd]")
        self.assertIsNone(self.api.pidfd_send_signal(descriptor, 0))

    def test_errno_invalid_pid_flags_signal_regular_and_closed_descriptors(self):
        with self.assertRaises(OSError) as invalid_pid:
            self.api.pidfd_open(0)
        self.assertEqual(invalid_pid.exception.errno, errno.EINVAL)
        with self.assertRaises(OSError) as invalid_flags:
            self.api.pidfd_open(os.getpid(), 1)
        self.assertEqual(invalid_flags.exception.errno, errno.EINVAL)
        descriptor = self.opened(os.getpid())
        with self.assertRaises(OSError) as invalid_signal:
            self.api.pidfd_send_signal(descriptor, -1)
        self.assertEqual(invalid_signal.exception.errno, errno.EINVAL)
        with tempfile.TemporaryFile() as stream:
            with self.assertRaises(OSError) as wrong_file:
                self.api.pidfd_send_signal(stream.fileno(), 0)
            self.assertEqual(wrong_file.exception.errno, errno.EBADF)
        self.descriptors.remove(descriptor)
        os.close(descriptor)
        with self.assertRaises(OSError) as closed:
            self.api.pidfd_send_signal(descriptor, 0)
        self.assertEqual(closed.exception.errno, errno.EBADF)

    def test_ctypes_arguments_cannot_truncate_and_siginfo_is_always_null(self):
        for value in (2 ** 64, -(2 ** 64)):
            with self.assertRaises(OverflowError):
                self.api.pidfd_open(value)
        with self.assertRaises(TypeError):
            self.api.pidfd_open(1.5)
        descriptor = self.opened(os.getpid())
        with self.assertRaises(TypeError):
            self.api.pidfd_send_signal(descriptor, 0, object())
        self.assertIsNone(self.api.pidfd_send_signal(descriptor, 0, None, 0))

    def test_missing_public_functions_fail_closed_without_modifying_global_wrappers(self):
        absent = object()
        native_open = getattr(os, "pidfd_open", absent)
        native_signal = getattr(signal, "pidfd_send_signal", absent)
        with mock.patch.multiple(self.api, _PY_OPEN=None, _PY_SIGNAL=None,
                                 _C_SYMBOLS={"pidfd_open": None, "pidfd_send_signal": None}):
            with self.assertRaises(OSError) as unsupported:
                self.api.require_support()
            self.assertEqual(unsupported.exception.errno, errno.ENOSYS)
        self.assertIs(getattr(os, "pidfd_open", absent), native_open)
        self.assertIs(getattr(signal, "pidfd_send_signal", absent), native_signal)

    def test_failed_send_self_probe_still_closes_its_open_identity(self):
        symbols = dict(self.api._libc())
        symbols["pidfd_send_signal"] = None
        before = len(os.listdir("/proc/self/fd"))
        with mock.patch.object(self.api, "_PY_SIGNAL", None), mock.patch.object(self.api, "_C_SYMBOLS", symbols):
            with self.assertRaises(OSError) as unsupported:
                self.api.require_support()
            self.assertEqual(unsupported.exception.errno, errno.ENOSYS)
        self.assertEqual(len(os.listdir("/proc/self/fd")), before)


@unittest.skipIf(sys.platform == "linux", "Actual unsupported-platform qualification")
class UnsupportedPidfdTests(unittest.TestCase):
    def test_actual_platform_refuses_without_pid_or_signal_fallback(self):
        module = load_facade()
        self.assertEqual(module.backend(), {"pidfd_open": "unavailable", "pidfd_send_signal": "unavailable"})
        with self.assertRaises(OSError) as unsupported:
            module.require_support()
        self.assertEqual(unsupported.exception.errno, errno.ENOSYS)


if __name__ == "__main__":
    unittest.main()
