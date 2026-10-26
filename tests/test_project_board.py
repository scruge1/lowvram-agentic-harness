"""Read-view isolation and asset delivery controls; native data is qualified separately."""
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler, Request

from harness import project_board as board


class ProjectBoardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        # Hosted Windows TEMP can use an 8.3 alias; real selection is canonical.
        self.root = Path(self.temporary.name).resolve()
        self.home, self.project = self.root / "home", self.root / "project with spaces"
        (self.project / ".icm").mkdir(parents=True)
        identity = self.project / ".icm/project.json"
        identity.write_text('{"source":"synthetic identity bytes"}', encoding="utf-8")
        database = self.root / "kanban.db"
        database.write_bytes(b"Synthetic file identity; no native data claim")
        info = database.stat()
        self.selected = board.Selection(self.home, self.project, "p_fixture", "project:p_fixture", database,
                                        board.digest(identity), (info.st_dev, info.st_ino))

    def test_identity_and_database_replacement_refuse_before_adapter(self):
        identity = self.project / ".icm/project.json"
        original = identity.read_bytes()
        identity.write_bytes(b"changed")
        with patch.object(board.subprocess, "run") as call:
            with self.assertRaisesRegex(board.BoardViewError, "identity changed"):
                self.selected.call("status")
            call.assert_not_called()
        identity.write_bytes(original)
        self.selected.database.rename(self.root / "retained-original.db")
        self.selected.database.write_bytes(b"replacement")
        with self.assertRaisesRegex(board.BoardViewError, "board identity changed"):
            self.selected.recheck()

    def test_missing_verified_package_stops_before_project_selection(self):
        with patch.object(board.home_entry, "consumer") as lease, patch.object(board.homes, "load", return_value=(self.home, {"installed": {}})), patch.object(board.managed_launch, "select_project") as select:
            lease.return_value.__enter__.return_value = ()
            with self.assertRaisesRegex(board.BoardViewError, "verify.*Hermes"):
                with board.selected_project(self.home, self.project):
                    self.fail("Unverified package admitted")
            select.assert_not_called()

    def assets(self):
        directory = self.root / "assets"
        directory.mkdir()
        (directory / "index.html").write_text("<p>inert delivery</p>", encoding="utf-8")
        (directory / "view.js").write_text("/* synthetic asset */", encoding="utf-8")
        manifest = {"schema": "project-board-assets/v1", "hermes_commit": board.HERMES_COMMIT,
                    "files": {name: board.digest(directory / name) for name in ("index.html", "view.js")}}
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return directory

    def test_manifest_and_escaped_asset_paths_are_refused(self):
        directory = self.assets()
        with self.assertRaisesRegex(board.BoardViewError, "manifest differs"):
            board.asset_files(directory, "0" * 64)
        manifest = directory / "manifest.json"
        value = json.loads(manifest.read_text())
        value["files"]["../outside.js"] = "0" * 64
        manifest.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(board.BoardViewError, "asset path"):
            board.asset_files(directory, board.digest(manifest))

    def test_http_effect_foreign_selection_and_late_asset_drift(self):
        directory = self.assets()
        server = ThreadingHTTPServer(("127.0.0.1", 0), board.handler(self.selected, board.asset_files(directory, board.digest(directory / "manifest.json"))))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: thread.join(timeout=2))
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        opener = build_opener(ProxyHandler({}))
        def request(path, status, method="GET", headers=None):
            req = Request(f"http://127.0.0.1:{server.server_port}" + path, method=method, headers=headers or {})
            try:
                with opener.open(req, timeout=5) as response:
                    actual, data = response.status, response.read()
            except HTTPError as error:
                actual, data = error.code, error.read()
            self.assertEqual(actual, status, data)
            return data
        with patch.object(board.subprocess, "run") as adapter:
            self.assertIn(b"p_fixture", request("/api/project-board", 200))
            request("/api/plugins/kanban/board?tenant=foreign", 400)
            request("/api/plugins/kanban/board?board=foreign", 400)
            request("/api/project-board?tenant=a&tenant=b", 400)
            request("/api/project-board?tenant=&tenant=" + self.selected.tenant, 400)
            request("/api/project-board", 400, headers={"Origin": "https://foreign.invalid"})
            request("/api/plugins/kanban/dispatch", 405, method="POST")
            adapter.assert_not_called()
        request("/view.js", 200)
        (directory / "view.js").write_bytes(b"MUTATED_AFTER_SELECTION")
        self.assertNotIn(b"MUTATED_AFTER_SELECTION", request("/view.js", 400))
        request("/../outside.js", 400)


if __name__ == "__main__":
    unittest.main()
