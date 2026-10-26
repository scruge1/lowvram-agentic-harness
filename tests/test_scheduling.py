"""Scheduling inspection controls. Synthetic stores; no ticker or agent dispatch."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from harness import home, scheduling


@unittest.skipUnless(shutil.which("git"), "Native source identity requires Git")
class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="schedule-read-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "Home with spaces"
        self.config = home.scaffold(self.root, profile="agent", base_url="http://127.0.0.1:9/v1",
                                    model="synthetic-no-model", offline=True)
        self.native = self.root / "packages/hermes-source"
        self.native.mkdir(parents=True)
        (self.native / "LICENSE").write_text("Synthetic source identity fixture only\n", encoding="utf-8")
        self.source = self.native / "cron.py"
        self.source.write_text("# Synthetic source; no scheduler code is imported.\n", encoding="utf-8")
        self.git("init", "--quiet")
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "--quiet", "-m", "Synthetic native identity")
        commit = self.git("rev-parse", "HEAD").strip()
        self.source_pin = patch.dict(home.GIT_SOURCES, hermes=("synthetic source fixture", commit))
        self.source_pin.start()
        self.addCleanup(self.source_pin.stop)
        metadata = self.root / "packages/synthetic-hermes-metadata.json"
        metadata.write_text('{"fixture":true}', encoding="utf-8")
        self.config["installed"]["hermes"] = {"artifacts": [{"path": str(metadata), "sha256": home.digest(metadata)}]}
        home.save_status(self.root, self.config)
        self.store = self.root / "state/hermes/cron"

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.native, text=True, stderr=subprocess.PIPE)

    def jobs(self, rows):
        self.store.mkdir(parents=True, exist_ok=True)
        path = self.store / "jobs.json"
        path.write_text(json.dumps({"jobs": rows}), encoding="utf-8")
        return path

    def history(self):
        self.store.mkdir(parents=True, exist_ok=True)
        path = self.store / "executions.db"
        db = sqlite3.connect(path)
        self.addCleanup(db.close)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE executions(id TEXT PRIMARY KEY,job_id TEXT,source TEXT,status TEXT,claimed_at TEXT,"
                   "started_at TEXT,finished_at TEXT,error TEXT,delivery_outcome TEXT,scheduled_instant TEXT)")
        for index, state in enumerate(("completed", "failed", "unknown")):
            db.execute("INSERT INTO executions VALUES(?,?,?,?,?,?,?,?,?,?)", (
                "attempt-" + str(index), "job-a", "fixture", state, "2026-01-0" + str(index + 1),
                None, None, "retained failure" if state == "failed" else None, "local", None))
        db.commit()
        return db, path

    def test_missing_stores_stay_missing_and_do_not_create_scheduler_state(self):
        for action in ("list", "runs", "result"):
            report = scheduling.inspect(self.root, action, job_id="job-a")
            self.assertEqual(report["observation"]["state"], "missing")
            self.assertFalse(report["scheduler_started"])
            self.assertEqual(report["jobs_dispatched"], 0)
        self.assertFalse(self.store.exists())

    def test_paused_failed_and_unknown_job_fields_are_preserved_without_progress_inference(self):
        path = self.jobs([{"id": "paused", "enabled": False, "state": "paused", "last_status": "failed"},
                          {"id": "unknown", "enabled": True, "state": "scheduled", "last_status": "unknown"}])
        before = path.read_bytes()
        report = scheduling.inspect(self.root, "list", limit=1)
        self.assertTrue(report["observation"]["truncated"])
        self.assertEqual(report["observation"]["total"], 2)
        self.assertEqual(report["observation"]["rows"][0]["last_status"], "failed")
        self.assertEqual(report["ticker_liveness"], "not_inspected")
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.store / "executions.db").exists())

    def test_legacy_or_malformed_jobs_require_explicit_repair_and_remain_unchanged(self):
        path = self.jobs([])
        for raw in (b'[]', b'{"jobs":{}}', b'{bad', b'{"jobs":[{"id":"x","enabled":"yes"}]}'):
            path.write_bytes(raw)
            with self.assertRaises((ValueError, KeyError)):
                scheduling.inspect(self.root, "list")
            self.assertEqual(path.read_bytes(), raw)

    def test_durable_attempts_do_not_turn_unknown_or_failed_into_completed(self):
        db, path = self.history()
        unrelated = self.root / "projects/unrelated-note.txt"
        unrelated.write_text("preserve this user note", encoding="utf-8")
        before_note, before_main = unrelated.read_bytes(), path.read_bytes()
        before_rows = db.execute("SELECT * FROM executions ORDER BY id").fetchall()
        report = scheduling.inspect(self.root, "runs", job_id="job-a", limit=2)
        observed = report["observation"]
        self.assertEqual([row["status"] for row in observed["rows"]], ["unknown", "failed"])
        self.assertTrue(observed["truncated"])
        self.assertEqual(observed["rows"][1]["error"], "retained failure")
        self.assertEqual(db.execute("SELECT * FROM executions ORDER BY id").fetchall(), before_rows)
        self.assertEqual(path.read_bytes(), before_main)
        self.assertEqual(unrelated.read_bytes(), before_note)
        self.assertEqual(scheduling.inspect(self.root, "runs", job_id="absent")["observation"]["rows"], [])

    def test_unknown_database_schema_is_not_initialized_or_migrated(self):
        self.store.mkdir(parents=True)
        path = self.store / "executions.db"
        with contextlib.closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE user_data(value TEXT)")
            db.execute("INSERT INTO user_data VALUES('preserve')")
            db.commit()
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "schema differs"):
            scheduling.inspect(self.root, "runs")
        self.assertEqual(path.read_bytes(), before)

    def test_saved_output_is_bounded_and_is_not_an_execution_or_checked_file_receipt(self):
        directory = self.store / "output/job-a"
        directory.mkdir(parents=True)
        path = directory / "2026-01-01_01-02-03.md"
        raw = ("Synthetic saved output.\n" + "Unicode: \u03b1\u03b2\u03b3\n" * 2000).encode()
        path.write_bytes(raw)
        observed = scheduling.inspect(self.root, "result", job_id="job-a")["observation"]
        self.assertEqual(observed["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertTrue(observed["truncated"])
        self.assertEqual(observed["content_scope"], "prefix")
        self.assertEqual(observed["execution_link"], "not_established")
        self.assertEqual(observed["checked_file_acceptance"], "not_established")
        self.assertEqual(path.read_bytes(), raw)

    def test_traversal_and_redirected_store_are_refused(self):
        with self.assertRaises(ValueError):
            scheduling.inspect(self.root, "runs", job_id="../../other-home")
        directory = self.store / "output/job-a"
        directory.mkdir(parents=True)
        with self.assertRaises(ValueError):
            scheduling.inspect(self.root, "result", job_id="job-a", filename="../../../auth.json")
        foreign = Path(self.temp.name) / "foreign.json"
        foreign.write_text('{"jobs":[]}', encoding="utf-8")
        try:
            (self.store / "jobs.json").symlink_to(foreign)
        except OSError:
            return  # Other refusal assertions still ran on Windows without symlink privilege.
        with self.assertRaisesRegex(ValueError, "redirected"):
            scheduling.inspect(self.root, "list")

    def test_changed_package_source_and_home_binding_refuse_before_store_access(self):
        self.source.write_text("# Changed tracked source\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            scheduling.inspect(self.root, "list")
        self.assertFalse(self.store.exists())
        self.source.write_text("# Synthetic source; no scheduler code is imported.\n", encoding="utf-8")
        config = json.loads((self.root / "home.json").read_text())
        config["home"] = str(Path(self.temp.name) / "other-home")
        (self.root / "home.json").write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "identity differs"):
            scheduling.inspect(self.root, "list")

    def test_loaded_runtime_drift_and_drift_during_delivery_are_refused(self):
        file = self.root / "runtime/harness/scheduling.py"
        original = file.read_bytes()
        file.write_bytes(original + b"\n# drift\n")
        with self.assertRaisesRegex(ValueError, "runtime source changed"):
            scheduling.inspect(self.root, "list")
        file.write_bytes(original)
        actual = scheduling.jobs
        def drift(*args):
            value = actual(*args)
            self.source.write_text("# Changed while native result was read\n", encoding="utf-8")
            return value
        with patch.object(scheduling, "jobs", side_effect=drift):
            with self.assertRaises(ValueError):
                scheduling.inspect(self.root, "list")

    def test_installed_cli_missing_package_and_forbidden_commands_do_not_create_jobs(self):
        other = self.root.parent / "Core home"
        home.scaffold(other, profile="core", base_url="http://127.0.0.1:9/v1", model="no-model", offline=True)
        cli = [sys.executable, "-B", str(other / "agent-home.py"), "schedule"]
        run = subprocess.run([*cli, "list"], capture_output=True, text=True, timeout=20)
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertIn("Hermes is not installed", run.stderr)
        for command in ("create", "resume", "tick", "run"):
            run = subprocess.run([*cli, command], capture_output=True, text=True, timeout=20)
            self.assertEqual(run.returncode, 2)
        run = subprocess.run([*cli, "--home", str(self.root), "list"], capture_output=True, text=True, timeout=20)
        self.assertNotEqual(run.returncode, 0)
        self.assertFalse((other / "state/hermes/cron").exists())

    def test_home_dispatch_routes_to_same_bounded_reader(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(home.main(["--home", str(self.root), "schedule", "list"]), 0)
        self.assertEqual(json.loads(output.getvalue())["observation"]["state"], "missing")
        self.assertFalse(self.store.exists())


if __name__ == "__main__":
    unittest.main()
