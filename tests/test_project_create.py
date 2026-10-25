"""Real Git/factory source controls; board calls below are explicit fixtures."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from harness import home as factory


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "adapters/pi/project-workflow"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


creator = load(WORKFLOW / "project_create.py", "project_create_source_fixture")
identity = load(WORKFLOW / "project_identity.py", "project_create_identity_fixture")


@unittest.skipUnless(shutil.which("git"), "The existing home factory requires Git")
class ProjectCreateTests(unittest.TestCase):
    def setUp(self):
        selected = os.environ.get("PROJECT_CREATE_TEST_ROOT")
        if selected is None and os.name == "nt" and Path("E:/").is_dir():
            selected = "E:/"
        self.temporary = tempfile.TemporaryDirectory(prefix="managed-project-create-", dir=selected)
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.home = self.base / "Agent home ü"
        factory.scaffold(self.home, source=ROOT, profile="core", base_url="http://127.0.0.1:9/v1",
                         model="no-model-source-fixture", offline=True)
        config = self.home / "home.json"
        value = json.loads(config.read_text(encoding="utf-8"))
        value["installed"]["hermes"] = {"fixture": "Unit board stub only; not native package acceptance"}
        config.write_text(json.dumps(value), encoding="utf-8")
        self.environment = mock.patch.dict(os.environ, {
            "AGENT_HOME": str(self.home), "PI_CODING_AGENT_DIR": str(self.home / "agent"),
            "PI_PROJECT_STATE_BASE": str(self.home / "state/projects"),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def board_fixture(self, home, request):
        self.assertEqual(request["action"], "project_admit")
        self.assertTrue(request["initialize"])
        root = Path(request["project_root"])
        document, _ = identity.initialize_identity(root, native_authority="Explicit isolated source fixture")
        return {"schema": "pi-kanban-result/v1", "ok": True, "action": "project_admit",
                "result": {"project_root": str(root), "identity": document, "workspace": {"state": "scaffolded"}},
                "limits": ["Synthetic board fixture; native Hermes qualification is separate."]}

    def test_existing_factory_creates_own_unborn_git_and_instructions(self):
        with mock.patch.object(factory, "check_package", return_value=None), \
                mock.patch.object(factory, "board", side_effect=self.board_fixture):
            created = creator.create_project(self.home, "report-1")
        root = self.home / "projects/report-1"
        self.assertEqual(created["action"], "project_create")
        self.assertEqual(created["result"]["project_root"], str(root))
        self.assertIn("ACTIVE-CHECKPOINT", (root / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertIn(".env", (root / ".gitignore").read_text(encoding="utf-8"))
        git = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, encoding="utf-8", check=True)
        self.assertEqual(Path(git.stdout.strip()).resolve(), root)
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "HEAD"], capture_output=True)
        self.assertNotEqual(head.returncode, 0, "Creation must not make an automatic commit")
        ignored = subprocess.run(["git", "-C", str(root), "check-ignore", ".env", ".icm/project.json"], capture_output=True)
        self.assertEqual(ignored.returncode, 0)

    def test_invalid_names_and_git_overrides_refuse_before_factory(self):
        with mock.patch.object(factory, "project") as operation:
            for name in ("", "../escape", "/absolute", "a/b", "a\\b", "two words", "ü", "-option", "x" * 81):
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, "short project name"):
                    creator.create_project(self.home, name)
            for key in creator.GIT_PATH_OVERRIDES:
                with self.subTest(variable=key), mock.patch.dict(os.environ, {key: str(self.base)}), \
                        self.assertRaisesRegex(ValueError, "Git path override"):
                    creator.create_project(self.home, "safe")
            operation.assert_not_called()
        self.assertEqual(list((self.home / "projects").iterdir()), [])

    def test_collision_preserves_bytes_and_never_reinitializes(self):
        root = self.home / "projects/existing"
        root.mkdir()
        marker = root / "keep.txt"
        marker.write_bytes(b"existing project content")
        with mock.patch.object(factory, "project") as operation, self.assertRaisesRegex(ValueError, "without initialize"):
            creator.create_project(self.home, "existing")
        operation.assert_not_called()
        self.assertEqual(marker.read_bytes(), b"existing project content")

    def test_partial_factory_failure_preserves_git_and_instructions(self):
        with mock.patch.object(factory, "check_package", return_value=None), \
                mock.patch.object(factory, "board", side_effect=ValueError("Synthetic board failure")), \
                self.assertRaisesRegex(ValueError, "Partial project preserved.*without initialize"):
            creator.create_project(self.home, "partial")
        root = self.home / "projects/partial"
        self.assertTrue((root / ".git").is_dir())
        self.assertTrue((root / "AGENTS.md").is_file())
        with self.assertRaisesRegex(ValueError, "already exists"):
            creator.selected_target(self.home, "partial")

    def test_symlink_parent_and_dangling_destination_refuse(self):
        projects = self.home / "projects"
        outside = self.base / "outside"
        outside.mkdir()
        projects.rmdir()
        try:
            projects.symlink_to(outside, target_is_directory=True)
        except OSError:
            projects.mkdir()
            self.skipTest("Directory symlink creation requires host support")
        with self.assertRaisesRegex(ValueError, "canonical directory"):
            creator.selected_target(self.home, "escape")
        self.assertEqual(list(outside.iterdir()), [])
        projects.unlink()
        projects.mkdir()
        (projects / "dangling").symlink_to(outside / "missing", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "already exists"):
            creator.selected_target(self.home, "dangling")

    def test_installed_binding_wrong_home_and_source_drift(self):
        file = self.home / "runtime" / creator.RELATIVE
        installed = load(file, "installed_project_create_fixture")
        self.assertEqual(installed.bindings(), (self.home, self.home / "runtime"))
        with mock.patch.dict(os.environ, {"AGENT_HOME": str(self.base)}), self.assertRaisesRegex(ValueError, "explicit environment"):
            installed.bindings()
        file.write_bytes(file.read_bytes() + b"\n# Source drift fixture\n")
        with self.assertRaisesRegex(ValueError, "source drift"):
            installed.bindings()


if __name__ == "__main__":
    unittest.main()
