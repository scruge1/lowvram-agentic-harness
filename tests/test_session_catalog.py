"""Positive/negative controls for header-only native session catalogue.

Fixtures are disposable; no real sessions, task board or model touched.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from harness import session_catalog as cat
from harness.managed_launch import session_directory


class NativeCatalogueFixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-session-index-")
        base = Path(self.temp.name)
        self.home = (base / "owner").resolve()
        self.home.mkdir()
        self.project = (base / "owned-project").resolve()
        self.project.mkdir()
        (self.project / ".icm").mkdir()
        self.identity = {
            "project_id": "p_fixture_catalog_012345abcdef",
            "board_id": "project:p_fixture_catalog_012345abcdef",
            "canonical_root": str(self.project),
            "state_root": str(self.home / "state" / "projects" / "p_fixture_catalog_012345abcdef"),
        }
        self.marker = self.project / ".icm" / "project.json"
        self.marker.write_text(json.dumps(self.identity),encoding="utf-8")
        self.bucket = session_directory(self.home, self.project)
        self.bucket.mkdir(parents=True)
        self.uid = self.marker.stat().st_uid

    def tearDown(self):
        self.temp.cleanup()

    @contextmanager
    def linux_host(self):
        with mock.patch.object(cat.sys, "platform", "linux"), \
             mock.patch.object(cat.os, "getuid", create=True, return_value=self.uid):
            yield

    def saved(self, name, sid, *, cwd=None, extra="do not reveal private tokens", created="2026-11-08T08:00:00Z"):
        file = self.bucket / name
        file.write_text(json.dumps({"type":"session","id":sid,"cwd":str(cwd or self.project),
             "timestamp":created})+"\n"+json.dumps({"type":"message","private":extra})+"\n",
             encoding="utf-8")
        return file

    def test_empty_is_read_only_and_does_not_create_bucket(self):
        self.bucket.rmdir()
        with self.linux_host():
            view=cat.list_project_sessions(self.home,self.project)
        self.assertEqual(view["total"],0)
        self.assertEqual(view["authority"],"retrieval_only")
        self.assertFalse(self.bucket.exists())

    def test_metadata_only_no_message_body_no_paths(self):
        self.saved("session-1.jsonl","session-one",extra="VERY_SECRET_NOT_IN_RESPONSE")
        with self.linux_host():
            result=cat.list_project_sessions(self.home,self.project)
        self.assertEqual(result["total"],1)
        self.assertEqual(result["sessions"][0]["session_id"],"session-one")
        self.assertNotIn("VERY_SECRET",json.dumps(result))
        self.assertNotIn(str(self.project),json.dumps(result))
        self.assertNotIn(str(self.bucket),json.dumps(result))
        self.assertEqual(result["sessions"][0]["source"],"native_pi_session_header_only")

    def test_cursor_pagination_fresh_source(self):
        self.saved("session-a.jsonl","sid-one")
        self.saved("session-b.jsonl","sid-two")
        with self.linux_host():
            first=cat.list_project_sessions(self.home,self.project,limit=1)
            second=cat.list_project_sessions(self.home,self.project,offset=1,
                limit=1,expected_snapshot_sha256=first["snapshot_sha256"])
        self.assertEqual(first["total"],2)
        self.assertEqual(len(second["sessions"]),1)
        self.assertNotEqual(first["sessions"][0]["session_id"],second["sessions"][0]["session_id"])
        self.assertIsNone(second["next_offset"])
        self.assertEqual(first["snapshot_sha256"],second["snapshot_sha256"])

    def test_new_message_refuses_stale_cursor(self):
        self.saved("session-a.jsonl","sid-one")
        f=self.saved("session-b.jsonl","sid-two")
        with self.linux_host():
            prior=cat.list_project_sessions(self.home,self.project,limit=1)
            with f.open("a",encoding="utf-8") as output:
                output.write('{"type":"message","change":"new"}\n')
            with self.assertRaisesRegex(cat.SessionCatalogueError,"changed"):
                cat.list_project_sessions(self.home,self.project,offset=1,
                 expected_snapshot_sha256=prior["snapshot_sha256"])

    def test_no_unpinned_pagination(self):
        self.saved("session-a.jsonl","sid-one")
        with self.linux_host(), self.assertRaisesRegex(cat.SessionCatalogueError,"fingerprint"):
            cat.list_project_sessions(self.home,self.project,offset=1)

    def test_invalid_ranges_and_types_refused(self):
        with self.linux_host():
            for kwargs in ({"offset":True},{"offset":-1},{"offset":999999},
                           {"limit":0},{"limit":26},{"limit":False},
                           {"expected_snapshot_sha256":"bad"}):
                with self.subTest(kwargs=kwargs), self.assertRaises(cat.SessionCatalogueError):
                    cat.list_project_sessions(self.home,self.project,**kwargs)

    def test_foreign_header_refused(self):
        self.saved("session-a.jsonl","sid-one",cwd=self.home)
        with self.linux_host(), self.assertRaisesRegex(cat.SessionCatalogueError,"another project"):
            cat.list_project_sessions(self.home,self.project)

    def test_duplicate_session_id_refused(self):
        self.saved("session-a.jsonl","sid-one")
        self.saved("session-b.jsonl","sid-one")
        with self.linux_host(), self.assertRaisesRegex(cat.SessionCatalogueError,"Duplicate"):
            cat.list_project_sessions(self.home,self.project)

    def test_invalid_or_oversized_header_refused(self):
        bad=self.bucket/"session-a.jsonl"
        bad.write_text('{"type":"session","id":',encoding="utf-8")
        with self.linux_host(), self.assertRaises(cat.SessionCatalogueError):
            cat.list_project_sessions(self.home,self.project)
        bad.write_bytes(b'X'*131073+b"\n")
        with self.linux_host(), self.assertRaisesRegex(cat.SessionCatalogueError,"oversized"):
            cat.list_project_sessions(self.home,self.project)

    def test_broken_icm_identity_refused(self):
        self.identity["board_id"]="project:wrong"
        self.marker.write_text(json.dumps(self.identity),encoding="utf-8")
        with self.linux_host(), self.assertRaisesRegex(cat.SessionCatalogueError,"identity"):
            cat.list_project_sessions(self.home,self.project)

    def test_cross_home_state_root_refused(self):
        self.identity["state_root"]=str(self.project/"other-home")
        self.marker.write_text(json.dumps(self.identity),encoding="utf-8")
        with self.linux_host(), self.assertRaisesRegex(cat.SessionCatalogueError,"another home"):
            cat.list_project_sessions(self.home,self.project)

    def test_symbolic_link_session_refused(self):
        target=self.saved("session-a.jsonl","sid-one")
        alias=self.bucket/"session-b.jsonl"
        try:
            alias.symlink_to(target)
        except (OSError,NotImplementedError):
            self.skipTest("Symbolic-link creation unavailable")
        with self.linux_host(), self.assertRaises(cat.SessionCatalogueError):
            cat.list_project_sessions(self.home,self.project)

    def test_unsupported_platform_refuses_read(self):
        self.saved("session-a.jsonl","sid-one")
        with mock.patch.object(cat.sys, "platform", "win32"), \
             self.assertRaisesRegex(cat.SessionCatalogueError,"Linux"):
            cat.list_project_sessions(self.home,self.project)

    def test_cli_is_metadata_only_and_no_create_or_writes(self):
        from contextlib import redirect_stdout
        from io import StringIO
        self.saved("session-a.jsonl", "sid-one", extra="SECRET_IN_BODY")
        before = sorted((p.name, p.stat().st_size) for p in self.bucket.iterdir())
        output = StringIO()
        with self.linux_host(), redirect_stdout(output):
            code = cat.main(["--home", str(self.home), "--project", str(self.project)])
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["sessions"][0]["session_id"], "sid-one")
        self.assertNotIn("SECRET_IN_BODY", output.getvalue())
        self.assertEqual(before, sorted((p.name, p.stat().st_size) for p in self.bucket.iterdir()))

    def test_cli_refuses_without_exposing_paths(self):
        from contextlib import redirect_stdout
        from io import StringIO
        output = StringIO()
        with self.linux_host(), redirect_stdout(output):
            code = cat.main(["--home", str(self.home), "--project", str(self.project),
                             "--offset", "3"])
        self.assertEqual(code, 1)
        reply = json.loads(output.getvalue())
        self.assertEqual(reply["status"], "unavailable")
        self.assertNotIn(str(self.home), output.getvalue())
        self.assertNotIn(str(self.project), output.getvalue())

if __name__ == '__main__':
    unittest.main()
