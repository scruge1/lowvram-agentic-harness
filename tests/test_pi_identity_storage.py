"""Project identity storage stays inside the explicitly selected agent home."""

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


WORKFLOW = Path(__file__).resolve().parents[1] / "adapters" / "pi" / "project-workflow"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, WORKFLOW / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


identity = load("pi_storage_identity", "project_identity.py")


class PiIdentityStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("PI_PROJECT_STATE_BASE", None)

    def test_selected_base_routes_identity_and_actual_knowledge_writer(self):
        selected = self.root / "selected-home" / "state" / "projects"
        os.environ["PI_PROJECT_STATE_BASE"] = str(selected)
        document, created = identity.initialize_identity(self.project, native_authority="user-request:test")
        self.assertTrue(created)
        state = selected.resolve() / document["project_id"]
        self.assertEqual(document["state_root"], str(state))
        self.assertEqual(document["knowledge_index"], str(state / "knowledge"))
        self.assertEqual(document["native_authority"], "user-request:test")
        pointer = self.project / ".icm" / "project.json"
        before = pointer.read_bytes()
        self.assertEqual(identity.load_identity(self.project), document)
        with mock.patch.dict(sys.modules, {"project_identity": identity}):
            knowledge = load("pi_storage_knowledge", "project_knowledge.py")
        result = knowledge.build(self.project)
        self.assertEqual(Path(result["index"]), state / "knowledge.db")
        self.assertTrue(Path(result["index"]).is_file())
        self.assertEqual(pointer.read_bytes(), before)

    def test_default_serialization_remains_exact_and_can_be_reopened(self):
        document, _ = identity.initialize_identity(self.project)
        state = f"~/.local/state/pi-projects/{document['project_id']}"
        self.assertEqual(document["state_root"], state)
        self.assertEqual(document["knowledge_index"], state + "/knowledge")
        self.assertEqual(identity.load_identity(self.project), document)

    def test_existing_identity_is_not_silently_migrated_to_another_base(self):
        document, _ = identity.initialize_identity(self.project)
        pointer = self.project / ".icm" / "project.json"
        original = pointer.read_bytes()
        os.environ["PI_PROJECT_STATE_BASE"] = str(self.root / "new-state")
        with self.assertRaisesRegex(identity.ProjectIdentityError, "not migrated"):
            identity.initialize_identity(self.project)
        self.assertEqual(pointer.read_bytes(), original)
        self.assertFalse((self.root / "new-state").exists())
        self.assertEqual(json.loads(original)["project_id"], document["project_id"])

    def test_tampered_knowledge_pointer_is_refused_without_rewriting_identity(self):
        os.environ["PI_PROJECT_STATE_BASE"] = str(self.root / "selected-state")
        identity.initialize_identity(self.project)
        pointer = self.project / ".icm" / "project.json"
        document = json.loads(pointer.read_bytes())
        document["knowledge_index"] = str(self.root / "elsewhere")
        pointer.write_text(json.dumps(document))
        before = pointer.read_bytes()
        with self.assertRaisesRegex(identity.ProjectIdentityError, "knowledge_index"):
            identity.load_identity(self.project)
        self.assertEqual(pointer.read_bytes(), before)

    def test_invalid_explicit_base_refuses_before_identity_creation(self):
        for value in ("", "relative/state", "~/.local/state", "  /state  "):
            with self.subTest(value=value):
                os.environ["PI_PROJECT_STATE_BASE"] = value
                with self.assertRaises(identity.ProjectIdentityError):
                    identity.initialize_identity(self.project)
                self.assertFalse((self.project / ".icm").exists())

    def test_existing_symlink_parent_is_canonicalized(self):
        actual = self.root / "actual"
        actual.mkdir()
        alias = self.root / "alias"
        try:
            alias.symlink_to(actual, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Directory symlinks are unavailable: {exc}")
        os.environ["PI_PROJECT_STATE_BASE"] = str(alias / "projects")
        document, _ = identity.initialize_identity(self.project)
        self.assertEqual(document["state_root"], str(actual.resolve() / "projects" / document["project_id"]))
        self.assertEqual(identity.load_identity(self.project), document)


if __name__ == "__main__":
    unittest.main()
