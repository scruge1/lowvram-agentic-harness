"""Real Git source admission before any native UI compiler or output write."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from scripts.build_project_board_assets import native_source_identity


@unittest.skipUnless(shutil.which("git"), "Native source admission requires Git")
class NativeBoardSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="native-board-source-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.git("init", "--quiet")
        self.module = self.root / "packages/ui/component.js"
        self.module.parent.mkdir(parents=True)
        self.module.write_text("export const fixture = 'original';\n", encoding="utf-8")
        (self.root / "LICENSE").write_text("Synthetic fixture licence only\n", encoding="utf-8")
        (self.root / ".gitignore").write_text("generated/\nnode_modules/\n", encoding="utf-8")
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--quiet", "-m", "Fixture source")
        self.commit = self.git("rev-parse", "HEAD").strip()

    def git(self, *arguments):
        return subprocess.check_output(["git", *arguments], cwd=self.root, text=True, stderr=subprocess.PIPE)

    def test_transitive_tracked_and_staged_source_refuse(self):
        identity = native_source_identity(self.root, self.commit)
        self.assertEqual(identity["tree"], self.git("rev-parse", "HEAD^{tree}").strip())
        self.module.write_text("export const fixture = 'changed';\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "clean native Git"):
            native_source_identity(self.root, self.commit)
        self.git("add", "packages/ui/component.js")
        with self.assertRaisesRegex(ValueError, "clean native Git"):
            native_source_identity(self.root, self.commit)
        self.module.write_text("export const fixture = 'original';\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "clean native Git"):
            native_source_identity(self.root, self.commit)

    def test_ignored_source_is_not_mistaken_for_dependency_artifacts(self):
        dependency = self.root / "node_modules/fixture.js"
        dependency.parent.mkdir()
        dependency.write_text("/* synthetic dependency fixture */", encoding="utf-8")
        self.assertEqual(native_source_identity(self.root, self.commit)["commit"], self.commit)
        generated = self.root / "generated/other-source.js"
        generated.parent.mkdir()
        generated.write_text("/* ignored source is still refused */", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Untracked native source"):
            native_source_identity(self.root, self.commit)

    def test_wrong_commit_and_nested_root_refuse(self):
        with self.assertRaisesRegex(ValueError, "HEAD differs"):
            native_source_identity(self.root, "0" * 40)
        with self.assertRaisesRegex(ValueError, "checkout root"):
            native_source_identity(self.module.parent, self.commit)


if __name__ == "__main__":
    unittest.main()
