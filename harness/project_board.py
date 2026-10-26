"""Loopback read view of one existing, explicitly selected project board.

No model, chat, dispatcher, project registry, remote bind or mutation route.
The native UI build is separate from source and package installation acceptance.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import parse_qsl, urlsplit

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import home as homes, home_entry, managed_launch, session_resume

MAX_REPLY = 2 * 1024 * 1024
HERMES_COMMIT = "866332bfb52c46e543143b2620a9aeee8bce9c77"


class BoardViewError(ValueError):
    pass


def require(value, message):
    if not value:
        raise BoardViewError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class Selection:
    home: Path
    project: Path
    project_id: str
    tenant: str
    database: Path
    identity_sha256: str
    database_identity: tuple
    lifecycle_fds: tuple = ()

    def recheck(self):
        identity = self.project / ".icm/project.json"
        require(identity.is_file() and not identity.is_symlink() and digest(identity) == self.identity_sha256,
                "Selected project identity changed; reopen the view")
        require(self.database.is_file() and not self.database.is_symlink(), "Selected board is unavailable")
        require(self.database.resolve() == self.database, "Selected board path is redirected")
        info = self.database.stat()
        require((info.st_dev, info.st_ino) == self.database_identity, "Selected board identity changed")

    def call(self, action, **values):
        self.recheck()
        environment = homes.environment(self.home)
        environment.update(HERMES_HOME=str(self.home / "state/hermes"),
                           HERMES_KANBAN_DB=str(self.database))
        if self.lifecycle_fds:
            environment[home_entry.FD_ENV] = str(self.lifecycle_fds[0])
        request = dict(values, action=action, project_root=str(self.project))
        run = subprocess.run([environment["PI_PROJECT_KANBAN_PYTHON"], "-B", environment["PI_PROJECT_KANBAN_ADAPTER"]],
                             cwd=self.home, env=environment, input=json.dumps(request), text=True, encoding="utf-8",
                             capture_output=True, timeout=30, pass_fds=self.lifecycle_fds)
        require(run.returncode == 0, "Project adapter refused the read: " + run.stderr[-2000:])
        raw = run.stdout
        require(len(raw.encode("utf-8")) <= MAX_REPLY, "Read view exceeds its response limit; use project CLI views")
        result = json.loads(raw)
        require(result.get("ok") is True, "Project adapter refused the read")
        self.recheck()
        return result["result"]


@contextmanager
def selected_project(home, project):
    """Keep the normal home READ lifetime; never initialize a project or DB."""
    require(project is not None, "Select an explicit existing project")
    with home_entry.consumer(home) as inherited:
        home, config = homes.load(Path(home))
        record = config.get("installed", {}).get("hermes")
        require(record and homes.check_package(home, "hermes", record) is None,
                "Install and verify this home's exact Hermes package before opening its board")
        root = managed_launch.select_project(home, project)
        current, identity_hash = session_resume._json(root / ".icm/project.json")
        identity, checked_hash = session_resume._project(home, root, current)
        require(identity_hash == checked_hash, "Project identity changed during selection")
        database = Path(identity["state_root"]) / "kanban.db"
        require(database.is_file() and not database.is_symlink(), "Use an existing admitted project board")
        require(database.resolve() == database, "Selected board path is redirected")
        info = database.stat()
        selected = Selection(home, root, identity["project_id"], identity["board_id"], database,
                             identity_hash, (info.st_dev, info.st_ino), tuple(inherited))
        status = selected.call("status")
        require(status.get("project_id") == selected.project_id and status.get("board_id") == selected.tenant,
                "Native board differs from the selected project")
        require(status.get("backend_revision") == HERMES_COMMIT and status.get("dispatcher") == "disabled",
                "Use the reviewed project backend without dispatch")
        yield selected


def project_projection(selected):
    selected.recheck()
    return {"projects": [{"id": selected.project_id, "slug": selected.project.name,
                           "name": selected.project.name, "primary_path": str(selected.project),
                           "icon": "", "color": ""}], "read_only": True,
            "source": "existing-public-project-identity"}


def read_api(selected, path, query):
    selected.recheck()
    require(query.get("board", "default") == "default", "Only the selected project board is available")
    require(query.get("tenant", selected.tenant) == selected.tenant, "Only the selected project tenant is available")
    if path == "/api/project-board":
        return {"project_id": selected.project_id, "name": selected.project.name,
                "project_root": str(selected.project), "read_only": True,
                "updates": "Reload to refresh", "result_scope": "Existing result text; not checked-artifact acceptance"}
    base = "/api/plugins/kanban"
    if path == base + "/config":
        return {"read_only": True, "default_tenant": selected.tenant, "lane_by_profile": False,
                "include_archived_by_default": False, "render_markdown": False}
    if path == base + "/projects":
        return project_projection(selected)
    if path in {base + "/board", base + "/boards"}:
        require(query.get("include_archived", "false") in {"true", "false"}, "Invalid archive filter")
        board = selected.call("board_read_view", include_archived=query.get("include_archived") == "true")
        if path.endswith("/board"):
            return board
        counts = {column["name"]: len(column["tasks"]) for column in board["columns"]}
        return {"boards": [{"slug": "default", "title": selected.project.name, "name": selected.project.name,
                            "project_id": selected.project_id, "project_name": selected.project.name,
                            "is_current": True, "counts": counts, "total": sum(counts.values())}],
                "current": "default", "read_only": True}
    prefix = base + "/tasks/"
    if path.startswith(prefix) and "/" not in path[len(prefix):]:
        return selected.call("task_read_view", task_id=path[len(prefix):])
    if path == base + "/home-channels":
        return {"channels": [], "available": False, "scope": "Notifications are not exposed by this read view"}
    raise BoardViewError("Read route is not available")


def asset_files(directory, expected_manifest):
    directory = Path(directory).resolve(strict=True)
    manifest = directory / "manifest.json"
    require(manifest.is_file() and not manifest.is_symlink(), "Use a reviewed local UI asset build")
    require(digest(manifest) == expected_manifest, "UI asset manifest differs from the reviewed build")
    value = json.loads(manifest.read_text(encoding="utf-8"))
    require(value.get("schema") == "project-board-assets/v1" and value.get("hermes_commit") == HERMES_COMMIT,
            "UI asset source does not match the reviewed native package")
    result = {}
    for name, expected in value["files"].items():
        relative = Path(name)
        require(not relative.is_absolute() and ".." not in relative.parts, "Invalid UI asset path")
        path = directory / relative
        require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(directory), "UI asset escaped its build")
        require(digest(path) == expected, "UI asset bytes changed: " + name)
        result["/" + relative.as_posix()] = (path, expected)
    require("/index.html" in result, "UI entry is missing")
    return result


def handler(selected, assets):
    class ReadViewHandler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # No project data, query strings or headers in routine logs.

        def reply(self, status, body, kind="application/json; charset=utf-8", head=False):
            require(len(body) <= MAX_REPLY, "Response exceeds the read-view limit")
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def read(self, head=False):
            try:
                host = self.headers.get("Host", "")
                require(host in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}, "Loopback host required")
                require(self.headers.get("Origin", "http://" + host) == "http://" + host, "Cross-origin read refused")
                require(self.headers.get("Sec-Fetch-Site") != "cross-site", "Cross-site read refused")
                selected.recheck()
                parsed = urlsplit(self.path)
                pairs = parse_qsl(parsed.query, keep_blank_values=True)
                require(len({key for key, _ in pairs}) == len(pairs), "Duplicate selection parameter")
                if parsed.path.startswith("/api/"):
                    value = read_api(selected, parsed.path, dict(pairs))
                    self.reply(200, json.dumps(value, ensure_ascii=False).encode("utf-8"), head=head)
                else:
                    name = "/index.html" if parsed.path == "/" else parsed.path
                    require(name in assets, "UI asset is not available")
                    path, expected = assets[name]
                    body = path.read_bytes()
                    require(hashlib.sha256(body).hexdigest() == expected, "UI asset changed before delivery")
                    kinds = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                             ".css": "text/css; charset=utf-8", ".woff2": "font/woff2", ".woff": "font/woff"}
                    self.reply(200, body, kinds.get(path.suffix, "application/octet-stream"), head=head)
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
                self.reply(400, json.dumps({"error": str(error), "read_only": True}).encode("utf-8"), head=head)

        def do_GET(self):
            self.read()

        def do_HEAD(self):
            self.read(head=True)

        def refuse(self):
            self.reply(405, b'{"error":"Read view only; effects are unavailable","read_only":true}')

        do_POST = do_PUT = do_PATCH = do_DELETE = refuse
    return ReadViewHandler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--assets", type=Path)
    parser.add_argument("--asset-manifest-sha256")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)
    require(0 <= args.port <= 65535, "Invalid local port")
    require(args.assets is not None and args.asset_manifest_sha256,
            "Board UI files are not installed. Build the pinned local assets with scripts/build_project_board_assets.py, "
            "then supply --assets and --asset-manifest-sha256. Automatic installation is not available yet.")
    assets = asset_files(args.assets, args.asset_manifest_sha256)
    with selected_project(args.home, args.project) as selected:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(selected, assets))
        try:
            print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}/", "project": selected.project_id,
                              "read_only": True, "access": "Same-machine loopback; no remote authentication claim"}), flush=True)
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
