"""Real Git/native SQLite fixtures; Linux lifecycle claims stay platform-specific."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from harness import project_backup as backup

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(sys.platform == "linux" and shutil.which("git"), "Stopped capture requires the existing Linux lease and Git")
class ProjectBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="project-backup-", dir=os.environ.get("PROJECT_BACKUP_TEST_ROOT"))
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / "home"
        self.project = self.home / "projects/demo"
        self.project.mkdir(parents=True)
        (self.home / "state/projects").mkdir(parents=True)
        backup.json_new(self.home / "home.json", {"schema": "agent-home/v1", "home": str(self.home)})
        installed_entry = backup.home_entry.install(self.home)
        helper = self.home / "runtime/adapters/pi/project-workflow/project_identity.py"
        helper.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / "adapters/pi/project-workflow/project_identity.py", helper)
        manifest = self.home / "runtime/runtime-manifest.json"
        backup.json_new(manifest, {"files": [{"path": "adapters/pi/project-workflow/project_identity.py", "sha256": sha(helper)}]})
        self.config = {"schema": "agent-home/v1", "home": str(self.home),
                       "lifecycle_guard_sha256": installed_entry["guard_sha256"],
                       "lifecycle_launcher_sha256": installed_entry["launcher_sha256"],
                       "runtime_manifest_sha256": sha(manifest)}
        (self.home / "home.json").write_text(json.dumps(self.config), encoding="utf-8")
        self.env = dict(os.environ, PI_PROJECT_STATE_BASE=str(self.home / "state/projects"),
                        GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
        subprocess.run([sys.executable, "-B", str(helper), "init", "--root", str(self.project),
                        "--native-authority", "Synthetic explicit owned test project"], env=self.env,
                       capture_output=True, check=True, timeout=15)
        self.identity = json.loads((self.project / ".icm/project.json").read_text())
        self.state = Path(self.identity["state_root"])
        self.state.mkdir()
        (self.project / "README.md").write_text("# Synthetic project\nOrchard evidence remains independently queryable.\n", encoding="utf-8")
        (self.project / "empty").mkdir()
        self.git("init", "--quiet")
        self.git("add", "README.md")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "core.hooksPath="+os.devnull,
                 "commit", "--quiet", "--no-gpg-sign", "-m", "Synthetic committed input")
        self.writer = sqlite3.connect(self.state / "kanban.db")
        self.addCleanup(self.writer.close)
        self.writer.execute("PRAGMA journal_mode=WAL")
        self.writer.execute("CREATE TABLE tasks(id TEXT PRIMARY KEY, tenant TEXT, title TEXT)")
        self.writer.execute("INSERT INTO tasks VALUES('task1',?, 'Committed WAL card')", (self.identity["board_id"],))
        self.writer.commit()
        self.assertTrue(Path(str(self.state / "kanban.db")+"-wal").is_file())
        knowledge = ROOT / "adapters/pi/project-workflow/project_knowledge.py"
        subprocess.run([sys.executable, "-B", str(knowledge), "build", "--root", str(self.project)],
                       env=self.env, capture_output=True, check=True, timeout=15)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.project), *args], env=self.env,
                              capture_output=True, check=True, timeout=15).stdout

    def capture(self, name="snapshot", **kwargs):
        return backup.capture(self.home, self.project, self.base / name, **kwargs)

    def test_stopped_capture_restore_and_real_queries_preserve_wal_git_and_identity(self):
        original_identity = (self.project / ".icm/project.json").read_bytes()
        original_wal = Path(str(self.state / "kanban.db")+"-wal").read_bytes()
        original_head = self.git("rev-parse", "HEAD")
        result = self.capture()
        snapshot = self.base / "snapshot"
        restored = self.base / "restored"
        reply = backup.restore(snapshot, restored, result["manifest_sha256"])
        self.assertEqual(reply["status"], "verified_export")
        self.assertFalse(reply["activated"])
        self.assertEqual((restored / "payload/project/.icm/project.json").read_bytes(), original_identity)
        self.assertEqual(Path(str(self.state / "kanban.db")+"-wal").read_bytes(), original_wal)
        self.assertEqual(self.git("rev-parse", "HEAD"), original_head)
        restored_head = subprocess.check_output(["git", "-C", str(restored / "payload/project"), "rev-parse", "HEAD"], env=self.env)
        self.assertEqual(restored_head, original_head)
        with sqlite3.connect((restored / "payload/state/kanban.db").as_uri()+"?mode=ro", uri=True) as connection:
            self.assertEqual(connection.execute("SELECT title FROM tasks").fetchall(), [("Committed WAL card",)])
        with sqlite3.connect((restored / "payload/state/knowledge.db").as_uri()+"?mode=ro", uri=True) as connection:
            self.assertIn("Orchard", connection.execute("SELECT content FROM chunks WHERE chunks MATCH 'Orchard'").fetchone()[0])
        self.assertTrue((restored / "payload/project/empty").is_dir())
        self.assertFalse(list((restored / "payload/state").glob("*-wal")))
        manifest = json.loads((snapshot / "manifest.json").read_text())
        self.assertEqual(manifest["original_identity"]["canonical_root"], str(self.project))
        self.assertTrue(all(value["quick_check"] == "ok" for value in manifest["database_checks"].values()))

    def test_live_home_and_pending_operation_refuse_before_destination_creation(self):
        guard = backup.home_entry._load_guard(self.home, self.config["lifecycle_guard_sha256"])
        with guard.lease(self.home, expected_sha256=self.config["lifecycle_guard_sha256"]):
            with self.assertRaisesRegex(ValueError, "busy"):
                self.capture()
        self.assertFalse((self.base / "snapshot").exists())
        pending = self.home / "state/updates/pending-activation.json"
        pending.parent.mkdir()
        pending.write_text("retained partial operation")
        with self.assertRaisesRegex(ValueError, "Pending"):
            self.capture()
        self.assertFalse((self.base / "snapshot").exists())
        self.assertEqual(pending.read_text(), "retained partial operation")

    def test_identity_helper_and_foreign_state_refuse_without_capture(self):
        pointer = self.project / ".icm/project.json"
        data = dict(self.identity, state_root=str(self.base / "foreign"))
        pointer.write_text(json.dumps(data))
        with self.assertRaisesRegex(backup.BackupError, "identity validation refused"):
            self.capture()
        self.assertFalse((self.base / "snapshot").exists())
        pointer.write_text(json.dumps(self.identity))
        helper = self.home / "runtime/adapters/pi/project-workflow/project_identity.py"
        helper.write_bytes(helper.read_bytes()+b"\n# drift\n")
        with self.assertRaisesRegex(backup.BackupError, "helper drift"):
            self.capture()

    def test_symlink_special_file_collision_and_quota_do_not_overwrite(self):
        source = self.project / "link"
        source.symlink_to(self.base)
        with self.assertRaisesRegex(backup.BackupError, "Unsupported|Symlink"):
            self.capture()
        source.unlink()
        os.mkfifo(source)
        with self.assertRaisesRegex(backup.BackupError, "Unsupported"):
            self.capture()
        source.unlink()
        with self.assertRaisesRegex(backup.BackupError, "quota"):
            self.capture(max_bytes=1)
        target = self.base / "snapshot"
        target.mkdir()
        (target / "keep").write_bytes(b"original")
        with self.assertRaisesRegex(backup.BackupError, "already exists"):
            self.capture()
        self.assertEqual((target / "keep").read_bytes(), b"original")

    def test_source_drift_and_interruption_retain_unaccepted_partial(self):
        original = backup.sqlite_copy
        def changed(source, target, deadline):
            original(source, target, deadline)
            (self.project / "README.md").write_text("changed by synthetic independent writer")
        with mock.patch.object(backup, "sqlite_copy", side_effect=changed):
            with self.assertRaisesRegex(backup.BackupError, "Source drift"):
                self.capture("drift")
        self.assertFalse((self.base / "drift/manifest.json").exists())
        self.assertEqual(json.loads((self.base / "drift/failure.json").read_text())["status"], "failed_partial")
        with mock.patch.object(backup, "sqlite_copy", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.capture("interrupted")
        self.assertTrue((self.base / "interrupted/failure.json").is_file())
        self.assertFalse((self.base / "interrupted/manifest.json").exists())

    def test_foreign_board_and_corrupt_db_retain_failure_without_manifest(self):
        self.writer.execute("UPDATE tasks SET tenant='foreign'")
        self.writer.commit()
        with self.assertRaisesRegex(backup.BackupError, "foreign board"):
            self.capture("foreign")
        self.assertFalse((self.base / "foreign/manifest.json").exists())
        self.writer.execute("UPDATE tasks SET tenant=?", (self.identity["board_id"],))
        self.writer.commit()
        knowledge_original = (self.state / "knowledge.db").read_bytes()
        with sqlite3.connect(self.state / "knowledge.db") as knowledge:
            knowledge.execute("UPDATE metadata SET value='foreign' WHERE key='project_id'")
        with self.assertRaisesRegex(backup.BackupError, "Knowledge index binding"):
            self.capture("foreign-knowledge")
        (self.state / "knowledge.db").write_bytes(knowledge_original)
        (self.state / "knowledge.db").write_bytes(b"corrupt synthetic SQLite")
        with self.assertRaises(sqlite3.Error):
            self.capture("corrupt")
        self.assertTrue((self.base / "corrupt/failure.json").is_file())

    def test_manifest_pin_membership_and_restore_collision_refuse(self):
        result = self.capture()
        snapshot = self.base / "snapshot"
        target = self.base / "export"
        with self.assertRaisesRegex(backup.BackupError, "SHA256"):
            backup.restore(snapshot, target, "0"*64)
        extra = snapshot / "payload/project/unlisted"
        extra.write_text("unexpected")
        with self.assertRaisesRegex(backup.BackupError, "membership"):
            backup.restore(snapshot, target, result["manifest_sha256"])
        self.assertFalse(target.exists())
        extra.unlink()
        saved = snapshot / "payload/project/README.md"
        original = saved.read_bytes()
        saved.unlink()
        with self.assertRaisesRegex(backup.BackupError, "membership"):
            backup.restore(snapshot, target, result["manifest_sha256"])
        saved.write_bytes(original)
        with self.assertRaisesRegex(backup.BackupError, "overlaps"):
            backup.restore(snapshot, self.project / "must-not-appear", result["manifest_sha256"])
        self.assertFalse((self.project / "must-not-appear").exists())
        target.mkdir()
        with self.assertRaisesRegex(backup.BackupError, "already exists"):
            backup.restore(snapshot, target, result["manifest_sha256"])

    def test_restore_interruption_and_validation_failure_preserve_partial_and_source(self):
        result = self.capture()
        snapshot = self.base / "snapshot"
        original = (snapshot / "manifest.json").read_bytes()
        actual = backup.validate_payload
        def validation(payload, manifest, deadline):
            if payload.parent.name == "interrupted-export":
                raise KeyboardInterrupt
            return actual(payload, manifest, deadline)
        with mock.patch.object(backup, "validate_payload", side_effect=validation):
            with self.assertRaises(KeyboardInterrupt):
                backup.restore(snapshot, self.base / "interrupted-export", result["manifest_sha256"])
        self.assertTrue((self.base / "interrupted-export/failure.json").is_file())
        self.assertFalse((self.base / "interrupted-export/export.json").exists())
        self.assertEqual((snapshot / "manifest.json").read_bytes(), original)

    def test_copy_corruption_cannot_be_accepted_as_the_new_manifest(self):
        original = backup.inventory
        def corrupted(roots, deadline, max_bytes, max_files):
            if any("snapshot" in path.parts for path in roots.values()):
                (roots["project"] / "README.md").write_text("synthetic output corruption")
            return original(roots, deadline, max_bytes, max_files)
        with mock.patch.object(backup, "inventory", side_effect=corrupted):
            with self.assertRaisesRegex(backup.BackupError, "regular file differs"):
                self.capture()
        self.assertFalse((self.base / "snapshot/manifest.json").exists())
        self.assertTrue((self.base / "snapshot/failure.json").exists())

    def test_direct_script_cli_from_unrelated_cwd_preserves_exact_manifest_pin(self):
        command = [sys.executable, "-I", "-B", str(ROOT / "harness/project_backup.py")]
        snapshot = self.base / "cli-snapshot"
        captured = subprocess.run(command+["capture", "--home", str(self.home), "--project", str(self.project),
                                          "--destination", str(snapshot)], cwd=self.base, capture_output=True,
                                  text=True, check=True, timeout=30)
        pin = json.loads(captured.stdout)["manifest_sha256"]
        restored = subprocess.run(command+["restore", "--snapshot", str(snapshot), "--manifest-sha256", pin,
                                          "--destination", str(self.base / "cli-export")], cwd=self.base,
                                  capture_output=True, text=True, check=True, timeout=30)
        reply = json.loads(restored.stdout)
        self.assertEqual(reply["status"], "verified_export")
        self.assertEqual(reply["source_manifest_sha256"], pin)
        self.assertFalse(reply["activated"])


class BackupValidationTests(unittest.TestCase):
    def test_unsafe_member_and_nonfinite_budgets_refuse(self):
        for name in ("../outside", "/absolute", "project/../../outside", "unknown/file", "project/a\\b"):
            with self.subTest(name=name), self.assertRaises(backup.BackupError):
                backup.path_for({"project": Path("/owned")}, name)
        for seconds in (0, -1, float("inf"), float("nan")):
            with self.subTest(seconds=seconds), self.assertRaises(backup.BackupError):
                backup.budget(seconds)


if __name__ == "__main__":
    unittest.main()
