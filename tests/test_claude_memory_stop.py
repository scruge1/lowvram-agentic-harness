"""Native metadata retirement is separate from lifetime/capture acceptance."""

import errno
import hashlib
import json
import os
from pathlib import Path
import socket
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from harness import claude_memory as memory


@unittest.skipUnless(
    os.name == "posix", "Owned UID, directory fsync and native metadata require POSIX"
)
class StopMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.pid = 2147483647
        self.assertFalse((Path("/proc") / str(self.pid)).exists())
        with socket.socket() as port:
            port.bind(("127.0.0.1", 0))
            self.port = port.getsockname()[1]
        self.proof = {
            "pid": self.pid,
            "process": {"start_ticks": "123", "uid": os.getuid()},
            "port": self.port,
            "root": str(self.root),
            "home": str(self.root.parent),
            "worker_sha256": "a" * 64,
        }
        self.registry = {
            "processes": {
                "worker": {
                    "pid": self.pid,
                    "type": "worker",
                    "startedAt": "2026-10-26T12:00:00.000Z",
                }
            }
        }
        self.identity = {
            "pid": self.pid,
            "port": self.port,
            "startToken": "123",
            "startedAt": "2026-10-26T12:00:00.000Z",
        }
        self.write()

    def write(self):
        (self.root / "supervisor.json").write_text(json.dumps(self.registry))
        (self.root / "worker.pid").write_text(json.dumps(self.identity))

    def capture(self):
        return memory._capture_stop_metadata(self.proof)

    def settle(self, proof, captured):
        # Filesystem-only controls. Actual PIDFD/zombie discrimination is below.
        with patch.object(memory.select, "select", return_value=([99], [], [])):
            return memory._settle_stop_metadata(proof, captured, exited_descriptor=99)

    def test_exact_known_owned_leftovers_retained_and_restart_ready(self):
        captured = self.capture()
        result = self.settle(self.proof, captured)
        self.assertTrue(result["restart_ready"])
        directory = Path(result["retained_stop"])
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        for name, pair in captured.items():
            self.assertFalse((self.root / name).exists())
            self.assertEqual((directory / (name + ".original")).read_bytes(), pair[0])
        record = json.loads((directory / "stop.json").read_text())
        self.assertEqual(record["lifetime"], "pidfd_exited")
        self.assertEqual(
            record["preimages"]["worker.pid"],
            hashlib.sha256(captured["worker.pid"][0]).hexdigest(),
        )
        self.assertNotIn("api_key", json.dumps(record))

    def test_native_graceful_cleanup_is_preserved(self):
        captured = self.capture()
        (self.root / "supervisor.json").write_text('{"processes":{}}')
        (self.root / "worker.pid").unlink()
        result = self.settle(self.proof, captured)
        self.assertTrue(result["restart_ready"])
        self.assertEqual(
            (self.root / "supervisor.json").read_bytes(), b'{"processes":{}}'
        )
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_changed_or_added_entry_refuses_without_modification(self):
        for change in ("bytes", "extra_entry", "pid"):
            with self.subTest(change=change):
                self.setUpMetadata()
                self.write()
                captured = self.capture()
                path = self.root / "supervisor.json"
                if change == "bytes":
                    path.write_bytes(path.read_bytes() + b"\n")
                elif change == "extra_entry":
                    value = json.loads(path.read_text())
                    value["processes"]["foreign"] = {"pid": os.getpid()}
                    path.write_text(json.dumps(value))
                else:
                    (self.root / "worker.pid").write_text("{}")
                before = {p.name: p.read_bytes() for p in self.root.iterdir()}
                result = self.settle(self.proof, captured)
                self.assertFalse(result["restart_ready"])
                self.assertEqual(
                    before, {p.name: p.read_bytes() for p in self.root.iterdir()}
                )

    def test_unknown_registry_or_epoch_never_qualifies_for_retirement(self):
        for mutate in (
            lambda: self.registry["processes"].update({"foreign": {"pid": 1}}),
            lambda: self.identity.update(startToken="different"),
            lambda: self.identity.update(secret="must_not_retire"),
            lambda: self.identity.update(startedAt="other-time"),
            lambda: self.identity.update(pid=float(self.pid)),
        ):
            self.setUpMetadata()
            mutate()
            self.write()
            with self.assertRaises(ValueError):
                self.capture()
            before = {p.name: p.read_bytes() for p in self.root.iterdir()}
            self.assertFalse(self.settle(self.proof, None)["restart_ready"])
            self.assertEqual(
                before, {p.name: p.read_bytes() for p in self.root.iterdir()}
            )

    def setUpMetadata(self):
        self.registry = {
            "processes": {
                "worker": {"pid": self.pid, "type": "worker", "startedAt": "now"}
            }
        }
        self.identity = {
            "pid": self.pid,
            "port": self.port,
            "startToken": "123",
            "startedAt": "now",
        }

    def test_port_occupied_and_live_pid_refuse_without_retirement(self):
        captured = self.capture()
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        with socket.socket() as port:
            port.bind(("127.0.0.1", self.port))
            self.assertFalse(self.settle(self.proof, captured)["restart_ready"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})
        proof = {**self.proof, "pid": os.getpid()}
        self.assertFalse(self.settle(proof, captured)["restart_ready"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_redirected_metadata_refused_and_original_preserved(self):
        original = self.root / "worker.pid"
        original.rename(self.root / "actual")
        original.symlink_to(self.root / "actual")
        with self.assertRaises(ValueError):
            self.capture()
        self.assertFalse(self.settle(self.proof, None)["restart_ready"])
        self.assertTrue(original.is_symlink())

    def test_partial_failure_retains_preimage_and_does_not_replay(self):
        captured = self.capture()
        rename = os.rename

        def fail_second(source, target):
            if Path(source).name == "worker.pid":
                raise OSError("controlled interruption")
            return rename(source, target)

        with patch.object(memory.os, "rename", side_effect=fail_second):
            result = self.settle(self.proof, captured)
        self.assertFalse(result["restart_ready"])
        directory = Path(result["retained_stop"])
        self.assertEqual(
            (directory / "supervisor.json.original").read_bytes(),
            captured["supervisor.json"][0],
        )
        self.assertEqual(
            (self.root / "worker.pid").read_bytes(), captured["worker.pid"][0]
        )
        self.assertFalse(self.settle(self.proof, captured)["restart_ready"])
        self.assertTrue((self.root / "worker.pid").exists())

    def tcp_states(self, selected_port):
        states = []
        for name in ("tcp", "tcp6"):
            for line in (Path("/proc/net") / name).read_text().splitlines()[1:]:
                fields = line.split()
                if int(fields[1].rsplit(":", 1)[1], 16) == selected_port:
                    states.append(fields[3])
        return states

    def time_wait_port(self):
        listener = socket.socket()
        client = accepted = None
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.settimeout(2)
            listener.bind(("127.0.0.1", 0))
            selected_port = listener.getsockname()[1]
            listener.listen(1)
            client = socket.socket()
            client.settimeout(2)
            client.connect(("127.0.0.1", selected_port))
            accepted, _ = listener.accept()
            accepted.shutdown(socket.SHUT_WR)
            self.assertEqual(client.recv(1), b"")
            accepted.close()
            accepted = None
            client.close()
            client = None
        finally:
            if accepted is not None:
                accepted.close()
            if client is not None:
                client.close()
            listener.close()
        deadline = time.monotonic() + 2
        while "06" not in self.tcp_states(selected_port):
            self.assertLess(
                time.monotonic(), deadline, "Owned TCP did not enter TIME_WAIT"
            )
            select.select([], [], [], 0.005)
        self.assertNotIn("0A", self.tcp_states(selected_port))
        return selected_port

    @unittest.skipUnless(sys.platform == "linux", "Actual Linux TCP TIME_WAIT witness")
    def test_time_wait_allows_known_metadata_retirement_but_not_restart(self):
        selected_port = self.time_wait_port()
        self.port = selected_port
        self.proof["port"] = selected_port
        self.identity["port"] = selected_port
        self.write()
        with socket.socket() as strict:
            with self.assertRaises(OSError) as failed:
                strict.bind(("127.0.0.1", selected_port))
            self.assertEqual(failed.exception.errno, errno.EADDRINUSE)
        captured = self.capture()
        result = self.settle(self.proof, captured)
        self.assertEqual(result["registry_review"], "settled")
        self.assertFalse(result["port_ready"])
        self.assertEqual(result["port_errno"], errno.EADDRINUSE)
        self.assertFalse(result["restart_ready"])
        for name, pair in captured.items():
            self.assertEqual(
                (Path(result["retained_stop"]) / (name + ".original")).read_bytes(),
                pair[0],
            )
        with (
            patch.object(memory, "health", return_value=None),
            patch.object(memory, "live_pid", return_value=None),
        ):
            inactive = memory.dispatch(
                self.root.parent,
                self.root,
                {"claude_memory_port": selected_port},
                None,
                None,
                {},
                None,
                "stop",
                {},
                "",
            )
        self.assertEqual(inactive["status"], "stopped")
        self.assertEqual(inactive["registry_review"], "settled")
        self.assertFalse(inactive["port_ready"])
        self.assertFalse(inactive["restart_ready"])

    @unittest.skipUnless(sys.platform == "linux", "Actual Linux reuse-address listener")
    def test_reuse_address_listener_still_blocks_retirement_and_restart(self):
        captured = self.capture()
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", self.port))
            listener.listen(1)
            result = self.settle(self.proof, captured)
            self.assertFalse(result["restart_ready"])
            self.assertFalse(result["port_ready"])
            self.assertEqual(result["registry_review"], "required")
            self.assertEqual(
                before, {p.name: p.read_bytes() for p in self.root.iterdir()}
            )
            (self.root / "supervisor.json").write_text('{"processes":{}}')
            (self.root / "worker.pid").unlink()
            clean = memory._restart_readiness(self.root, self.port)
            self.assertEqual(clean["registry_review"], "settled")
            self.assertFalse(clean["port_ready"])
            self.assertFalse(clean["restart_ready"])
        self.assertTrue(
            memory._restart_readiness(self.root, self.port)["restart_ready"]
        )


@unittest.skipUnless(
    sys.platform == "linux", "Actual PIDFD/proc zombie fixture requires Linux"
)
class KnownExitedLifetimeTests(unittest.TestCase):
    def test_real_pidfd_exited_zombie_allows_only_matching_owned_lifetime(self):
        native = memory.model_service._pidfd()
        native.require_support()
        child = subprocess.Popen(
            [sys.executable, "-B", "-c", "import time; time.sleep(30)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        descriptor = native.pidfd_open(child.pid, 0)
        try:
            process = memory.model_service._process(child.pid)
            self.assertIsNotNone(process)
            proof = {"pid": child.pid, "process": process}
            self.assertFalse(memory._owned_lifetime_exited(proof, descriptor))
            native.pidfd_send_signal(descriptor, signal.SIGTERM)
            self.assertTrue(select.select([descriptor], [], [], 5)[0])
            # Do not poll/wait yet: a separate native stop helper cannot reap it.
            fields = (
                (Path("/proc") / str(child.pid) / "stat")
                .read_text()
                .rsplit(")", 1)[1]
                .split()
            )
            self.assertEqual(fields[0], "Z")
            self.assertTrue(memory._owned_lifetime_exited(proof, descriptor))
            self.assertFalse(memory._owned_lifetime_exited(proof, None))
            wrong = {
                "pid": child.pid,
                "process": {**process, "start_ticks": "different"},
            }
            self.assertFalse(memory._owned_lifetime_exited(wrong, descriptor))
            self.assertFalse(
                memory._owned_lifetime_exited(
                    {"pid": os.getpid(), "process": process}, descriptor
                )
            )
            with tempfile.TemporaryDirectory(
                prefix="observer-zombie-metadata-"
            ) as value:
                root = Path(value).resolve()
                with socket.socket() as port:
                    port.bind(("127.0.0.1", 0))
                    selected_port = port.getsockname()[1]
                proof.update(
                    root=str(root),
                    home=str(root.parent),
                    port=selected_port,
                    worker_sha256="b" * 64,
                )
                (root / "supervisor.json").write_text(
                    json.dumps(
                        {
                            "processes": {
                                "worker": {
                                    "pid": child.pid,
                                    "type": "worker",
                                    "startedAt": "same-native-time",
                                }
                            }
                        }
                    )
                )
                (root / "worker.pid").write_text(
                    json.dumps(
                        {
                            "pid": child.pid,
                            "port": selected_port,
                            "startToken": process["start_ticks"],
                            "startedAt": "same-native-time",
                        }
                    )
                )
                captured = memory._capture_stop_metadata(proof)
                settled = memory._settle_stop_metadata(
                    proof, captured, exited_descriptor=descriptor
                )
                self.assertTrue(settled["restart_ready"])
                self.assertEqual(
                    (
                        Path(settled["retained_stop"]) / "worker.pid.original"
                    ).read_bytes(),
                    captured["worker.pid"][0],
                )
                self.assertTrue(
                    (Path("/proc") / str(child.pid)).exists(),
                    "Fixture must remain an unreaped same-parent zombie",
                )
            child.wait(timeout=3)
            self.assertTrue(memory._owned_lifetime_exited(proof, descriptor))
        finally:
            if not select.select([descriptor], [], [], 0)[0]:
                native.pidfd_send_signal(descriptor, signal.SIGKILL)
            child.wait(timeout=3)
            os.close(descriptor)


if __name__ == "__main__":
    unittest.main()
