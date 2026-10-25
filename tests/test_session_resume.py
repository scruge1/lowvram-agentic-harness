"""Cooperative Linux ownership and optional installed-Pi continuation checks.

Set PI_SESSION_TEST_PI_PACKAGE and PI_SESSION_TEST_NODE for the real Pi1.4
metadata/CLI cases. These tests never submit a prompt or request inference.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from harness import session_resume as resume


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


class PlatformTests(unittest.TestCase):
    def test_unsupported_platform_refuses_before_filesystem_access(self):
        with mock.patch.object(resume.sys, "platform", "win32"):
            with self.assertRaisesRegex(resume.SessionResumeError, "requires Linux"):
                resume.acquire("missing", "missing", node="missing", pi_package="missing")


@unittest.skipUnless(sys.platform == "linux", "Linux flock/proc ownership")
class SessionLeaseTests(unittest.TestCase):
    def setUp(self):
        root = os.environ.get("PI_SESSION_TEST_ROOT")
        temporary = tempfile.TemporaryDirectory(prefix="session-resume-", dir=root)
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.home = self.base / "Hôme α with spaces"
        self.home.mkdir()
        (self.home / "agent").mkdir()
        write_json(self.home / "home.json", {"home": str(self.home)})
        self.project, self.identity = self.make_project("project β", "fixture-primary")
        self.package = self.home / "packages/pi/node_modules/@earendil-works/pi-coding-agent"
        write_json(self.package / "package.json", {"name": "@earendil-works/pi-coding-agent", "version": "1.4.0"})
        (self.package / "dist").mkdir()
        (self.package / "dist/cli.js").write_text("setInterval(()=>{},1000);\n")
        self.node = Path(os.environ.get("PI_SESSION_TEST_NODE") or shutil.which("node") or sys.executable).resolve()

    def make_project(self, name, project_id):
        project = self.base / name
        project.mkdir()
        state = self.home / "state/projects" / project_id
        state.mkdir(parents=True)
        identity = {"project_id": project_id, "board_id": "project:" + project_id,
                    "canonical_root": str(project), "state_root": str(state)}
        write_json(project / ".icm/project.json", identity)
        return project, identity

    def acquire(self, project=None, identity=None, **kwargs):
        return resume.acquire(self.home, project or self.project, node=self.node, pi_package=self.package,
                              project_identity=identity or self.identity, **kwargs)

    def bucket(self):
        return resume.session_directory(self.home, self.project)

    def test_fresh_lease_blocks_same_bucket_but_other_project_is_independent(self):
        other, identity = self.make_project("other project", "fixture-other")
        with self.acquire() as lease:
            self.assertEqual(lease.pi_args, ())
            self.assertEqual(lease.pass_fds, (lease.fd,))
            self.assertEqual(list(lease.bucket.glob("*.jsonl")), [])
            with self.assertRaises(resume.SessionBusyError):
                self.acquire()
            with self.acquire(other, identity) as independent:
                self.assertNotEqual(independent.bucket, lease.bucket)
        with self.acquire():
            pass
        with self.assertRaises(resume.SessionResumeError):
            _ = lease.pass_fds

    def test_empty_continue_is_typed_refusal_not_new_session(self):
        with self.assertRaisesRegex(resume.NoPreviousSession, "No previous session in this home/project"):
            self.acquire(continue_recent=True)
        self.assertEqual(list(self.bucket().glob("*.jsonl")), [])
        with self.acquire():
            pass

    def test_home_and_current_identity_must_agree(self):
        different = dict(self.identity, board_id="project:different")
        with self.assertRaisesRegex(resume.SessionScopeError, "identity changed"):
            self.acquire(identity=different)
        foreign = self.base / "foreign-home-state"
        foreign.mkdir()
        different = dict(self.identity, state_root=str(foreign))
        write_json(self.project / ".icm/project.json", different)
        with self.assertRaisesRegex(resume.SessionScopeError, "another agent home"):
            self.acquire(identity=different)
        write_json(self.home / "home.json", {"home": str(self.base)})
        with self.assertRaisesRegex(resume.SessionScopeError, "home binding"):
            self.acquire()

    def test_session_directory_symlink_is_refused(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.home / "agent/sessions").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(resume.SessionScopeError, "symlink"):
            self.acquire()
        self.assertEqual(list(outside.iterdir()), [])

    def test_lock_alias_is_refused_without_touching_target(self):
        bucket = resume._directory(self.home, self.project)
        target = self.base / "unrelated"
        target.write_text("keep\n")
        os.link(target, bucket / ".managed-session.lock")
        with self.assertRaisesRegex(resume.SessionScopeError, "single-link"):
            self.acquire()
        self.assertEqual(target.read_text(), "keep\n")

    def test_malformed_foreign_incomplete_and_linked_history_is_unchanged(self):
        bucket = resume._directory(self.home, self.project)
        path = bucket / "owned.jsonl"
        examples = [b"[]\n", b"not-json\n", json.dumps({"type": "session", "cwd": str(self.base)}).encode() + b"\n",
                    json.dumps({"type": "session", "cwd": str(self.project)}).encode()]
        for raw in examples:
            path.write_bytes(raw)
            before = path.stat().st_mtime_ns
            with self.assertRaises(resume.SessionScopeError):
                self.acquire(continue_recent=True)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(path.stat().st_mtime_ns, before)
        path.unlink()
        target = self.base / "outside.jsonl"
        target.write_bytes(b"owned outside data\n")
        path.symlink_to(target)
        with self.assertRaises(resume.SessionScopeError):
            self.acquire(continue_recent=True)
        self.assertEqual(target.read_bytes(), b"owned outside data\n")

    def node_required(self):
        if self.node.name not in ("node", "nodejs"):
            self.skipTest("Node is not installed")

    @contextlib.contextmanager
    def node_owner(self, *, agent=None, cwd=None, args=(), entry=None, pass_fds=()):
        self.node_required()
        env = {key: os.environ[key] for key in ("HOME", "PATH", "LANG") if key in os.environ}
        env["PI_CODING_AGENT_DIR"] = str(agent or self.home / "agent")
        process = subprocess.Popen([str(self.node), str(entry or self.package / "dist/cli.js"), *args],
                                   cwd=cwd or self.project, env=env, pass_fds=pass_fds,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            time.sleep(0.1)
            if process.poll() is not None:
                self.fail("Owned Node fixture exited: " + process.stderr.read().decode())
            yield process
        finally:
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=5)

    def test_recognized_same_uid_owner_is_refused_without_signaling(self):
        with self.node_owner() as process:
            with self.assertRaises(resume.SessionBusyError) as caught:
                self.acquire()
            self.assertIn(process.pid, [owner.pid for owner in caught.exception.owners])
            self.assertIsNone(process.poll())

    def test_foreign_home_project_and_non_pi_node_do_not_claim_bucket(self):
        other, _ = self.make_project("foreign project", "fixture-foreign")
        other_agent = self.base / "foreign-agent"
        other_agent.mkdir()
        unrelated = self.base / "unrelated.js"
        unrelated.write_text("setInterval(()=>{},1000);\n")
        for options in ({"agent": other_agent}, {"cwd": other}, {"entry": unrelated}):
            with self.node_owner(**options):
                with self.acquire():
                    pass

    def test_explicit_native_session_bucket_is_detected_from_other_cwd(self):
        with self.node_owner(cwd=self.base, args=("--session-dir", str(self.bucket()))) as process:
            with self.assertRaises(resume.SessionBusyError) as caught:
                self.acquire()
            self.assertEqual(caught.exception.owners[0].pid, process.pid)

    def test_actual_node_inherits_lease_after_parent_descriptor_closes(self):
        self.node_required()
        lease = self.acquire()
        with self.node_owner(pass_fds=lease.pass_fds) as process:
            fd = lease.fd
            self.assertEqual(Path(os.readlink(f"/proc/{process.pid}/fd/{fd}")), self.bucket() / ".managed-session.lock")
            lease.close()
            with self.assertRaises(resume.SessionBusyError):
                resume._lock(self.bucket())
            process.terminate()
            process.wait(timeout=5)
            released = resume._lock(self.bucket())
            os.close(released)

    def test_parent_crash_keeps_actual_node_descriptor_until_child_exits(self):
        self.node_required()
        import ctypes
        library = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int()
        self.assertEqual(library.prctl(37, ctypes.byref(previous), 0, 0, 0), 0)
        self.assertEqual(library.prctl(36, 1, 0, 0, 0), 0)
        self.addCleanup(lambda: library.prctl(36, previous.value, 0, 0, 0))
        input_read, input_write = os.pipe()
        code = """import json,subprocess,sys,time
from pathlib import Path
from harness.session_resume import acquire
home,project,node,package,input_fd,arguments=sys.argv[1:]
identity=json.loads((Path(project)/'.icm/project.json').read_text())
lease=acquire(home,project,node=node,pi_package=package,project_identity=identity)
child=subprocess.Popen([node,str(Path(package)/'dist/cli.js'),*json.loads(arguments)],cwd=project,stdin=int(input_fd),pass_fds=lease.pass_fds,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
print(json.dumps({'pid':child.pid,'fd':lease.fd}),flush=True)
time.sleep(30)
"""
        arguments = ["--offline", "--mode", "rpc", "--provider", "local", "--model", "fixture-model"]
        env = {key: os.environ[key] for key in ("HOME", "PATH", "LANG") if key in os.environ}
        env.update(PI_CODING_AGENT_DIR=str(self.home / "agent"), PI_OFFLINE="1", PI_SKIP_VERSION_CHECK="1")
        parent = subprocess.Popen([sys.executable, "-B", "-c", code, str(self.home), str(self.project), str(self.node), str(self.package),
                                   str(input_read), json.dumps(arguments)], env=env, pass_fds=(input_read,),
                                  cwd=Path(__file__).resolve().parents[1], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        child_pid = None
        try:
            ready, _, _ = __import__("select").select([parent.stdout], [], [], 10)
            self.assertTrue(ready, "Owned wrapper did not report child")
            details = json.loads(parent.stdout.readline())
            child_pid = details["pid"]
            parent.kill()
            parent.wait(timeout=5)
            self.assertEqual(Path(os.readlink(f"/proc/{child_pid}/fd/{details['fd']}")), self.bucket() / ".managed-session.lock")
            with self.assertRaises(resume.SessionBusyError):
                resume._lock(self.bucket())
            os.kill(child_pid, signal.SIGTERM)
            os.waitpid(child_pid, 0)
            child_pid = None
            fd = resume._lock(self.bucket())
            os.close(fd)
        finally:
            if parent.poll() is None:
                parent.kill()
            parent.communicate(timeout=5)
            if child_pid:
                os.kill(child_pid, signal.SIGTERM)
                os.waitpid(child_pid, 0)
            os.close(input_read)
            os.close(input_write)


@unittest.skipUnless(sys.platform == "linux" and os.environ.get("PI_SESSION_TEST_PI_PACKAGE") and os.environ.get("PI_SESSION_TEST_NODE"),
                     "Set installed Pi1.4 package and Node paths for native qualification")
class NativeSessionTests(SessionLeaseTests):
    # Inherited ownership cases also run against the actual installed package.
    def setUp(self):
        super().setUp()
        shutil.rmtree(self.package)
        self.package.symlink_to(Path(os.environ["PI_SESSION_TEST_PI_PACKAGE"]).resolve(), target_is_directory=True)
        self.node = Path(os.environ["PI_SESSION_TEST_NODE"]).resolve()
        write_json(self.home / "agent/settings.json", {"extensions": [], "packages": [], "compaction": {"enabled": False},
                                                       "retry": {"enabled": False}, "defaultProvider": "local", "defaultModel": "fixture-model"})
        write_json(self.home / "agent/models.json", {"providers": {"local": {"baseUrl": "http://127.0.0.1:9/v1", "apiKey": "local",
                   "api": "openai-completions", "models": [{"id": "fixture-model", "contextWindow": 32768, "maxTokens": 4096}]}}})

    def native(self, code, *arguments):
        env = {key: os.environ[key] for key in ("HOME", "PATH", "LANG") if key in os.environ}
        env.update(PI_CODING_AGENT_DIR=str(self.home / "agent"), PI_OFFLINE="1", PI_SKIP_VERSION_CHECK="1")
        body = "import {pathToFileURL} from 'node:url';const api=await import(pathToFileURL(process.argv[1]+'/dist/core/session-manager.js'));" + code
        result = subprocess.run([str(self.node), "--input-type=module", "--eval", body, str(self.package.resolve()), *map(str, arguments)],
                                env=env, cwd=self.project, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def saved(self, saved_project=None):
        bucket = resume._directory(self.home, self.project)
        code = """const cwd=process.argv[2],bucket=process.argv[3],saved=JSON.parse(process.argv[4]);
const manager=api.SessionManager.create(cwd,bucket);
manager.appendMessage({role:'user',content:'Owned synthetic session metadata only.',timestamp:1});
if(saved)manager.appendCustomEntry('pi-kanban-selection/v1',{project:saved,task:null});
console.log(JSON.stringify({path:manager.getSessionFile(),id:manager.getSessionId()}));"""
        value = self.native(code, self.project, bucket, json.dumps(saved_project))
        return Path(value["path"]), value["id"]

    def test_native_continue_selects_actual_recent_session_preserving_all_bytes(self):
        saved = {"root": str(self.project), "projectId": self.identity["project_id"], "boardId": self.identity["board_id"]}
        old, _ = self.saved(saved)
        newest, expected_id = self.saved(saved)
        os.utime(old, ns=(1_000_000_000, 1_000_000_000))
        snapshots = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (old, newest)}
        with self.acquire(continue_recent=True) as lease:
            self.assertEqual(lease.pi_args, ("--session", str(newest)))
            self.assertEqual(lease.selection["id"], expected_id)
            self.assertEqual(lease.selection["saved_project"], saved)
            self.assertEqual(lease.selection["source_sha256"], hashlib.sha256(snapshots[newest][0]).hexdigest())
            self.assertEqual(lease.selection["listed_count"], 2)
        for path, snapshot in snapshots.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), snapshot)

    def test_native_history_without_saved_navigation_is_allowed_in_same_scope(self):
        path, _ = self.saved()
        before = path.read_bytes()
        with self.acquire(continue_recent=True) as lease:
            self.assertIsNone(lease.selection["saved_project"])
        self.assertEqual(path.read_bytes(), before)

    def test_native_saved_project_mismatch_refuses_unchanged_source(self):
        path, _ = self.saved({"root": str(self.project), "projectId": "foreign", "boardId": self.identity["board_id"]})
        before = path.read_bytes()
        with self.assertRaisesRegex(resume.SessionScopeError, "Saved selected project differs"):
            self.acquire(continue_recent=True)
        self.assertEqual(path.read_bytes(), before)

    def test_native_legacy_version_is_refused_without_migration(self):
        path, _ = self.saved()
        lines = path.read_text().splitlines()
        header = json.loads(lines[0])
        header["version"] = 2
        lines[0] = json.dumps(header)
        path.write_text("\n".join(lines) + "\n")
        before = path.read_bytes()
        with self.assertRaisesRegex(resume.SessionScopeError, "migration is not admitted"):
            self.acquire(continue_recent=True)
        self.assertEqual(path.read_bytes(), before)

    def test_erased_unmanaged_override_in_same_home_conservatively_blocks_continue(self):
        self.saved()
        with self.node_owner(cwd=self.base, args=("--session-dir", str(self.bucket()))):
            # The original raw flag becomes invisible after actual Pi startup.
            # A continue request must refuse this unknown same-home owner.
            with self.assertRaises(resume.SessionBusyError):
                self.acquire(continue_recent=True)

    def test_actual_other_project_inherited_bucket_lease_allows_this_continue(self):
        self.saved()
        other, identity = self.make_project("managed other project", "fixture-managed-other")
        lease = self.acquire(other, identity)
        try:
            with self.node_owner(cwd=other, pass_fds=lease.pass_fds):
                lease.close()
                with self.acquire(continue_recent=True) as selected:
                    self.assertEqual(selected.selection["header_cwd"], str(self.project))
        finally:
            lease.close()

    @contextlib.contextmanager
    def node_owner(self, **options):
        # The inherited owner tests execute REAL Pi in inert RPC mode. No prompts.
        if "entry" in options:
            with super().node_owner(**options) as process:
                yield process
            return
        args = ("--offline", "--mode", "rpc", "--provider", "local", "--model", "fixture-model", *options.pop("args", ()))
        env = {key: os.environ[key] for key in ("HOME", "PATH", "LANG") if key in os.environ}
        agent = options.pop("agent", self.home / "agent")
        if agent != self.home / "agent":
            for name in ("settings.json", "models.json"):
                shutil.copyfile(self.home / "agent" / name, agent / name)
        env.update(PI_CODING_AGENT_DIR=str(agent), PI_OFFLINE="1", PI_SKIP_VERSION_CHECK="1")
        session_dir = options.pop("session_dir", None)
        if session_dir:
            env["PI_CODING_AGENT_SESSION_DIR"] = str(session_dir)
        process = subprocess.Popen([str(self.node), str(options.pop("entry", self.package / "dist/cli.js")), *args],
                                   cwd=options.pop("cwd", self.project), env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **options)
        try:
            process.stdin.write('{"id":"qualification","type":"get_state"}\n')
            process.stdin.flush()
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            self.addCleanup(selector.close)
            deadline = time.monotonic() + 20
            response = None
            while time.monotonic() < deadline and process.poll() is None:
                if selector.select(0.2):
                    line = process.stdout.readline()
                    if line:
                        candidate = json.loads(line)
                        if candidate.get("id") == "qualification":
                            response = candidate
                            break
            error = process.stderr.read() if process.poll() is not None else "still running"
            self.assertIsNotNone(response, "Owned native CLI did not answer get_state: " + error)
            self.assertTrue(response.get("success"), response)
            yield process
        finally:
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=10)

    def test_explicit_native_session_bucket_is_detected_from_other_cwd(self):
        # Pi process.title erases argv. Only an explicit environment binding is
        # observable after native startup from an unrelated cwd; no global lock
        # is claimed for an unmanaged, concealed --session-dir override.
        with self.node_owner(cwd=self.base, args=("--session-dir", str(self.bucket())), session_dir=self.bucket()) as process:
            with self.assertRaises(resume.SessionBusyError) as caught:
                self.acquire()
            self.assertEqual(caught.exception.owners[0].pid, process.pid)


if __name__ == "__main__":
    unittest.main()
