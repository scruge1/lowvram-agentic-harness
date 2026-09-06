import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from harness.integration import (
    PRD_NAME,
    PROFILE_NAME,
    IntegrationError,
    init_integration,
)
from ssot.workflow import doctor_project


class IntegrationBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_bootstrap_is_source_bound_and_deliberately_unresolved(self):
        instructions = self.root / "AGENTS.md"
        instructions.write_text("# Target rules\n", encoding="utf-8")
        result = init_integration(
            self.root,
            "claude-code",
            ["AGENTS.md"],
            ["enforcement", "ssot"],
        )
        self.assertEqual(result["status"], "scaffolded")
        self.assertEqual(result["authority"], "no_installation_authority")
        self.assertFalse(result["ready"])
        profile = json.loads((self.root / PROFILE_NAME).read_text(encoding="utf-8"))
        self.assertEqual(profile["host"], "claude-code")
        self.assertEqual(
            profile["declared_surfaces"][0]["sha256"],
            hashlib.sha256(instructions.read_bytes()).hexdigest(),
        )
        manifest = json.loads(
            (self.root / "ssot-project.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest["requirements"][0]["source"]["sha256"],
            hashlib.sha256((self.root / PRD_NAME).read_bytes()).hexdigest(),
        )
        diagnosis = doctor_project(self.root)
        self.assertFalse(diagnosis["ready"])
        self.assertIn("REQ-UNRESOLVED-001", diagnosis["unresolved_requirements"])

    def test_existing_ssot_is_not_replaced(self):
        (self.root / "ssot-project.json").write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(IntegrationError, "add integration stages"):
            init_integration(self.root, "generic")
        self.assertFalse((self.root / PRD_NAME).exists())
        self.assertFalse((self.root / PROFILE_NAME).exists())

    def test_surface_cannot_escape_target(self):
        with self.assertRaisesRegex(IntegrationError, "escapes target root"):
            init_integration(self.root, "pi", ["../outside.md"])
        self.assertFalse((self.root / PRD_NAME).exists())

    def test_existing_setup_file_is_not_overwritten(self):
        existing = self.root / PRD_NAME
        existing.write_text("retain me\n", encoding="utf-8")
        with self.assertRaisesRegex(IntegrationError, "refusing to overwrite"):
            init_integration(self.root, "hermes")
        self.assertEqual(existing.read_text(encoding="utf-8"), "retain me\n")
        self.assertFalse((self.root / PROFILE_NAME).exists())

    def test_new_authority_requires_a_declared_target_surface(self):
        with self.assertRaisesRegex(IntegrationError, "declare at least one"):
            init_integration(self.root, "generic")
        self.assertFalse((self.root / PRD_NAME).exists())
        self.assertFalse((self.root / "ssot-project.json").exists())


if __name__ == "__main__":
    unittest.main()
