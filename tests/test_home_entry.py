"""Stable-entry subprocess tests with an explicit minimal runtime observer."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from harness import home_entry


REPO = Path(__file__).resolve().parents[1]
GUARD = REPO / "harness/home_lifecycle.py"
RUNTIME = '''import json,os,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2]
busy=None
if sys.platform=='linux':
    import fcntl
    descriptor=os.open(root/'state/home-lifecycle.lock',os.O_RDWR)
    try:
        try:
            fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
            busy=False
        except BlockingIOError:
            busy=True
    finally:
        os.close(descriptor)
observation={'runtime_imported':True,'shared_before_import':busy,
             'fd_env':os.environ.get('AGENT_HOME_LIFECYCLE_FD')}
Path(os.environ['ENTRY_IMPORT_MARKER']).write_text(json.dumps(observation))
def main(argv=None,*,bound_home=None):
    result={**observation,'pid':os.getpid(),'argv':argv,'bound_home':str(bound_home)}
    mode=os.environ.get('ENTRY_FIXTURE_MODE','report')
    if mode=='spawn':
        import subprocess,time
        from harness import home_entry
        passed=home_entry.inherited_pass_fds(bound_home)
        child=subprocess.Popen([sys.executable,'-B','-c',os.environ['ENTRY_CHILD_PROGRAM'],
                                os.environ['ENTRY_CHILD_READY'],os.environ['ENTRY_CHILD_RELEASE'],str(passed[0])],
                               pass_fds=passed,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        deadline=time.monotonic()+5
        while not Path(os.environ['ENTRY_CHILD_READY']).exists() and time.monotonic()<deadline:
            if child.poll() is not None:raise ValueError('Fixture child exited')
            time.sleep(.01)
        if not Path(os.environ['ENTRY_CHILD_READY']).exists():raise ValueError('Fixture child readiness timed out')
        result['child_pid']=child.pid
        print(json.dumps(result),flush=True)
        os._exit(0)  # Parent exits without context cleanup; child must keep its fd copy.
    print(json.dumps(result),flush=True)
    if mode=='hold':sys.stdin.buffer.read(1)
    return 0
'''
CHILD = '''import json,os,sys,time
from pathlib import Path
ready,release=Path(sys.argv[1]),Path(sys.argv[2]);fd=int(sys.argv[3]);info=os.fstat(fd)
ready.write_text(json.dumps({'pid':os.getpid(),'fd':fd,'inode':info.st_ino}))
deadline=time.monotonic()+10
while not release.exists() and time.monotonic()<deadline:time.sleep(.01)
'''


class EntryFixture(unittest.TestCase):
    def setUp(self):
        selected = os.environ.get("HOME_ENTRY_TEST_ROOT")
        if not selected and os.name == "nt" and Path("E:/").is_dir():
            selected = "E:/"
        self.temporary = tempfile.TemporaryDirectory(prefix="harness-entry-", dir=selected)
        self.base = Path(self.temporary.name).resolve()
        self.parent = self.base.parent
        self.home = self.base / "agent home ü"
        self.home.mkdir()
        (self.home / "state").mkdir()
        self.config = {"schema": "agent-home/v1", "home": str(self.home), "profile": "core"}
        self.config_file = self.home / "home.json"
        self.config_file.write_text(json.dumps(self.config), encoding="utf-8")
        self.protected = []
        for name in ("agent/APPEND_SYSTEM.md", "context/owner.md", "agent/auth.json", "agent/sessions/keep.jsonl",
                     "memory/palace/keep.bin", "state/projects/keep.bin", "packages/cache.bin"):
            path = self.home / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic retained user bytes: " + name)
            self.protected.append(path)
        self.protected_before = {str(p): p.read_bytes() for p in self.protected}
        original_config = self.config_file.read_bytes()
        self.binding = home_entry.install(self.home, guard_source=GUARD)
        self.assertEqual(self.config_file.read_bytes(), original_config)
        self.config["lifecycle_guard_sha256"] = self.binding["guard_sha256"]
        self.config_file.write_text(json.dumps(self.config), encoding="utf-8")  # Caller integration, not helper magic.
        self.launcher = self.home / "agent-home.py"
        runtime = self.home / "runtime/harness"
        runtime.mkdir(parents=True)
        (runtime / "__init__.py").write_text("")
        (runtime / "home.py").write_text(RUNTIME, encoding="utf-8")
        shutil.copyfile(REPO / "harness/home_entry.py", runtime / "home_entry.py")
        self.marker = self.base / "runtime-imported.json"
        self.child_release = self.base / "child-release"
        self.child_ready = self.base / "child-ready.json"
        self.children = []
        self.addCleanup(self.clean_fixture)

    def clean_fixture(self):
        self.child_release.touch()
        for child in self.children:
            if child.poll() is None:
                child.stdin.close()
                child.stdin = None
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=3)
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream is not None:
                    stream.close()
        self.assertEqual({str(p): p.read_bytes() for p in self.protected}, self.protected_before)
        self.assertEqual(self.base.parent, self.parent)
        self.assertEqual(self.base.resolve(), self.base)
        self.assertTrue(self.base.name.startswith("harness-entry-"))
        self.temporary.cleanup()

    def environment(self, mode="report"):
        return {**os.environ, "ENTRY_IMPORT_MARKER": str(self.marker), "ENTRY_FIXTURE_MODE": mode,
                "ENTRY_CHILD_PROGRAM": CHILD, "ENTRY_CHILD_READY": str(self.child_ready),
                "ENTRY_CHILD_RELEASE": str(self.child_release), "PYTHONDONTWRITEBYTECODE": "1"}

    def invoke(self, *args, expected=0, mode="report", environment=None):
        result = subprocess.run([sys.executable, "-B", str(self.launcher), *args], cwd=self.base,
                                env=environment or self.environment(mode), capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, expected, result.stderr)
        return result

    def load_guard(self):
        spec = importlib.util.spec_from_file_location("installed_entry_guard", self.home / "home-lifecycle.py")
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        return guard


class StableEntryTests(EntryFixture):
    def test_installed_bytes_pins_and_explicit_caller_binding(self):
        self.assertEqual((self.home / "home-lifecycle.py").read_bytes(), GUARD.read_bytes())
        self.assertEqual(hashlib.sha256(self.launcher.read_bytes()).hexdigest(), self.binding["launcher_sha256"])
        self.assertIn(self.binding["guard_sha256"], self.launcher.read_text())
        self.assertEqual(self.config["lifecycle_guard_sha256"], self.binding["guard_sha256"])
        self.assertIn("Caller must persist", self.binding["home_json_update"])

    def test_collision_is_nonoverwrite_and_does_not_change_home_configuration(self):
        before = {p.name: p.read_bytes() for p in (self.launcher, self.home / "home-lifecycle.py", self.config_file)}
        with self.assertRaisesRegex(ValueError, "occupied"):
            home_entry.install(self.home, guard_source=GUARD)
        self.assertEqual({p.name: p.read_bytes() for p in (self.launcher, self.home / "home-lifecycle.py", self.config_file)}, before)

    def test_guard_drift_cannot_execute_even_before_runtime_import(self):
        malicious_marker = self.base / "unexpected-guard-code"
        (self.home / "home-lifecycle.py").write_text(
            "from pathlib import Path\nPath(" + repr(str(malicious_marker)) + ").touch()\n")
        result = self.invoke("doctor", expected=1)
        self.assertIn("guard byte drift", result.stderr)
        self.assertFalse(malicious_marker.exists())
        self.assertFalse(self.marker.exists())

    def test_wrong_home_argument_and_config_refuse_before_runtime_import(self):
        foreign = self.base / "other home"
        foreign.mkdir()
        self.assertIn("different agent home", self.invoke("--home", str(foreign), "doctor", expected=1).stderr)
        self.assertFalse(self.marker.exists())
        self.config["home"] = str(foreign)
        self.config_file.write_text(json.dumps(self.config))
        self.assertIn("binding differs", self.invoke("doctor", expected=1).stderr)
        self.assertFalse(self.marker.exists())

    def test_missing_or_different_guard_binding_refuses_before_import(self):
        for value in (None, "0" * 64):
            self.config["lifecycle_guard_sha256"] = value
            self.config_file.write_text(json.dumps(self.config))
            self.assertIn("binding differs", self.invoke("doctor", expected=1).stderr)
            self.assertFalse(self.marker.exists())

    def test_actual_dispatch_retains_argv_unicode_path_and_bound_home(self):
        result = json.loads(self.invoke("doctor").stdout)
        self.assertEqual(result["bound_home"], str(self.home))
        self.assertEqual(result["argv"], ["--home", str(self.home), "doctor"])
        self.assertTrue(result["runtime_imported"])
        if sys.platform == "linux":
            self.assertTrue(result["shared_before_import"])
            self.assertIsNotNone(result["fd_env"])
        else:
            self.assertIsNone(result["shared_before_import"])
            self.assertIsNone(result["fd_env"])

    def test_existing_end_options_boundary_is_forwarded_to_runtime_parser(self):
        arguments = ["managed", "--", "--home", "literal Pi argument ; $(no-shell)"]
        result = json.loads(self.invoke(*arguments).stdout)
        self.assertEqual(result["argv"], ["--home", str(self.home), *arguments])
        self.assertEqual(result["bound_home"], str(self.home))

    def test_legacy_unpinned_home_explicitly_has_no_consumer_or_command_lease(self):
        self.config.pop("lifecycle_guard_sha256")
        self.config_file.write_text(json.dumps(self.config))
        with home_entry.consumer(self.home) as passed:
            self.assertEqual(passed, ())
        target = [sys.executable, "-B", "-c", "pass"]
        self.assertEqual(home_entry.guarded_command(self.home, target), target)
        self.assertFalse((self.home / "state/home-lifecycle.lock").exists())


@unittest.skipUnless(sys.platform == "linux", "Linux stable-entry lifetime controls")
class LinuxEntryTests(EntryFixture):
    def test_nested_consumer_acquires_its_own_fd_without_ambient_authority(self):
        guard = self.load_guard()
        with mock.patch.dict(os.environ, {home_entry.FD_ENV: "1"}):
            with home_entry.consumer(self.home) as fresh:
                self.assertGreaterEqual(fresh[0], 3)
                self.assertFalse(os.get_inheritable(fresh[0]))
                self.assertEqual(os.environ[home_entry.FD_ENV], "1")
                with self.assertRaisesRegex(ValueError, "busy"):
                    with guard.lease(self.home, expected_sha256=self.binding["guard_sha256"], mode="exclusive"):
                        self.fail("Independent consumer must hold a shared lease")
        with guard.lease(self.home, expected_sha256=self.binding["guard_sha256"]) as outer:
            with mock.patch.dict(os.environ, {home_entry.FD_ENV: str(outer.fd)}):
                with home_entry.consumer(self.home) as nested:
                    self.assertNotEqual(nested[0], outer.fd)
                    self.assertEqual(os.fstat(nested[0]).st_ino, os.fstat(outer.fd).st_ino)
                os.fstat(outer.fd)  # Inner close must not release/close the outer copy.
                with self.assertRaisesRegex(ValueError, "busy"):
                    with guard.lease(self.home, expected_sha256=self.binding["guard_sha256"], mode="exclusive"):
                        self.fail("Outer lease must remain held")
        with guard.lease(self.home, expected_sha256=self.binding["guard_sha256"], mode="exclusive"):
            pass

    def test_consumer_busy_pending_and_declared_invalid_pin_fail_closed(self):
        guard = self.load_guard()
        with guard.lease(self.home, expected_sha256=self.binding["guard_sha256"], mode="exclusive"):
            with self.assertRaisesRegex(ValueError, "busy"):
                with home_entry.consumer(self.home):
                    self.fail("Busy consumer admitted")
        updates = self.home / "state/updates"
        updates.mkdir()
        journal = updates / "pending-activation.json"
        journal.write_text("retained pending journal")
        with self.assertRaisesRegex(ValueError, "Pending activation"):
            with home_entry.consumer(self.home):
                self.fail("Pending consumer admitted")
        self.assertEqual(journal.read_text(), "retained pending journal")
        journal.unlink()
        self.config["lifecycle_guard_sha256"] = None
        self.config_file.write_text(json.dumps(self.config))
        with self.assertRaisesRegex(ValueError, "invalid"):
            with home_entry.consumer(self.home):
                self.fail("An invalid declared pin must not select legacy mode")

    def test_guarded_command_exec_preserves_final_pid_argv_and_lock(self):
        literal = "literal ü ; $(no-shell)"
        program = """import json,os,sys
fd=int(os.environ['AGENT_HOME_LIFECYCLE_FD'])
print(json.dumps({'pid':os.getpid(),'inode':os.fstat(fd).st_ino,'args':sys.argv[1:]}),flush=True)
sys.stdin.buffer.read(1)
"""
        target = [sys.executable, "-B", "-u", "-c", program, literal]
        argv = home_entry.guarded_command(self.home, target, python=sys.executable)
        self.assertEqual(argv[:2], [sys.executable, "-c"])
        child = subprocess.Popen(argv, cwd=self.base, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.children.append(child)
        import select
        self.assertTrue(select.select([child.stdout], [], [], 5)[0])
        line = child.stdout.readline()
        if not line:
            self.fail(child.stderr.read())
        ready = json.loads(line)
        self.assertEqual(ready["pid"], child.pid)
        self.assertEqual(ready["args"], [literal])
        actual_argv = (Path("/proc") / str(child.pid) / "cmdline").read_bytes().rstrip(b"\0").split(b"\0")
        self.assertEqual(actual_argv, [value.encode() for value in target])
        self.assertEqual(ready["inode"], (self.home / "state/home-lifecycle.lock").stat().st_ino)
        guard = self.load_guard()
        with self.assertRaisesRegex(ValueError, "busy"):
            with guard.lease(self.home, expected_sha256=self.binding["guard_sha256"], mode="exclusive"):
                self.fail("Final exec command must hold its lifetime lease")
        _output, error = child.communicate("x", timeout=5)
        self.assertEqual(child.returncode, 0, error)
        with guard.lease(self.home, expected_sha256=self.binding["guard_sha256"], mode="exclusive"):
            pass

    def test_guarded_command_pending_and_changed_guard_refuse_before_any_target_code(self):
        target_marker, guard_marker = self.base / "target-executed", self.base / "guard-executed"
        target = [sys.executable, "-B", "-c", "from pathlib import Path;Path(" + repr(str(target_marker)) + ").touch()"]
        argv = home_entry.guarded_command(self.home, target)
        updates = self.home / "state/updates"
        updates.mkdir()
        pending = updates / "pending-activation.json"
        pending.write_text("retained")
        result = subprocess.run(argv, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Pending activation", result.stderr)
        self.assertFalse(target_marker.exists())
        self.assertEqual(pending.read_text(), "retained")
        pending.unlink()
        (self.home / "home-lifecycle.py").write_text("from pathlib import Path;Path(" + repr(str(guard_marker)) + ").touch()")
        result = subprocess.run(argv, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn("guard byte drift", result.stderr)
        self.assertFalse(target_marker.exists())
        self.assertFalse(guard_marker.exists())

    def test_pending_journal_refuses_before_any_runtime_import(self):
        updates = self.home / "state/updates"
        updates.mkdir()
        pending = updates / "pending-activation.json"
        pending.write_text("partial journal")
        self.assertIn("Pending activation", self.invoke("doctor", expected=1).stderr)
        self.assertFalse(self.marker.exists())
        self.assertEqual(pending.read_text(), "partial journal")

    def test_exclusive_busy_refuses_before_runtime_import(self):
        guard = self.load_guard()
        with guard.lease(self.home, expected_sha256=self.binding["guard_sha256"], mode="exclusive"):
            self.assertIn("busy", self.invoke("doctor", expected=1).stderr)
            self.assertFalse(self.marker.exists())
        self.assertTrue(json.loads(self.invoke("doctor").stdout)["shared_before_import"])

    def test_shared_lease_remains_held_through_runtime_main(self):
        child = subprocess.Popen([sys.executable, "-B", "-u", str(self.launcher), "doctor"],
                                 cwd=self.base, env=self.environment("hold"), stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.children.append(child)
        import select
        self.assertTrue(select.select([child.stdout], [], [], 5)[0])
        ready = json.loads(child.stdout.readline())
        self.assertTrue(ready["shared_before_import"])
        guard = self.load_guard()
        with self.assertRaisesRegex(ValueError, "busy"):
            with guard.lease(self.home, expected_sha256=self.binding["guard_sha256"], mode="exclusive"):
                self.fail("Live entry must retain its lease")
        _output, error = child.communicate("x", timeout=5)
        self.assertEqual(child.returncode, 0, error)
        with guard.lease(self.home, expected_sha256=self.binding["guard_sha256"], mode="exclusive"):
            pass

    def test_child_retains_explicit_descriptor_after_actual_parent_exit(self):
        parent = json.loads(self.invoke("doctor", mode="spawn").stdout)
        child = json.loads(self.child_ready.read_text())
        self.assertEqual(parent["child_pid"], child["pid"])
        self.assertEqual(child["inode"], (self.home / "state/home-lifecycle.lock").stat().st_ino)
        guard = self.load_guard()
        with self.assertRaisesRegex(ValueError, "busy"):
            with guard.lease(self.home, expected_sha256=self.binding["guard_sha256"], mode="exclusive"):
                self.fail("Inherited child must retain the kernel lease")
        self.child_release.touch()
        deadline = time.monotonic() + 5
        while True:
            try:
                with guard.lease(self.home, expected_sha256=self.binding["guard_sha256"], mode="exclusive"):
                    break
            except guard.LeaseBusy:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.01)

    def test_descriptor_api_rejects_missing_foreign_or_standard_stream_handles(self):
        guard = self.load_guard()
        with guard.lease(self.home, expected_sha256=self.binding["guard_sha256"]) as held:
            self.assertEqual(home_entry.inherited_pass_fds(self.home, environ={home_entry.FD_ENV: str(held.fd)}), (held.fd,))
            foreign = self.base / "foreign-file"
            with foreign.open("wb") as stream:
                with self.assertRaisesRegex(ValueError, "does not name"):
                    home_entry.inherited_pass_fds(self.home, environ={home_entry.FD_ENV: str(stream.fileno())})
            for env in ({}, {home_entry.FD_ENV: "invalid"}, {home_entry.FD_ENV: "1"}):
                with self.assertRaises(ValueError):
                    home_entry.inherited_pass_fds(self.home, environ=env)
            self.assertEqual(home_entry.inherited_pass_fds(self.home, environ={}, required=False), ())

    def test_symlink_entry_or_guard_refuses_before_runtime_import(self):
        alias = self.base / "launcher alias.py"
        alias.symlink_to(self.launcher)
        result = subprocess.run([sys.executable, "-B", str(alias), "doctor"], env=self.environment(),
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.marker.exists())
        guard = self.home / "home-lifecycle.py"
        saved = self.base / "saved-guard.py"
        guard.rename(saved)
        guard.symlink_to(saved)
        self.assertIn("regular unique file", self.invoke("doctor", expected=1).stderr)
        self.assertFalse(self.marker.exists())


@unittest.skipIf(sys.platform == "linux", "Actual non-Linux inspection qualification")
class InspectionEntryTests(EntryFixture):
    def test_actual_windows_inspection_dispatch_has_no_lease_or_stale_handle(self):
        environment = self.environment()
        environment[home_entry.FD_ENV] = "1234"
        result = json.loads(self.invoke("doctor", environment=environment).stdout)
        self.assertIsNone(result["fd_env"])
        self.assertIsNone(result["shared_before_import"])
        self.assertFalse((self.home / "state/home-lifecycle.lock").exists())
        self.assertEqual(home_entry.inherited_pass_fds(self.home, environ={home_entry.FD_ENV: "invalid"}), ())


if __name__ == "__main__":
    unittest.main()
