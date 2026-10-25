"""Artifact/ownership tests with a synthetic protocol process, never inference.

The lifecycle fixture uses the real Python process, socket inode, inherited
flock and pidfd. Its argv prefix is substituted explicitly; native llama-server
artifact and loaded-model qualification is a separate acceptance run.
"""
import contextlib
import copy
import hashlib
import http.server
import io
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from harness import bootstrap
from harness import model_service as service


SYNTHETIC = r'''#!/usr/bin/python3
import argparse,http.server,json,sys,time
if '--version' in sys.argv:
 print('version: synthetic (d327bf1)',file=sys.stderr);sys.exit(0)
if '--help' in sys.argv:
 print('--n-cpu-moe --api-key-file --fit --no-warmup',file=sys.stderr);sys.exit(0)
p=argparse.ArgumentParser();p.add_argument('--port',type=int);p.add_argument('--alias');p.add_argument('--api-key-file');a,_=p.parse_known_args()
if '--fixture-no-listener' in sys.argv:time.sleep(30);sys.exit(0)
key=open(a.api_key_file).read().strip()
class Handler(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  if self.headers.get('Authorization')!='Bearer '+key:self.send_error(401);return
  body={'data':[{'id':a.alias}]} if self.path=='/v1/models' else {'status':'ok'}
  raw=json.dumps(body).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def log_message(self,*args):pass
http.server.HTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PlatformTests(unittest.TestCase):
    def test_unsupported_platform_refuses_before_writing(self):
        with mock.patch.object(service.sys, "platform", "win32"), self.assertRaisesRegex(service.ModelServiceError, "Linux x86_64"):
            service.status("nonexistent")

    def test_pins_describe_exact_optional_artifacts_without_model_recommendation(self):
        pins = service._read(service.PINS)
        self.assertIn("No model recommendation", pins["acceptance"])
        self.assertEqual(pins["model"]["bytes"], 5027784800)
        for backend in ("cpu", "cuda"):
            value = service.specification(model=pins["model"]["id"], backend=backend, ram_required_bytes=12 * 1024 ** 3,
                                          gpu_uuid="GPU-1234" if backend == "cuda" else None,
                                          gpu_layers=16 if backend == "cuda" else 0, min_gpu_free_mb=7000 if backend == "cuda" else 0)
            service._validate(value)
            self.assertEqual(value["runtime"]["revision"], "d327bf1f0780f87b8c01b367b61853b0c291d7c4")


@unittest.skipUnless(sys.platform == "linux" and platform.machine() in ("x86_64", "AMD64"), "Linux x64 native lifecycle")
class ModelServiceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="model-service-", dir=os.environ.get("MODEL_SERVICE_TEST_ROOT"))
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.home = self.base / "future Hôme α"
        self.root = Path(str(self.home) + "-runtimes")
        self.root.mkdir()
        (self.root / "bootstrap-owner").write_text("agent-home-bootstrap/v1:" + str(self.home) + "\n")
        self.model = self.base / "public-fixture.gguf"
        self.model.write_bytes(b"GGUF synthetic fixture; not weights\n")
        self.archive = self.base / "native-fixture.tar.gz"
        with tarfile.open(self.archive, "w:gz") as stream:
            item = tarfile.TarInfo("native/llama-server")
            raw = SYNTHETIC.encode()
            item.size, item.mode = len(raw), 0o755
            stream.addfile(item, io.BytesIO(raw))
            item = tarfile.TarInfo("native/LICENSE")
            item.size = 4
            stream.addfile(item, io.BytesIO(b"MIT\n"))
        self.spec = service.specification(model="qwen3vl-8b-instruct-q4-k-m", context=4096, max_output=32,
                                          threads=2, batch_threads=2, ram_required_bytes=12 * 1024 ** 3)
        self.spec["model"].update(name=self.model.name, sha256=digest(self.model), bytes=self.model.stat().st_size)
        self.spec["runtime"]["archives"] = [{"name": self.archive.name, "sha256": digest(self.archive),
                                            "bytes": self.archive.stat().st_size, "unpacked_max_bytes": 1024 ** 2,
                                            "license": "MIT", "url": "https://github.com/ggml-org/llama.cpp/releases/download/b11869/fixture.tar.gz"}]
        self.sources = {self.model.name: str(self.model), self.archive.name: str(self.archive)}

    def provision(self):
        return service.provision(self.home, self.spec, sources=self.sources)

    @contextlib.contextmanager
    def lifecycle(self, *, no_listener=False):
        original = service._argv
        def synthetic_argv(*args):
            value = original(*args)
            return [str(Path(sys.executable).resolve()), *value, *(["--fixture-no-listener"] if no_listener else [])]
        with mock.patch.object(service, "_argv", side_effect=synthetic_argv):
            try:
                yield
            finally:
                file = self.root / "state/model-service/service.json"
                if file.exists():
                    service.stop(self.home)

    def test_plan_precedes_home_creation_and_has_exact_storage_and_downloads(self):
        before = sorted(self.base.rglob("*"))
        value = service.plan(self.home, self.spec)
        self.assertEqual(value["home"], str(self.home))
        self.assertEqual(value["storage_root"], str(self.root))
        self.assertEqual(len(value["downloads"]), 2)
        self.assertEqual(value["fit"], "not_probed")
        self.assertFalse(self.home.exists())
        self.assertEqual(sorted(self.base.rglob("*")), before)

    def test_missing_download_permission_and_low_space_refuse_before_producer_writes(self):
        with self.assertRaisesRegex(service.ModelServiceError, "explicitly allow"):
            service.provision(self.home, self.spec)
        with mock.patch.object(shutil, "disk_usage", return_value=shutil._ntuple_diskusage(1, 1, 0)):
            with self.assertRaisesRegex(service.ModelServiceError, "Insufficient space"):
                self.provision()
        self.assertFalse((self.root / "cache").exists())

    def test_local_copy_native_stderr_inspection_and_idempotence_preserve_originals(self):
        before = {path: (digest(path), path.stat().st_ino) for path in (self.model, self.archive)}
        value = self.provision()
        self.assertIn("d327bf1", value["native_version"])
        self.assertEqual(value["home"], str(self.home))
        self.assertEqual(self.provision(), value)
        self.assertFalse(self.home.exists())
        for path, expected in before.items():
            self.assertEqual((digest(path), path.stat().st_ino), expected)
            self.assertNotEqual(service._artifact(self.root, self.spec["model"] if path == self.model else self.spec["runtime"]["archives"][0]).stat().st_ino, path.stat().st_ino)

    def test_existing_conflicting_final_and_partial_are_preserved(self):
        destination = service._artifact(self.root, self.spec["model"])
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"existing unrelated bytes")
        with self.assertRaisesRegex(service.ModelServiceError, "conflicts"):
            self.provision()
        self.assertEqual(destination.read_bytes(), b"existing unrelated bytes")
        destination.unlink()
        partial = destination.with_name(destination.name + ".partial")
        partial.write_bytes(b"incomplete owned prior transfer")
        with self.assertRaisesRegex(service.ModelServiceError, "partial preserved"):
            self.provision()
        self.assertEqual(partial.read_bytes(), b"incomplete owned prior transfer")

    def test_existing_verified_install_needs_no_second_download_space_reservation(self):
        expected = self.provision()
        with mock.patch.object(shutil, "disk_usage", return_value=shutil._ntuple_diskusage(1, 1, 0)):
            self.assertEqual(self.provision(), expected)

    def test_archive_parent_path_absolute_link_and_hardlink_are_refused(self):
        for index, kind in enumerate(("parent", "symlink", "hardlink")):
            archive = self.base / (kind + ".tar.gz")
            with tarfile.open(archive, "w:gz") as stream:
                item = tarfile.TarInfo("../outside" if kind == "parent" else "native/link")
                if kind == "symlink":
                    item.type, item.linkname = tarfile.SYMTYPE, "/etc/passwd"
                elif kind == "hardlink":
                    item.type, item.linkname = tarfile.LNKTYPE, "../outside"
                stream.addfile(item)
            with self.assertRaises(service.ModelServiceError):
                service._extract(archive, self.base / ("extract-" + str(index)), 1024)
        self.assertFalse((self.base / "outside").exists())

    def test_native_library_links_are_internal_and_runtime_drift_refuses(self):
        self.provision()
        receipt, runtime, _ = service._load(self.root)
        self.assertGreater(len(receipt["runtime_files"]), 0)
        (runtime / "0/native/LICENSE").write_bytes(b"changed")
        with self.assertRaisesRegex(service.ModelServiceError, "runtime bytes changed"):
            service._load(self.root)

    def test_redirected_storage_refuses_before_copy(self):
        foreign = self.base / "foreign-cache"
        foreign.mkdir()
        (self.root / "cache").symlink_to(foreign, target_is_directory=True)
        with self.assertRaisesRegex(service.ModelServiceError, "symlink"):
            self.provision()
        self.assertEqual(list(foreign.iterdir()), [])

    def test_gpu_is_held_even_when_permission_flag_is_explicit(self):
        spec = copy.deepcopy(self.spec)
        spec["runtime"]["backend"] = "cuda"
        spec["resources"].update(gpu_uuid="GPU-1234", gpu_layers=12, min_gpu_free_mb=7000)
        with self.assertRaisesRegex(service.ModelServiceError, "atomic resource-owner"):
            service._resources(spec, allow_gpu=True)

    def test_pidfd_helper_drift_refuses_before_launch(self):
        self.provision()
        with mock.patch.object(service, "PIDFD_SHA256", "0" * 64), self.assertRaisesRegex(service.ModelServiceError, "helper byte drift"):
            service.start(self.home)
        self.assertFalse((self.root / "state/model-service/service.json").exists())

    def test_actual_process_socket_nonce_lifetime_and_exact_stop(self):
        self.provision()
        with self.lifecycle():
            started = service.start(self.home, startup_timeout=5)
            self.assertEqual(started["status"], "running")
            self.assertEqual(started["home"], str(self.home))
            self.assertEqual(service.start(self.home)["pid"], started["pid"])
            self.assertEqual(service.status(self.home)["pid"], started["pid"])
            self.assertFalse(self.home.exists())
            self.assertEqual(service.stop(self.home)["status"], "stopped")
            self.assertIsNone(service._process(started["pid"]))
            self.assertEqual(service.stop(self.home)["status"], "stopped")

    def test_initial_empty_exec_argv_waits_without_weakening_nonempty_identity(self):
        self.provision()
        original = service._process
        samples = []
        def initial_empty(pid):
            value = original(pid)
            if value and not samples:
                samples.append(pid)
                return dict(value, argv=[])
            return value
        with self.lifecycle(), mock.patch.object(service, "_process", side_effect=initial_empty):
            self.assertEqual(service.start(self.home, startup_timeout=5)["status"], "running")
            self.assertEqual(len(samples), 1)

    def test_existing_healthy_foreign_listener_gets_no_probe_or_signal(self):
        self.provision()
        requests = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(200)
                self.end_headers()
            def log_message(self, *_):
                pass
        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.lifecycle(), self.assertRaises(OSError):
                service.start(self.home, port=server.server_port, startup_timeout=1)
            self.assertTrue(thread.is_alive())
            self.assertEqual(requests, [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_foreign_pid_record_refuses_without_signaling_either_process(self):
        self.provision()
        with self.lifecycle():
            started = service.start(self.home, startup_timeout=5)
            path = self.root / "state/model-service/service.json"
            original = service._read(path)
            foreign = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
            try:
                altered = dict(original, pid=foreign.pid, start_ticks=service._process(foreign.pid)["start_ticks"])
                bootstrap.publish_json(path, altered)
                with self.assertRaisesRegex(service.ModelServiceError, "ownership differs"):
                    service.stop(self.home)
                self.assertIsNone(foreign.poll())
                self.assertIsNotNone(service._process(started["pid"]))
            finally:
                bootstrap.publish_json(path, original)
                foreign.terminate()
                foreign.wait(timeout=5)

    def test_recover_exact_startup_argv_after_missing_parent_pid_publication(self):
        self.provision()
        with self.lifecycle():
            started = service.start(self.home, startup_timeout=5)
            path = self.root / "state/model-service/service.json"
            original = service._read(path)
            bootstrap.publish_json(path, dict(original, pid=None, start_ticks=None, phase="starting"))
            self.assertEqual(service.status(self.home)["pid"], started["pid"])
            self.assertEqual(service.start(self.home)["pid"], started["pid"])
            self.assertEqual(service.stop(self.home)["status"], "stopped")

    def test_startup_timeout_stops_only_owned_fixture_and_retains_failure(self):
        self.provision()
        with self.lifecycle(no_listener=True):
            with self.assertRaisesRegex(service.ModelServiceError, "deadline exceeded"):
                service.start(self.home, startup_timeout=1)
            value = service._read(self.root / "state/model-service/service.json")
            self.assertEqual(value["phase"], "stopped")
            self.assertIn("deadline exceeded", value["last_start_failure"])
            self.assertIsNone(service._process(value["pid"]))
            self.assertTrue(Path(value["log"]).is_file())

    def test_nonce_and_source_binding_drift_prevent_service_claim(self):
        self.provision()
        with self.lifecycle():
            service.start(self.home, startup_timeout=5)
            path = self.root / "state/model-service/service.json"
            original = service._read(path)
            try:
                bootstrap.publish_json(path, dict(original, specification_sha256="0" * 64))
                with self.assertRaisesRegex(service.ModelServiceError, "selection differs"):
                    service.status(self.home)
            finally:
                bootstrap.publish_json(path, original)


if __name__ == "__main__":
    unittest.main()
