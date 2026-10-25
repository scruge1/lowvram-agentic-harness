"""Target binding and local-checkout provenance controls; no model or live board."""

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
INTAKE = ROOT / "adapters" / "pi" / "intake"
WORKFLOW = ROOT / "adapters" / "pi" / "project-workflow"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


binding = load("pi_framework_binding", INTAKE / "framework_binding.py")


class Record(str):
    pass


class FrameworkBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.module = self.base / "agent_framework" / "__init__.py"
        self.module.parent.mkdir()
        self.module.write_bytes(b"# Recorded fixture source\n")
        item = Record("agent_framework/__init__.py")
        item.hash = SimpleNamespace(mode="sha256", value=base64.urlsafe_b64encode(
            hashlib.sha256(self.module.read_bytes()).digest()).decode().rstrip("="))
        self.dist = SimpleNamespace(version="1.21.0", files=[item],
                                    locate_file=lambda file: self.base / str(file))

    def test_binding_uses_actual_target_bytes_and_refuses_replacement(self):
        output = self.base / "runtime.json"
        with mock.patch.object(binding.metadata, "distribution", return_value=self.dist):
            result = binding.write_binding(output)
        value = json.loads(output.read_bytes())
        self.assertEqual(value["python"], str(Path(sys.executable).absolute()))
        self.assertEqual(value["helper"], str((INTAKE / "decision-138.py").resolve()))
        self.assertEqual(value["files"], [{"path": str(self.module.resolve()),
                                          "sha256": hashlib.sha256(self.module.read_bytes()).hexdigest()}])
        self.assertEqual(result["sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
        original = output.read_bytes()
        with mock.patch.object(binding.metadata, "distribution") as inspect:
            with self.assertRaises(FileExistsError):
                binding.write_binding(output)
            inspect.assert_not_called()
        self.assertEqual(output.read_bytes(), original)

    def test_record_drift_refuses_before_publication(self):
        self.module.write_bytes(b"# Changed after package installation\n")
        with mock.patch.object(binding.metadata, "distribution", return_value=self.dist):
            with self.assertRaisesRegex(ValueError, "RECORD"):
                binding.write_binding(self.base / "runtime.json")
        self.assertFalse((self.base / "runtime.json").exists())

    def test_unknown_or_different_distribution_refuses(self):
        for version, files, reason in [("1.23.0", self.dist.files, "version"),
                                       ("1.21.0", [], "inventory")]:
            with self.subTest(version=version, files=len(files)):
                self.dist.version, self.dist.files = version, files
                with mock.patch.object(binding.metadata, "distribution", return_value=self.dist):
                    with self.assertRaisesRegex(ValueError, reason):
                        binding.build_binding()

    def test_relative_destination_refuses_before_environment_inspection(self):
        with mock.patch.object(binding.metadata, "distribution") as inspect:
            with self.assertRaisesRegex(ValueError, "absolute"):
                binding.write_binding(Path("runtime.json"))
            inspect.assert_not_called()


@unittest.skipUnless(shutil.which("git"), "Git is required for actual checkout provenance controls")
class HermesCheckoutProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        # Spaces and shell metacharacters must remain literal argv path bytes.
        self.source = self.base / "source with spaces & symbols"
        self.source.mkdir()
        self.git("init", "--quiet")
        self.file = self.source / "source.py"
        self.file.write_text("# Original\n", encoding="utf-8")
        self.git("add", "source.py")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "fixture")
        self.commit = self.git("rev-parse", "HEAD").stdout.strip()
        self.modules = {name: ModuleType("hermes_cli." + name)
                        for name in ("kanban_db", "kanban_db_connect", "kanban_db_graph")}
        package = ModuleType("hermes_cli")
        for name, module in self.modules.items():
            module.__file__ = str(self.file)
            setattr(package, name, module)
        overrides = {"hermes_cli": package,
                     **{"hermes_cli." + key: value for key, value in self.modules.items()}}
        with mock.patch.dict(sys.modules, overrides), mock.patch.object(sys, "path", [str(WORKFLOW), *sys.path]):
            self.adapter = load("pi_intake_backend_fixture", WORKFLOW / "pi_kanban.py")
        self.adapter.EXPECTED_HERMES_COMMIT = self.commit
        self.adapter.EXPECTED_MODULE_HASHES = {key: hashlib.sha256(self.file.read_bytes()).hexdigest()
                                               for key in self.modules}
        self.direct = {"url": self.source.as_uri(), "dir_info": {}}

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.source), *args], text=True,
                              capture_output=True, check=True, timeout=10)

    def package_commit(self):
        dist = SimpleNamespace(read_text=lambda _name: json.dumps(self.direct))
        with mock.patch.object(self.adapter.importlib.metadata, "distribution", return_value=dist):
            return self.adapter.package_commit()

    def test_clean_exact_native_git_checkout_is_accepted(self):
        self.assertEqual(self.package_commit(), self.commit)

    def test_tracked_dirty_source_refuses_even_when_installed_hashes_match(self):
        self.file.write_text("# Changed\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "tracked changes"):
            self.package_commit()

    def test_wrong_revision_and_remote_file_host_refuse(self):
        self.adapter.EXPECTED_HERMES_COMMIT = "0" * 40
        with self.assertRaisesRegex(ValueError, "revision drift"):
            self.package_commit()
        self.direct["url"] = "file://untrusted.invalid/source"
        with self.assertRaisesRegex(ValueError, "local file URL"):
            self.package_commit()

    def test_original_vcs_identity_remains_supported(self):
        self.direct = {"url": "https://example.invalid/hermes.git",
                       "vcs_info": {"commit_id": self.commit}}
        self.assertEqual(self.package_commit(), self.commit)


if __name__ == "__main__":
    unittest.main()
