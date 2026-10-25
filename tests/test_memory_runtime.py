"""Memory cache binding and dispatch without downloading or running a model."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "harness" / "memory_runtime.py"
PIDFD_SOURCE = SOURCE.parents[1] / "adapters/pi/project-workflow/native_pidfd.py"


class MemoryRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.wrapper = self.home / "runtime/harness/memory_runtime.py"
        self.wrapper.parent.mkdir(parents=True)
        self.wrapper.write_bytes(SOURCE.read_bytes())
        spec = importlib.util.spec_from_file_location("bound_memory_fixture", self.wrapper)
        self.runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runtime)
        self.onnx_source = self.home / "envs/mempalace/site-packages" / self.runtime.ONNX_SOURCE
        self.onnx_source.parent.mkdir(parents=True)
        self.onnx_source.write_text("# Recorded installed Chroma source\n")
        self.chroma = SimpleNamespace(version="1.5.fixture", locate_file=lambda _path: self.onnx_source)
        self.metadata_version = mock.patch.object(self.runtime.metadata, "version", return_value="3.11.0")
        self.metadata_distribution = mock.patch.object(self.runtime.metadata, "distribution", return_value=self.chroma)
        self.metadata_version.start()
        self.metadata_distribution.start()
        self.addCleanup(self.metadata_version.stop)
        self.addCleanup(self.metadata_distribution.stop)
        native_helper = self.home / "runtime" / self.runtime.NATIVE_PIDFD_SOURCE
        native_helper.parent.mkdir(parents=True)
        native_helper.write_bytes(PIDFD_SOURCE.read_bytes())
        self.records = {"harness/memory_runtime.py": self.runtime.digest(self.wrapper),
                        self.runtime.NATIVE_PIDFD_SOURCE: self.runtime.digest(native_helper)}
        for files in self.runtime.HELPERS.values():
            for relative in files:
                path = self.home / "runtime" / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# Pinned helper fixture\n")
                self.records[relative] = self.runtime.digest(path)
        manifest = self.home / "runtime/runtime-manifest.json"
        manifest.write_text(json.dumps({"files": [{"path": path, "sha256": sha}
                                                  for path, sha in self.records.items()]}))
        self.binding = self.runtime.build_binding(self.home)
        self.config = {"schema": "agent-home/v1", "home": str(self.home),
                       "runtime_manifest_sha256": self.runtime.digest(manifest), "memory_runtime": self.binding}
        (self.home / "home.json").write_text(json.dumps(self.config))
        self.runtime.checked_home(self.home)
        self.cls = type("RecordedONNX", (), {"MODEL_NAME": "all-MiniLM-L6-v2",
                                            "DOWNLOAD_PATH": Path("original-cache")})
        self.onnx = SimpleNamespace(__file__=str(self.onnx_source), ONNXMiniLM_L6_V2=self.cls)
        environment = mock.patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)

    def test_bind_reads_only_package_identity_without_import_or_cache_creation(self):
        before_home = os.environ.get("HOME")
        with mock.patch.object(self.runtime.importlib, "import_module") as import_package:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(self.runtime.main(["--home", str(self.home), "--bind"]), 0)
            import_package.assert_not_called()
        self.assertEqual(json.loads(out.getvalue()), self.binding)
        self.assertFalse(Path(self.binding["cache_directory"]).exists())
        self.assertEqual(os.environ.get("HOME"), before_home)

    def test_runtime_binds_process_local_cache_and_cpu_while_preserving_home(self):
        before_home = os.environ.get("HOME")
        with mock.patch.object(self.runtime.importlib, "import_module", return_value=self.onnx) as import_package:
            self.runtime.prepare_runtime(self.home, self.binding)
        import_package.assert_called_once_with(self.runtime.ONNX_MODULE)
        self.assertEqual(self.cls.DOWNLOAD_PATH, self.home / "cache/chroma/onnx_models/all-MiniLM-L6-v2")
        self.assertEqual(os.environ["MEMPALACE_EMBEDDING_MODEL"], "minilm")
        self.assertEqual(os.environ["MEMPALACE_EMBEDDING_DEVICE"], "cpu")
        self.assertEqual(os.environ["CUDA_VISIBLE_DEVICES"], "")
        self.assertEqual(os.environ["MEMPALACE_HUB_FORWARD"], "1")
        self.assertEqual(os.environ["MEMPALACE_CLI_WRITE_ROUTING"], "direct")
        self.assertEqual(os.environ.get("HOME"), before_home)
        self.assertFalse(self.cls.DOWNLOAD_PATH.exists())

    def test_changed_module_or_cache_destination_refuses_before_import(self):
        altered = {**self.binding, "cache_directory": str(self.home.parent / "outside")}
        with mock.patch.object(self.runtime.importlib, "import_module") as import_package:
            with self.assertRaisesRegex(ValueError, "binding drift"):
                self.runtime.prepare_runtime(self.home, altered)
            self.onnx_source.write_text("# Drifted package\n")
            with self.assertRaisesRegex(ValueError, "binding drift"):
                self.runtime.prepare_runtime(self.home, self.binding)
            import_package.assert_not_called()

    def test_changed_helper_refuses_before_package_import_or_execution(self):
        path = self.home / "runtime" / self.runtime.HELPERS["validated"][1]
        path.write_text("# Changed retrieval policy\n")
        with mock.patch.object(self.runtime, "prepare_runtime") as prepare:
            with self.assertRaisesRegex(ValueError, "source byte drift"):
                self.runtime.dispatch(self.home, self.config, self.records, "validated", ["--query", "private token"])
            prepare.assert_not_called()

    def test_mcp_uses_direct_stdio_server_with_fixed_palace(self):
        observed = []
        server = SimpleNamespace(main=lambda: observed.append(list(sys.argv)))
        def import_package(name):
            if name == self.runtime.ONNX_MODULE:
                return self.onnx
            self.assertEqual(name, "mempalace.mcp_server")
            return server
        with mock.patch.object(self.runtime, "require_hub") as admission, \
             mock.patch.object(self.runtime.importlib, "import_module", side_effect=import_package), \
             mock.patch.object(sys, "argv", []):
            self.assertEqual(self.runtime.dispatch(self.home, self.config, self.records, "mcp", []), 0)
        admission.assert_called_once_with(self.home, self.config)
        self.assertEqual(observed, [["mempalace-mcp", "--palace", str(self.home / "memory/palace")]])
        with mock.patch.object(self.runtime, "prepare_runtime") as prepare:
            with self.assertRaisesRegex(ValueError, "fixed local stdio"):
                self.runtime.dispatch(self.home, self.config, self.records, "mcp", ["--transport", "http"])
            prepare.assert_not_called()

    def test_home_manifest_and_wrapper_bytes_are_checked(self):
        self.wrapper.write_bytes(self.wrapper.read_bytes() + b"\n# Changed\n")
        with mock.patch.object(self.runtime, "bind_native_pidfd") as bind:
            with self.assertRaisesRegex(ValueError, "source byte drift"):
                self.runtime.checked_home(self.home)
            bind.assert_not_called()

    def test_pidfd_helper_drift_refuses_before_compilation(self):
        helper = self.home / "runtime" / self.runtime.NATIVE_PIDFD_SOURCE
        marker = self.home / "unexpected-helper-execution"
        helper.write_text("from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\n")
        with self.assertRaisesRegex(ValueError, "source byte drift"):
            self.runtime.bind_native_pidfd(self.home, self.records)
        self.assertFalse(marker.exists())

    @unittest.skipUnless(sys.platform == "linux", "requires actual Linux pidfd support")
    def test_pidfd_binding_uses_canonical_source_and_ignores_import_search(self):
        decoy = SimpleNamespace(require_support=lambda: self.fail("Imported unbound helper"))
        with mock.patch.dict(sys.modules, {"native_pidfd": decoy}):
            self.runtime.bind_native_pidfd(self.home, self.records)
        bound = self.runtime._BOUND_PIDFD
        self.assertEqual(Path(bound.__file__), self.home / "runtime" / self.runtime.NATIVE_PIDFD_SOURCE)
        self.assertIn(bound.require_support()["pidfd_open"], ("python", "libc"))

    @unittest.skipUnless(sys.platform == "linux", "requires actual Linux symlink support")
    def test_pidfd_helper_symlink_refuses_even_with_matching_bytes(self):
        helper = self.home / "runtime" / self.runtime.NATIVE_PIDFD_SOURCE
        redirected = helper.with_name("redirected.py")
        helper.rename(redirected)
        helper.symlink_to(redirected)
        with self.assertRaisesRegex(ValueError, "path is redirected"):
            self.runtime.bind_native_pidfd(self.home, self.records)

    def test_explicit_daemon_route_refuses_before_import(self):
        with mock.patch.object(self.runtime, "prepare_runtime") as prepare:
            for flag in ("--daemon", "--background"):
                with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, "writers are refused"):
                    self.runtime.dispatch(self.home, self.config, self.records, "cli", ["mine", "exports", flag])
            prepare.assert_not_called()

    def test_missing_hub_refuses_clients_before_import_or_helper_execution(self):
        with mock.patch.object(self.runtime, "require_hub", side_effect=self.runtime.MemoryRuntimeError("run hub-start")), \
             mock.patch.object(self.runtime, "prepare_runtime") as prepare, \
             mock.patch.object(self.runtime.runpy, "run_path") as run:
            for mode in ("cli", "mcp", "capture", "validated"):
                with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "hub-start"):
                    self.runtime.dispatch(self.home, self.config, self.records, mode, [])
            prepare.assert_not_called()
            run.assert_not_called()

    def test_init_never_starts_hub_and_refuses_external_palace_or_live_writer(self):
        observed = []
        cli = SimpleNamespace(main=lambda: observed.append(list(sys.argv)))
        with mock.patch.object(self.runtime, "hub_lock", return_value=contextlib.nullcontext()), \
             mock.patch.object(self.runtime, "read_receipt", return_value=None), \
             mock.patch.object(self.runtime, "native_registry", return_value=None), \
             mock.patch.object(self.runtime, "require_hub") as admission, \
             mock.patch.object(self.runtime, "prepare_runtime") as prepare, \
             mock.patch.object(self.runtime.importlib, "import_module", return_value=cli), \
             mock.patch.object(sys, "argv", []):
            args = ["init", "--yes", "--no-llm", "--palace", str(self.home / "memory/palace")]
            self.assertEqual(self.runtime.dispatch(self.home, self.config, self.records, "cli", args), 0)
            self.assertEqual(observed, [["mempalace", *args]])
            admission.assert_not_called()
            prepare.assert_called_once()
            prepare.reset_mock()
            for args in (["init", "--palace", str(self.home.parent / "external")],
                         ["init", "--palace=" + str(self.home.parent / "external")],
                         ["serve"], ["daemon", "start"]):
                with self.subTest(arguments=args), self.assertRaises(ValueError):
                    self.runtime.dispatch(self.home, self.config, self.records, "cli", args)
            prepare.assert_not_called()
        with mock.patch.object(self.runtime, "hub_lock", return_value=contextlib.nullcontext()), \
             mock.patch.object(self.runtime, "read_receipt", return_value={"pid": 123}), \
             mock.patch.object(self.runtime, "native_registry", return_value=None), \
             mock.patch.object(self.runtime, "owned_process", return_value={"pid": 123}), \
             mock.patch.object(self.runtime, "prepare_runtime") as prepare:
            with self.assertRaisesRegex(ValueError, "Stop the palace hub"):
                self.runtime.dispatch(self.home, self.config, self.records, "cli", ["init"])
            prepare.assert_not_called()

    def test_ready_requires_owned_registry_before_any_health_request(self):
        receipt = {"pid": 123}
        foreign = {"pid": 456, "host": "127.0.0.1", "port": 8000, "scheme": "http",
                   "read_only": False, "palace_path": str(self.home / "memory/palace")}
        with mock.patch.object(self.runtime, "require_linux"), \
             mock.patch.object(self.runtime, "read_receipt", return_value=receipt), \
             mock.patch.object(self.runtime, "owned_process", return_value={"pid": 123}), \
             mock.patch.object(self.runtime, "native_registry", return_value=foreign), \
             mock.patch.object(self.runtime.request, "build_opener") as opener:
            with self.assertRaisesRegex(ValueError, "registry does not match"):
                self.runtime.require_hub(self.home, self.config)
            opener.assert_not_called()

    def test_readiness_rechecks_lifetime_after_loopback_health(self):
        receipt = {"pid": 123}
        info = {"pid": 123, "host": "127.0.0.1", "port": 8000, "scheme": "http",
                "read_only": False, "palace_path": str(self.home / "memory/palace")}
        response = mock.MagicMock()
        response.__enter__.return_value.status = 200
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(self.runtime, "require_linux"), \
             mock.patch.object(self.runtime, "read_receipt", return_value=receipt), \
             mock.patch.object(self.runtime, "owned_process", side_effect=[{"pid": 123}, None]), \
             mock.patch.object(self.runtime, "native_registry", return_value=info), \
             mock.patch.object(self.runtime.request, "build_opener", return_value=opener):
            with self.assertRaisesRegex(ValueError, "ownership changed"):
                self.runtime.require_hub(self.home, self.config)
        opener.open.assert_called_once_with("http://127.0.0.1:8000/healthz", timeout=2.0)

    def test_stop_refuses_recycled_pid_before_sending_signal(self):
        receipt = {"pid": 123, "command": ["owned"], "start_ticks": 10}
        replacement = {"pid": 123, "command": ["other"], "start_ticks": 20}
        with mock.patch.object(self.runtime, "require_linux"), \
             mock.patch.object(self.runtime, "_pidfd_open", return_value=987), \
             mock.patch.object(self.runtime.os, "close") as close, \
             mock.patch.object(self.runtime, "process_identity", return_value=replacement), \
             mock.patch.object(self.runtime, "_pidfd_send_signal") as send:
            with self.assertRaisesRegex(ValueError, "not the recorded owned process"):
                self.runtime.terminate_owned(receipt, self.config)
            send.assert_not_called()
            close.assert_called_once_with(987)

    @unittest.skipUnless(sys.platform == "linux", "Linux process lifetime proof")
    def test_pidfd_stops_only_the_recorded_public_test_child(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            identity = self.runtime.process_identity(child.pid)
            self.assertEqual(identity["pid"], child.pid)
            self.assertEqual(identity["uid"], os.getuid())
            self.assertEqual(identity["python_real"], str(Path(sys.executable).resolve()))
            self.assertEqual(identity["command"], [sys.executable, "-c", "import time; time.sleep(30)"])
            self.runtime.terminate_owned(identity, self.config)
            self.assertLess(child.wait(timeout=1), 0)
            self.assertIsNone(self.runtime.process_identity(child.pid))
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=2)

    def test_hub_child_binds_cache_then_calls_native_http_in_same_process(self):
        nonce = "a" * 64
        receipt = {"pid": os.getpid(), "nonce": nonce}
        observed = []
        server = SimpleNamespace(main=lambda: observed.append(list(sys.argv)))
        with mock.patch.object(self.runtime, "require_linux"), \
             mock.patch.object(self.runtime, "read_receipt", return_value=receipt), \
             mock.patch.object(self.runtime, "owned_process", return_value={"pid": os.getpid()}), \
             mock.patch.object(self.runtime, "prepare_runtime") as prepare, \
             mock.patch.object(self.runtime.importlib, "import_module", return_value=server) as imports, \
             mock.patch.object(sys, "argv", []):
            self.assertEqual(self.runtime.run_hub(self.home, self.config, nonce), 0)
        prepare.assert_called_once_with(self.home, self.binding)
        imports.assert_called_once_with("mempalace.mcp_server")
        self.assertEqual(observed, [["mempalace-mcp", "--palace", str(self.home / "memory/palace"),
                                     "--transport", "http", "--host", "127.0.0.1", "--port", "0"]])

    def test_start_is_idempotent_and_never_adopts_registered_foreign_writer(self):
        (self.home / "memory/palace").mkdir(parents=True)
        expected = {"status": "running", "pid": 123, "owned": True}
        with mock.patch.object(self.runtime, "hub_lock", return_value=contextlib.nullcontext()), \
             mock.patch.object(self.runtime, "read_receipt", return_value={"pid": 123}), \
             mock.patch.object(self.runtime, "owned_process", return_value={"pid": 123}), \
             mock.patch.object(self.runtime, "require_hub", return_value=expected), \
             mock.patch.object(self.runtime.subprocess, "Popen") as spawn:
            self.assertEqual(self.runtime.hub_start(self.home, self.config), expected)
            spawn.assert_not_called()
        with mock.patch.object(self.runtime, "hub_lock", return_value=contextlib.nullcontext()), \
             mock.patch.object(self.runtime, "read_receipt", return_value=None), \
             mock.patch.object(self.runtime, "native_registry", return_value={"pid": 456}), \
             mock.patch.object(self.runtime, "process_identity", return_value={"pid": 456}), \
             mock.patch.object(self.runtime.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(ValueError, "Another live native writer"):
                self.runtime.hub_start(self.home, self.config)
            spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
