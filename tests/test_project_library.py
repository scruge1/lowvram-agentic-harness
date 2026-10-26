"""Actual fictional files/SQLite and scoped CLI; no model, service or UI proof."""
import hashlib
import importlib
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "adapters/pi/project-workflow"
sys.path.insert(0, str(WORKFLOW))
identity = importlib.import_module("project_identity")
knowledge = importlib.import_module("project_knowledge")


class ProjectLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=os.environ.get("PROJECT_LIBRARY_TEST_ROOT"))
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "fictional-project"
        self.root.mkdir()
        self.environment = mock.patch.dict(os.environ, {"PI_PROJECT_STATE_BASE": str(self.base / "state")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.pointer, _ = identity.initialize_identity(self.root, native_authority="Owned fictional Library source test")
        (self.root / "docs").mkdir()
        self.note = self.root / "docs/record.md"
        self.note.write_bytes("# Fictional record\n\nCobalt orchard café.\nKeep empty values.\n".encode("utf-8"))
        (self.root / "docs/source.md").write_bytes(b"# Original source\n\nFictional source reference.\n")
        self.build()

    def build(self):
        return knowledge.build(self.root)

    @property
    def database(self):
        return Path(self.pointer["state_root"]) / "knowledge.db"

    def query(self, terms="orchard"):
        return knowledge.current(self.root, terms=terms)

    def test_import_build_query_and_bounded_original_source_agree(self):
        result = self.query()
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["fresh"])
        self.assertEqual(result["results"][0]["path"], "docs/record.md")
        pin = hashlib.sha256(self.note.read_bytes()).hexdigest()
        read = knowledge.current(self.root, source="docs/record.md", start_line=3, line_limit=1, expected_sha256=pin)
        self.assertTrue(read["index_fresh"])
        self.assertEqual(read["source"]["text"], "Cobalt orchard café.\n")
        self.assertEqual(read["source"]["sha256"], pin)
        self.assertEqual(read["source"]["line_end"], 3)
        self.assertEqual(read["source"]["text_sha256"], hashlib.sha256(read["source"]["text"].encode()).hexdigest())

    def test_correction_holds_search_but_current_read_works_until_explicit_build(self):
        old = hashlib.sha256(self.note.read_bytes()).hexdigest()
        self.note.write_text("# Corrected fictional record\nMarigold orchard.\n", encoding="utf-8")
        legacy = knowledge.query(self.root, "Cobalt", 10)
        self.assertTrue(legacy["results"])
        self.assertEqual(legacy["freshness"], "indexed_snapshot_not_current_validated")
        held = self.query()
        self.assertFalse(held["ok"])
        self.assertEqual(held["results"], [])
        self.assertIn("docs/record.md", held["changed"])
        read = knowledge.current(self.root, source="docs/record.md")
        self.assertFalse(read["index_fresh"])
        self.assertIn("Marigold", read["source"]["text"])
        with self.assertRaises(knowledge.KnowledgeError):
            knowledge.current(self.root, source="docs/record.md", expected_sha256=old)
        self.build()
        self.assertTrue(self.query("Marigold")["results"])
        self.assertEqual(self.query("Cobalt")["results"], [])

    def test_addition_and_deletion_require_existing_explicit_rebuild(self):
        self.note.unlink()
        (self.root / "docs/new.md").write_text("New saffron record.\n", encoding="utf-8")
        status = knowledge.current(self.root)
        self.assertEqual(status["removed"], ["docs/record.md"])
        self.assertEqual(status["added"], ["docs/new.md"])
        self.assertFalse(self.query()["ok"])
        with self.assertRaises(knowledge.KnowledgeError):
            knowledge.current(self.root, source="docs/record.md")
        self.build()
        self.assertEqual(self.query()["results"], [])
        self.assertTrue(self.query("saffron")["results"])

    def test_actual_index_chunks_and_orphan_rows_are_checked(self):
        for sql in ("UPDATE chunks SET content='fabricated unseen answer' WHERE path='docs/record.md'",
                    "INSERT INTO chunks VALUES ('docs/orphan.md','unbound',1,1,'fabricated orchard')"):
            with self.subTest(sql=sql):
                try:
                    with closing(sqlite3.connect(self.database)) as connection:
                        connection.execute(sql)
                        connection.commit()
                    held = self.query()
                    self.assertFalse(held["ok"])
                    self.assertEqual(held["results"], [])
                    self.assertIn("index_chunk_binding", held["reasons"])
                finally:
                    self.build()

    def test_policy_manifest_and_foreign_index_bindings_refuse(self):
        policy = self.root / knowledge.CONFIG_PATH
        manifest = self.root / self.pointer["knowledge_manifest"]
        policy_raw, manifest_raw = policy.read_bytes(), manifest.read_bytes()
        for arm in ("policy", "manifest", "foreign_index"):
            with self.subTest(arm=arm):
                try:
                    if arm == "policy":
                        value = json.loads(policy_raw)
                        value["include"] = ["docs/record.md"]
                        policy.write_text(json.dumps(value), encoding="utf-8")
                    elif arm == "manifest":
                        value = json.loads(manifest_raw)
                        value["canonical_root"] = str(self.base / "foreign")
                        manifest.write_text(json.dumps(value), encoding="utf-8")
                    else:
                        with closing(sqlite3.connect(self.database)) as connection:
                            connection.execute("UPDATE metadata SET value='foreign-project' WHERE key='project_id'")
                            connection.commit()
                    self.assertFalse(self.query()["ok"])
                finally:
                    policy.write_bytes(policy_raw)
                    manifest.write_bytes(manifest_raw)
                    self.build()

    def test_deadline_defers_without_delivering_partial_content(self):
        result = knowledge.current(self.root, source="docs/record.md", seconds=1e-12)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "deferred")
        self.assertNotIn("source", result)

    def test_actual_owned_exclusive_index_lock_defers_without_payload(self):
        with closing(sqlite3.connect(self.database)) as held:
            held.execute("BEGIN EXCLUSIVE")
            result = self.query()
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "deferred")
            self.assertEqual(result["reason"], "Current index is busy")
            self.assertNotIn("results", result)
            self.assertNotIn("source", result)
            held.rollback()
        self.assertTrue(self.query()["ok"])

    def test_changed_source_during_final_membership_check_is_not_delivered(self):
        original = knowledge.discover_sources
        calls = 0
        def drift(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.note.write_text("Late changed source.\n", encoding="utf-8")
            return original(*args, **kwargs)
        with mock.patch.object(knowledge, "discover_sources", side_effect=drift):
            result = self.query()
        self.assertEqual(result["status"], "deferred")
        self.assertNotIn("results", result)

    def test_new_source_during_validation_is_not_silently_omitted(self):
        original = knowledge.discover_sources
        calls = 0
        def drift(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                (self.root / "docs/late.md").write_text("New later source.", encoding="utf-8")
            return original(*args, **kwargs)
        with mock.patch.object(knowledge, "discover_sources", side_effect=drift):
            result = self.query()
        self.assertEqual(result["status"], "deferred")

    def test_window_and_source_path_bounds(self):
        self.note.write_text("x" * 5000 + "\nsecond line\n", encoding="utf-8")
        self.build()
        read = knowledge.current(self.root, source="docs/record.md")
        self.assertEqual(len(read["source"]["text"]), 4000)
        self.assertTrue(read["source"]["partial"])
        for source in ("../outside.md", str(self.note), "docs/../docs/record.md", "docs\\record.md", "docs//record.md"):
            with self.subTest(source=source), self.assertRaises(knowledge.KnowledgeError):
                knowledge.current(self.root, source=source)
        for request in ({"start_line": 3}, {"line_limit": 51}, {"line_limit": True}):
            with self.subTest(request=request), self.assertRaises(knowledge.KnowledgeError):
                knowledge.current(self.root, source="docs/record.md", **request)

    def test_excluded_credentials_are_not_read_and_unsupported_formats_are_explicit(self):
        secret = self.root / "docs/api-token.md"
        secret.write_bytes(b"excluded fixture value")
        pdf = self.root / "docs/example.pdf"
        pdf.write_bytes(b"%PDF fictional unsupported data")
        original = knowledge._current_bytes
        def guarded(path, *args):
            self.assertNotEqual(path, secret)
            self.assertNotEqual(path, pdf)
            return original(path, *args)
        with mock.patch.object(knowledge, "_current_bytes", side_effect=guarded):
            result = self.query()
        self.assertFalse(result["ok"])
        self.assertIn({"path": "docs/example.pdf", "reason": "unsupported_extension"}, result["unsupported"])
        self.assertNotIn("excluded fixture value", json.dumps(result))

    def test_existing_current_file_and_index_are_not_modified(self):
        paths = [self.note, self.database, self.root / knowledge.CONFIG_PATH, self.root / self.pointer["knowledge_manifest"]]
        before = {p: p.read_bytes() for p in paths}
        self.assertTrue(self.query()["ok"])
        self.assertTrue(knowledge.current(self.root, source="docs/record.md")["ok"])
        self.assertEqual({p: p.read_bytes() for p in paths}, before)

    def test_current_source_preserves_crlf_bytes_and_hash(self):
        raw = "# Exact source\r\nOrchard café.\r\n".encode("utf-8")
        self.note.write_bytes(raw)
        self.build()
        result = knowledge.current(self.root, source="docs/record.md", start_line=2, line_limit=1)
        self.assertEqual(result["source"]["text"], "Orchard café.\r\n")
        self.assertEqual(result["source"]["sha256"], hashlib.sha256(raw).hexdigest())

    def test_existing_two_mib_read_ceiling_defers_even_with_larger_policy(self):
        policy = self.root / knowledge.CONFIG_PATH
        value = json.loads(policy.read_text(encoding="utf-8"))
        value["max_file_bytes"] *= 2
        policy.write_text(json.dumps(value), encoding="utf-8")
        self.note.write_bytes(b"x" * (knowledge.DEFAULT_CONFIG["max_file_bytes"] + 1))
        result = knowledge.current(self.root, source="docs/record.md")
        self.assertEqual(result["status"], "deferred")
        self.assertNotIn("source", result)

    def test_corrupt_index_is_unavailable_and_does_not_deliver_results(self):
        self.database.write_bytes(b"Controlled invalid index fixture")
        result = self.query()
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("results", result)

    def test_default_discovery_prunes_excluded_package_directories(self):
        folder = self.root / "docs/node_modules/private"
        folder.mkdir(parents=True)
        (folder / "hidden.md").write_bytes(b"Excluded fictional package text")
        original = knowledge.os.walk
        visited = []
        def walk(*args, **kwargs):
            for row in original(*args, **kwargs):
                visited.append(Path(row[0]))
                yield row
        with mock.patch.object(knowledge.os, "walk", side_effect=walk):
            result = self.query()
        self.assertTrue(result["ok"])
        self.assertFalse(any("node_modules" in path.parts for path in visited))

    def test_complex_policy_defers_instead_of_unbounded_recursive_scan(self):
        policy = self.root / knowledge.CONFIG_PATH
        value = json.loads(policy.read_text(encoding="utf-8"))
        value["include"] = ["docs/**/record.md"]
        policy.write_text(json.dumps(value), encoding="utf-8")
        self.build()
        result = self.query()
        self.assertEqual(result["status"], "deferred")
        self.assertNotIn("results", result)

    def test_hardlinked_and_foreign_symlinked_sources_refuse(self):
        linked = self.root / "docs/linked.md"
        os.link(self.note, linked)
        with self.assertRaises(knowledge.KnowledgeError):
            self.query()
        linked.unlink()
        outside = self.base / "outside.md"
        outside.write_bytes(b"Outside fictional source")
        try:
            linked.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("Creating a native symlink requires platform permission")
        result = self.query()
        self.assertFalse(result["ok"])
        self.assertIn({"path": "docs/linked.md", "reason": "outside_project_root"}, result["unsupported"])
        with self.assertRaises(knowledge.KnowledgeError):
            knowledge.current(self.root, source="docs/linked.md")

    def test_normal_scoped_cli_and_legacy_snapshot_label(self):
        def cli(*args):
            return subprocess.run([sys.executable, "-I", "-B", str(WORKFLOW / "project_knowledge.py"), *args,
                                   "--root", str(self.root)], capture_output=True, text=True, timeout=15)
        for args in (("status",), ("query", "--current", "--terms", "orchard"), ("read", "--source", "docs/record.md")):
            ran = cli(*args)
            self.assertEqual(ran.returncode, 0, ran.stderr)
            self.assertTrue(json.loads(ran.stdout)["ok"])
        self.note.write_text("Changed source.\n", encoding="utf-8")
        ran = cli("query", "--current", "--terms", "orchard")
        self.assertEqual(ran.returncode, 2)
        self.assertEqual(json.loads(ran.stdout)["results"], [])
        legacy = cli("query", "--terms", "orchard")
        self.assertEqual(json.loads(legacy.stdout)["freshness"], "indexed_snapshot_not_current_validated")


if __name__ == "__main__":
    unittest.main()
