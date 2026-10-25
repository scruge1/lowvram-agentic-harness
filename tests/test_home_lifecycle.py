"""Real-process qualification of the stable Linux home guard; no runtime/model."""
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


SOURCE = Path(__file__).resolve().parents[1] / "harness/home_lifecycle.py"
PIN = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
LOADER = """
import importlib.util,json,sys
from pathlib import Path
home=Path(sys.argv[1]); pin=sys.argv[2]
spec=importlib.util.spec_from_file_location('installed_home_guard',home/'home-lifecycle.py')
guard=importlib.util.module_from_spec(spec); spec.loader.exec_module(guard)
try:
    with guard.lease(home,expected_sha256=pin,mode=sys.argv[3],recover=sys.argv[4]=='yes') as held:
        print(json.dumps({'ready':True,'pid':__import__('os').getpid(),'fd':held.fd,
                          'inheritable':__import__('os').get_inheritable(held.fd),
                          'pending':str(held.pending_journal) if held.pending_journal else None}),flush=True)
        if sys.argv[5]=='hold': sys.stdin.buffer.read(1)
except (OSError,ValueError) as error:
    print(str(error),file=sys.stderr);raise SystemExit(1)
"""
FD_CHILD = """
import json,os,sys
fd=int(sys.argv[1]) if len(sys.argv)>1 else int(os.environ['AGENT_HOME_LIFECYCLE_FD'])
print(json.dumps({'ready':True,'pid':os.getpid(),'fd':fd,'inode':os.fstat(fd).st_ino,
                  'inheritable':os.get_inheritable(fd),'args':sys.argv[2:]}),flush=True)
sys.stdin.buffer.read(1)
"""


class Fixture(unittest.TestCase):
    def setUp(self):
        selected = os.environ.get("LIFECYCLE_TEST_ROOT")
        if not selected and os.name == "nt" and Path("E:/").is_dir():
            selected = "E:/"
        self.temporary = tempfile.TemporaryDirectory(prefix="harness-lifecycle-", dir=selected)
        self.base = Path(self.temporary.name).resolve()
        self.parent = self.base.parent
        self.home = self.base / "agent home ü"
        self.home.mkdir()
        (self.home / "state").mkdir()
        self.guard_file = self.home / "home-lifecycle.py"
        shutil.copyfile(SOURCE, self.guard_file)
        self.config = {"schema": "agent-home/v1", "home": str(self.home), "lifecycle_guard_sha256": PIN}
        self.write_config()
        self.children = []
        self.addCleanup(self.clean_fixture)

    def write_config(self):
        (self.home / "home.json").write_text(json.dumps(self.config), encoding="utf-8")

    def clean_fixture(self):
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
        self.assertEqual(self.base.parent, self.parent)
        self.assertEqual(self.base.resolve(), self.base)
        self.assertTrue(self.base.name.startswith("harness-lifecycle-"))
        self.temporary.cleanup()

    def command(self, *, home=None, pin=PIN, mode="shared", recover=False, hold=False):
        return [sys.executable, "-B", "-u", "-c", LOADER, str(home or self.home), pin,
                mode, "yes" if recover else "no", "hold" if hold else "probe"]

    def probe(self, *, expected=0, **kwargs):
        result = subprocess.run(self.command(**kwargs), capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, expected, result.stderr)
        return result

    def hold(self, **kwargs):
        child = subprocess.Popen(self.command(hold=True, **kwargs), stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.children.append(child)
        return child, self.ready(child)

    def ready(self, child):
        # Linux pipe readiness bounds a broken child protocol without sleeping.
        import select
        self.assertTrue(select.select([child.stdout], [], [], 5)[0], "Child did not report readiness")
        line = child.stdout.readline()
        if not line:
            self.fail("Child exited before readiness: " + child.stderr.read())
        value = json.loads(line)
        self.assertTrue(value["ready"])
        self.assertEqual(value["pid"], child.pid)
        return value

    def release(self, child):
        output, error = child.communicate("x", timeout=5)
        self.assertEqual(child.returncode, 0, error + output)

    def load_guard(self):
        self.assertEqual(hashlib.sha256(self.guard_file.read_bytes()).hexdigest(), PIN)
        spec = importlib.util.spec_from_file_location("fixture_home_guard", self.guard_file)
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        return guard


@unittest.skipUnless(sys.platform == "linux", "Linux flock lifetime controls")
class LinuxLifecycleTests(Fixture):
    def test_concurrent_shared_consumers_and_nonblocking_exclusive_refusal(self):
        first, one = self.hold()
        second, two = self.hold()
        self.assertFalse(one["inheritable"])
        self.assertFalse(two["inheritable"])
        start = time.monotonic()
        self.assertIn("busy", self.probe(mode="exclusive", expected=1).stderr)
        self.assertLess(time.monotonic() - start, 2)
        self.release(first)
        self.probe(mode="exclusive", expected=1)
        self.release(second)
        self.probe(mode="exclusive")

    def test_exclusive_owner_blocks_both_modes_until_release(self):
        child, _ready = self.hold(mode="exclusive")
        self.assertIn("busy", self.probe(expected=1).stderr)
        self.assertIn("busy", self.probe(mode="exclusive", expected=1).stderr)
        self.release(child)
        self.probe()

    def test_crash_releases_kernel_lease_without_deleting_lock(self):
        child, _ready = self.hold()
        lock = self.home / "state/home-lifecycle.lock"
        inode = lock.stat().st_ino
        child.kill()
        child.wait(timeout=5)
        self.probe(mode="exclusive")
        self.assertEqual(lock.stat().st_ino, inode)
        self.assertEqual(lock.read_bytes(), b"")

    def test_pending_journal_blocks_normal_entry_and_exclusive_owner_can_recover(self):
        updates = self.home / "state/updates"
        updates.mkdir()
        journal = updates / "pending-activation.json"
        raw = b"{partial journal retained for explicit recovery"
        journal.write_bytes(raw)
        self.assertIn("Pending activation", self.probe(expected=1).stderr)
        self.assertIn("Pending activation", self.probe(mode="exclusive", expected=1).stderr)
        child, ready = self.hold(mode="exclusive", recover=True)
        self.assertEqual(ready["pending"], str(journal))
        self.probe(expected=1)
        self.release(child)
        self.assertEqual(journal.read_bytes(), raw)
        self.probe(expected=1)
        journal.unlink()  # The fixture explicitly completes recovery, not the guard.
        self.probe()

    def test_journal_created_under_exclusive_lease_is_seen_after_release(self):
        guard = self.load_guard()
        with guard.lease(self.home, expected_sha256=PIN, mode="exclusive"):
            (self.home / "state/updates").mkdir()
            (self.home / guard.PENDING).write_text("{}")
            self.probe(expected=1)
        self.assertIn("Pending activation", self.probe(expected=1).stderr)

    def test_exception_and_explicit_close_release_only_owned_descriptor(self):
        guard = self.load_guard()
        with self.assertRaisesRegex(RuntimeError, "fixture exception"):
            with guard.lease(self.home, expected_sha256=PIN) as held:
                descriptor = held.fd
                self.probe(mode="exclusive", expected=1)
                raise RuntimeError("fixture exception")
        with self.assertRaises(OSError):
            os.fstat(descriptor)
        held.close()
        with self.assertRaisesRegex(ValueError, "closed"):
            _unused = held.pass_fds
        self.probe(mode="exclusive")

    def test_explicit_pass_fds_child_retains_lease_after_parent_context_closes(self):
        guard = self.load_guard()
        with guard.lease(self.home, expected_sha256=PIN) as held:
            child = subprocess.Popen([sys.executable, "-B", "-u", "-c", FD_CHILD, str(held.fd)],
                                     pass_fds=held.pass_fds, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.children.append(child)
            ready = self.ready(child)
            self.assertEqual(ready["inode"], os.fstat(held.fd).st_ino)
            self.assertTrue(ready["inheritable"])
        self.probe(mode="exclusive", expected=1)
        self.release(child)
        self.probe(mode="exclusive")

    def test_unpassed_descriptor_does_not_claim_descendant_coverage(self):
        guard = self.load_guard()
        program = "import json,os,sys;print(json.dumps({'ready':True,'pid':os.getpid()}),flush=True);sys.stdin.buffer.read(1)"
        with guard.lease(self.home, expected_sha256=PIN):
            child = subprocess.Popen([sys.executable, "-B", "-u", "-c", program], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.children.append(child)
            self.ready(child)
        self.assertIsNone(child.poll())
        self.probe(mode="exclusive")
        self.release(child)

    def test_exec_cli_preserves_pid_argv_and_lease_for_direct_command(self):
        literal = "spaces ü ; $(touch must-not-exist)"
        argv = [sys.executable, "-B", str(self.guard_file), "--home", str(self.home),
                "--expected-sha256", PIN, "--", sys.executable, "-B", "-u", "-c", FD_CHILD]
        # FD_CHILD uses the CLI environment handle when no explicit fd argument.
        program = FD_CHILD.replace("fd=int(sys.argv[1]) if len(sys.argv)>1 else int(os.environ['AGENT_HOME_LIFECYCLE_FD'])",
                                   "fd=int(os.environ['AGENT_HOME_LIFECYCLE_FD'])").replace("'args':sys.argv[2:]", "'args':sys.argv[1:]")
        argv[-1] = program
        child = subprocess.Popen([*argv, literal], cwd=self.base, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.children.append(child)
        ready = self.ready(child)
        self.assertEqual(ready["args"], [literal])
        self.assertTrue(ready["inheritable"])
        self.probe(mode="exclusive", expected=1)
        self.release(child)
        self.probe(mode="exclusive")
        self.assertFalse((self.base / "must-not-exist").exists())

    def test_pending_cli_does_not_execute_command_or_clear_journal(self):
        updates = self.home / "state/updates"
        updates.mkdir()
        journal = updates / "pending-activation.json"
        journal.write_text("retained")
        marker = self.base / "command-was-run"
        argv = [sys.executable, "-B", str(self.guard_file), "--home", str(self.home), "--expected-sha256", PIN,
                "--", sys.executable, "-B", "-c", "from pathlib import Path;Path(" + repr(str(marker)) + ").touch()"]
        result = subprocess.run(argv, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Pending activation", result.stderr)
        self.assertFalse(marker.exists())
        self.assertEqual(journal.read_text(), "retained")

    def test_wrong_home_pin_and_unintegrated_home_refuse_before_lock(self):
        self.config["home"] = str(self.base)
        self.write_config()
        self.assertIn("identity differs", self.probe(expected=1).stderr)
        self.config["home"] = str(self.home)
        self.config.pop("lifecycle_guard_sha256")
        self.write_config()
        self.assertIn("old homes", self.probe(expected=1).stderr)
        self.assertFalse((self.home / "state/home-lifecycle.lock").exists())
        self.assertIn("exact stable", self.probe(pin="0" * 64, expected=1).stderr)

    def test_wrong_guard_location_and_post_load_source_drift_refuse(self):
        other = self.base / "other-guard.py"
        shutil.copyfile(self.guard_file, other)
        result = subprocess.run([sys.executable, "-B", str(other), "--home", str(self.home), "--expected-sha256", PIN,
                                 "--", sys.executable, "-c", "raise SystemExit(99)"], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn("exact stable", result.stderr)
        guard = self.load_guard()
        self.guard_file.write_bytes(self.guard_file.read_bytes() + b"\n# synthetic drift\n")
        with self.assertRaisesRegex(ValueError, "exact stable"):
            with guard.lease(self.home, expected_sha256=PIN):
                self.fail("Drift must not acquire")
        self.assertFalse((self.home / "state/home-lifecycle.lock").exists())

    def test_symlink_home_state_config_guard_lock_and_journal_refuse(self):
        alias = self.base / "home alias"
        alias.symlink_to(self.home, target_is_directory=True)
        self.assertIn("symlink", self.probe(home=alias, expected=1).stderr)
        for relative in ("home.json", "home-lifecycle.py", "state"):
            original = self.home / relative
            saved = self.base / (relative.replace("/", "-") + ".saved")
            original.rename(saved)
            original.symlink_to(saved, target_is_directory=saved.is_dir())
            self.assertIn("symlink", self.probe(expected=1).stderr)
            original.unlink()
            saved.rename(original)
        external = self.base / "external-lock"
        external.write_bytes(b"retained")
        lock = self.home / "state/home-lifecycle.lock"
        lock.symlink_to(external)
        self.assertIn("symlink", self.probe(expected=1).stderr)
        self.assertEqual(external.read_bytes(), b"retained")
        lock.unlink()
        updates = self.home / "state/updates"
        updates.mkdir()
        (updates / "pending-activation.json").symlink_to(external)
        self.assertIn("symlink", self.probe(mode="exclusive", recover=True, expected=1).stderr)
        self.assertEqual(external.read_bytes(), b"retained")

    def test_hardlinked_lock_is_not_modified_or_admitted(self):
        external = self.base / "external-lock"
        external.write_bytes(b"retained")
        os.link(external, self.home / "state/home-lifecycle.lock")
        self.assertIn("multiple links", self.probe(expected=1).stderr)
        self.assertEqual(external.read_bytes(), b"retained")

    def test_invalid_modes_and_shared_recovery_are_refused(self):
        guard = self.load_guard()
        for arguments in ({"mode": "other"}, {"recover": True}):
            with self.assertRaises(ValueError):
                with guard.lease(self.home, expected_sha256=PIN, **arguments):
                    self.fail("Invalid lease request admitted")
        self.assertFalse((self.home / "state/home-lifecycle.lock").exists())


@unittest.skipIf(sys.platform == "linux", "Actual unsupported-platform qualification")
class UnsupportedLifecycleTests(Fixture):
    def test_actual_platform_refuses_before_state_or_command_mutation(self):
        marker = self.base / "unexpected"
        result = subprocess.run([sys.executable, "-B", str(self.guard_file), "--home", str(self.home),
                                 "--expected-sha256", PIN, "--", sys.executable, "-c",
                                 "from pathlib import Path;Path(" + repr(str(marker)) + ").touch()"],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn("require Linux", result.stderr)
        self.assertFalse(marker.exists())
        self.assertEqual(list((self.home / "state").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
