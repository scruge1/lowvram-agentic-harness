"""Native bootstrap orchestration controls, without runtime downloads or installs."""
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

from harness import bootstrap as b


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.destination = self.root / "native.tar.xz"
        self.body = b"explicit synthetic native archive bytes"
        self.sha = hashlib.sha256(self.body).hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def test_native_resume_and_absent_only_hash_checked_promotion(self):
        partial = self.destination.with_name(self.destination.name + ".partial")
        partial.write_bytes(self.body[:5])
        def native(argv, **kwargs):
            self.assertEqual(argv[:2], ["/usr/bin/curl", "-q"])
            self.assertIn("--continue-at", argv)
            self.assertIn("--noproxy", argv)
            self.assertEqual(kwargs["env"], {"test": "owned"})
            with partial.open("ab") as stream:
                stream.write(self.body[5:])
        b.download("https://example.org/file", self.destination, self.sha, len(self.body), env={"test": "owned"}, runner=native)
        self.assertEqual(self.destination.read_bytes(), self.body)
        self.assertFalse(partial.exists())

    def test_complete_partial_needs_no_refetch(self):
        partial = self.destination.with_name(self.destination.name + ".partial")
        partial.write_bytes(self.body)
        native = Mock(side_effect=AssertionError("No duplicate transfer"))
        b.download("https://example.org/file", self.destination, self.sha, len(self.body), env={}, runner=native)
        native.assert_not_called()

    def test_conflicting_final_never_changes_or_starts_network(self):
        self.destination.write_bytes(b"preserve original")
        native = Mock()
        with self.assertRaisesRegex(b.BootstrapError, "final download conflicts"):
            b.download("https://example.org/file", self.destination, self.sha, len(self.body), env={}, runner=native)
        self.assertEqual(self.destination.read_bytes(), b"preserve original")
        native.assert_not_called()

    def test_hash_failure_retains_partial_and_has_no_final(self):
        partial = self.destination.with_name(self.destination.name + ".partial")
        def native(*_args, **_kwargs):
            partial.write_bytes(b"x" * len(self.body))
        with self.assertRaisesRegex(b.BootstrapError, "failed partial retained"):
            b.download("https://example.org/file", self.destination, self.sha, len(self.body), env={}, runner=native)
        self.assertEqual(partial.read_bytes(), b"x" * len(self.body))
        self.assertFalse(self.destination.exists())

    def test_free_space_refusal_precedes_network(self):
        native = Mock()
        with patch.object(b.shutil, "disk_usage", return_value=shutil._ntuple_diskusage(100, 99, 1)):
            with self.assertRaisesRegex(b.BootstrapError, "free-space reserve"):
                b.download("https://example.org/file", self.destination, self.sha, len(self.body), env={}, runner=native)
        native.assert_not_called()
        self.assertFalse(self.destination.exists())

    def test_oversized_partial_is_retained(self):
        partial = self.destination.with_name(self.destination.name + ".partial")
        partial.write_bytes(self.body + b"unexpected")
        with self.assertRaisesRegex(b.BootstrapError, "Oversized partial"):
            b.download("https://example.org/file", self.destination, self.sha, len(self.body), env={}, runner=Mock())
        self.assertEqual(partial.read_bytes(), self.body + b"unexpected")

    def test_archive_paths_and_external_links_refused_before_native_extraction(self):
        for name, link in (("../escape", None), (b.NODE_NAME + "/outside", "../../outside")):
            archive = self.root / ("bad-link.tar.xz" if link else "bad-path.tar.xz")
            with tarfile.open(archive, "w:xz") as stream:
                item = tarfile.TarInfo(name)
                if link:
                    item.type, item.linkname = tarfile.SYMTYPE, link
                    stream.addfile(item)
                else:
                    item.size = 3
                    stream.addfile(item, io.BytesIO(b"bad"))
            with patch.object(b, "command") as native:
                with self.assertRaises(b.BootstrapError):
                    b.extract_node(archive, self.root, env={})
                native.assert_not_called()
            self.assertFalse((self.root.parent / "escape").exists())

    def test_existing_node_tree_not_overwritten_without_receipt(self):
        (self.root / b.NODE_NAME).mkdir()
        with self.assertRaisesRegex(b.BootstrapError, "not overwritten"):
            b.extract_node(self.root / "unused", self.root, env={})

    @unittest.skipIf(os.name == "nt", "Native symlink control needs no Windows elevation")
    def test_redirected_runtime_inventory_refused_before_reading_outside(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "private.txt").write_text("private fixture")
        alias = self.root / "alias"
        alias.symlink_to(outside, target_is_directory=True)
        with patch.object(b, "sha256", side_effect=AssertionError("Do not read outside the selected prefix")):
            with self.assertRaisesRegex(b.BootstrapError, "redirected"):
                b.inventory(alias)

    def test_owned_child_environment_preserves_home_and_excludes_ambient_hooks(self):
        hostile = {"HOME": str(self.root), "HTTP_PROXY": "private", "HF_TOKEN": "private", "PYTHONPATH": "untrusted",
                   "NODE_OPTIONS": "--require private", "UV_PYTHON_INSTALL_MIRROR": "untrusted"}
        with patch.dict(os.environ, hostile, clear=True):
            value = b.owned_environment(self.root, self.root / "node/bin/node")
            self.assertEqual(dict(os.environ), hostile)
        self.assertEqual(value["HOME"], str(self.root))
        self.assertEqual(value["PATH"].split(os.pathsep)[0], str(self.root / "node/bin"))
        self.assertTrue(all(key not in value for key in hostile if key != "HOME"))
        self.assertEqual(value["XDG_CACHE_HOME"], str(self.root / "cache"))

    def process_helper(self, body):
        helper = self.root / b.NATIVE_PIDFD_SOURCE
        helper.parent.mkdir(parents=True, exist_ok=True)
        helper.write_text(body, encoding="utf-8")
        return helper, hashlib.sha256(helper.read_bytes()).hexdigest()

    def test_process_preflight_accepts_exact_facade_and_records_backend(self):
        helper, pin = self.process_helper("def require_support(): return {'pidfd_open':'python','pidfd_send_signal':'libc'}\n")
        with patch.object(b.sys, "platform", "linux"), patch.object(b, "NATIVE_PIDFD_SHA256", pin):
            result = b.process_api_preflight(self.root)
        self.assertEqual(result["source"], str(helper))
        self.assertEqual(result["source_sha256"], pin)
        self.assertEqual(result["backend"], {"pidfd_open": "python", "pidfd_send_signal": "libc"})

    def test_process_preflight_refuses_helper_drift_before_execution(self):
        marker = self.root / "must-not-execute"
        self.process_helper("from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('executed')\n")
        with patch.object(b.sys, "platform", "linux"):
            with self.assertRaisesRegex(b.BootstrapError, "helper byte drift"):
                b.process_api_preflight(self.root)
        self.assertFalse(marker.exists())

    @unittest.skipIf(os.name == "nt", "Native symlink control needs no Windows elevation")
    def test_process_preflight_refuses_redirected_canonical_helper(self):
        helper, pin = self.process_helper("def require_support(): return {'pidfd_open':'libc','pidfd_send_signal':'libc'}\n")
        alternate = self.root / "alternate-helper.py"
        helper.rename(alternate)
        helper.symlink_to(alternate)
        with patch.object(b.sys, "platform", "linux"), patch.object(b, "NATIVE_PIDFD_SHA256", pin):
            with self.assertRaisesRegex(b.BootstrapError, "redirected"):
                b.process_api_preflight(self.root)

    def test_process_preflight_unsupported_kernel_or_backend_fails_clearly(self):
        for body in ("def require_support(): raise OSError(38,'unsupported kernel')\n",
                     "def require_support(): return {'pidfd_open':'unavailable','pidfd_send_signal':'unavailable'}\n"):
            _, pin = self.process_helper(body)
            with patch.object(b.sys, "platform", "linux"), patch.object(b, "NATIVE_PIDFD_SHA256", pin):
                with self.assertRaisesRegex(b.BootstrapError, "before package installation|package installation was not started"):
                    b.process_api_preflight(self.root)

    def test_process_preflight_rejects_wrong_platform_without_loading_helper(self):
        with patch.object(b.sys, "platform", "win32"):
            with self.assertRaisesRegex(b.BootstrapError, "requires Linux"):
                b.process_api_preflight(self.root)

    def test_process_preflight_failure_precedes_node_download_and_home_creation(self):
        home = self.root / "new-home"
        root = Path(str(home) + "-runtimes")
        for name in ("downloads", "cache", "tmp", "python", "bin"):
            (root / name).mkdir(parents=True, exist_ok=True)
        (root / "bootstrap-owner").write_text("agent-home-bootstrap/v1:" + str(home))
        python = root / "python" / b.PYTHON_KEY / "bin/python3.12"
        with patch.object(b.sys, "platform", "linux"), patch.object(b.platform, "machine", return_value="x86_64"), \
                patch.object(b.platform, "python_version", return_value="3.12.13"), patch.object(b.sys, "executable", str(python)), \
                patch.object(b, "process_api_preflight", side_effect=b.BootstrapError("unsupported process APIs")), \
                patch.object(b, "download") as download, patch.object(b, "command") as native:
            with self.assertRaisesRegex(b.BootstrapError, "unsupported process APIs"):
                b.provision(home, root)
        download.assert_not_called()
        native.assert_not_called()
        self.assertFalse(home.exists())

    def test_existing_installer_handoff_pins_both_runtimes_without_shell(self):
        receipt = {"home": "/selected home", "python": {"path": "/permanent/python"}, "node": {"path": "/permanent/node/bin/node"}}
        command = b.installer_command(receipt, ["--base-url", "http://127.0.0.1:8080/v1", "--model", "owner-model"])
        self.assertEqual(command[:7], ["/permanent/python", "-B", "-m", "harness.home", "--home", "/selected home", "install"])
        self.assertEqual(command[7:11], ["--python312", "/permanent/python", "--managed-node", "/permanent/node/bin/node"])
        self.assertIn("resume-install", b.installer_command(receipt, [], resume=True))
        for key in ("--home=other", "--python312", "--managed-node=other", "--source=other"):
            with self.assertRaises(b.BootstrapError):
                b.installer_command(receipt, [key])
        with self.assertRaises(b.BootstrapError):
            b.installer_command(receipt, ["--model", "different"], resume=True)

    @unittest.skipUnless(sys.platform == "linux" and shutil.which("bash"), "Initial shell bootstrap is Linux only")
    def test_shell_plan_creates_nothing_and_native_pins_match(self):
        home = self.root / "new home"
        result = subprocess.run(["bash", str(b.SOURCE / "install.sh"), "--home", str(home), "--plan"],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(home) + "-runtimes", result.stdout)
        self.assertIn("31,058,332", result.stdout)
        self.assertFalse(home.exists())
        self.assertFalse(Path(str(home) + "-runtimes").exists())
        source = (b.SOURCE / "install.sh").read_text()
        self.assertIn(b.UV_SHA256, source)
        self.assertIn(b.PYTHON_KEY, source)


if __name__ == "__main__":
    unittest.main()
