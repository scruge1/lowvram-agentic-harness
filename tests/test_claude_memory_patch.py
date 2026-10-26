"""Synthetic package staging and entry controls. No worker or model import."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from harness import claude_memory, claude_memory_patch as cm, home, home_entry


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve() / "home"
        self.home.mkdir()
        (self.home / "home.json").write_text(json.dumps({"schema": "agent-home/v1", "home": str(self.home)}))
        self.prefix = self.home / "packages/claude-mem"
        self.worker = self.prefix / cm.WORKER
        self.worker.parent.mkdir(parents=True)
        (self.prefix / "node_modules/claude-mem/package.json").write_text('{"version":"13.29.0"}')
        (self.prefix / "package-lock.json").write_text('{"synthetic":true}')
        before = b'"use strict";'
        old = b'async function $5(t={}){for(const row of await t.readTable()){if(row.orphan)await t.killTree(row.pid)}return{skipped:null}}'
        after = b'var retained=true;/*! Bundled license information:\n synthetic fixture licence */'
        self.original = before + old + after
        self.policy = copy.deepcopy(cm.manifest())
        replacement = self.policy["replacement"].encode()
        effective = before + replacement + after
        self.policy.update(upstream_sha256=cm.digest(self.original), upstream_bytes=len(self.original),
                           start_byte=len(before), end_byte_exclusive=len(before)+len(old), span_sha256=cm.digest(old),
                           effective_sha256=cm.digest(effective), effective_bytes=len(effective))
        self.worker.write_bytes(self.original)
        self.patcher = patch.object(cm, "manifest", return_value=self.policy)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_stage_retains_original_and_licence_with_distinct_explicit_provenance(self):
        receipt = cm.stage(self.home)
        self.assertEqual(cm.verify(self.home), receipt)
        original = self.prefix / cm.PATCH_DIRECTORY / "upstream-worker-service.cjs"
        self.assertEqual(original.read_bytes(), self.original)
        self.assertNotEqual(self.worker.read_bytes(), self.original)
        self.assertTrue(self.worker.read_bytes().endswith(self.original[self.original.index(b'/*!'):]))
        self.assertNotEqual(receipt["upstream_sha256"], receipt["effective_sha256"])
        self.assertEqual(receipt["patch_id"], "disable-global-orphan-sweep-v1")
        self.assertIn("not upstream-unmodified", receipt["scope"])
        files = cm.artifacts(self.home)
        before = {p: p.read_bytes() for p in files}
        self.assertEqual(cm.stage(self.home), receipt)
        self.assertEqual({p: p.read_bytes() for p in files}, before)

    def test_unknown_upstream_span_replacement_and_effective_hash_refuse_before_writes(self):
        for key in ("upstream_sha256", "span_sha256", "replacement_sha256", "effective_sha256"):
            with self.subTest(key=key):
                previous = self.policy[key]
                self.policy[key] = "0" * 64
                with self.assertRaises(cm.PatchError):
                    cm.stage(self.home)
                self.policy[key] = previous
                self.assertEqual(self.worker.read_bytes(), self.original)
                self.assertFalse((self.prefix / cm.PATCH_DIRECTORY).exists())

    def test_multiple_span_or_missing_licence_is_not_a_refresh(self):
        start, end = self.policy["start_byte"], self.policy["end_byte_exclusive"]
        doubled = self.original + self.original[start:end]
        self.policy.update(upstream_sha256=cm.digest(doubled), upstream_bytes=len(doubled))
        self.worker.write_bytes(doubled)
        with self.assertRaisesRegex(cm.PatchError, "ambiguous"):
            cm.stage(self.home)
        self.assertFalse((self.prefix / cm.PATCH_DIRECTORY).exists())
        missing = self.original.replace(b'/*! Bundled license information:', b'no licence marker')
        self.policy.update(upstream_sha256=cm.digest(missing), upstream_bytes=len(missing))
        self.worker.write_bytes(missing)
        with self.assertRaisesRegex(cm.PatchError, "licence"):
            cm.stage(self.home)

    def test_inventory_refuses_unpatched_then_tracks_original_effective_and_receipt(self):
        with self.assertRaises((cm.PatchError, OSError)):
            home.package_artifacts(self.home, "claude-mem")
        cm.stage(self.home)
        artifacts = home.package_artifacts(self.home, "claude-mem")
        record = {"artifacts": artifacts}
        self.assertIsNone(home.check_package(self.home, "claude-mem", record))
        expected = {str(path) for path in cm.artifacts(self.home)}
        self.assertTrue(expected.issubset({row["path"] for row in artifacts}))
        self.worker.write_bytes(self.worker.read_bytes() + b"altered")
        # Even a caller that recomputes the generic file hashes cannot bypass provenance.
        for row in record["artifacts"]:
            row["sha256"] = cm.digest(Path(row["path"]).read_bytes())
        self.assertIn("patch verification failed", home.check_package(self.home, "claude-mem", record))

    def test_altered_original_receipt_or_missing_provenance_never_pass_entry(self):
        cm.stage(self.home)
        files = cm.artifacts(self.home)
        for path in files[1:]:
            previous = path.read_bytes()
            path.write_bytes(previous + b"altered")
            with self.assertRaises((ValueError, OSError)):
                cm.verify(self.home)
            path.write_bytes(previous)
        receipt = files[-1]
        receipt.unlink()
        with self.assertRaises(OSError):
            cm.stage(self.home)  # An effective file alone cannot invent a receipt.

    def test_concurrent_effective_publication_keeps_recoverable_original(self):
        real = cm._publish

        def drift(path, raw, **kwargs):
            if path == self.worker:
                self.worker.write_bytes(self.original + b"foreign change")
            return real(path, raw, **kwargs)

        with patch.object(cm, "_publish", side_effect=drift), self.assertRaisesRegex(cm.PatchError, "Concurrent"):
            cm.stage(self.home)
        original = self.prefix / cm.PATCH_DIRECTORY / "upstream-worker-service.cjs"
        self.assertEqual(original.read_bytes(), self.original)
        self.assertEqual(self.worker.read_bytes(), self.original + b"foreign change")
        with self.assertRaises(cm.PatchError):
            cm.verify(self.home)

    def test_original_and_receipt_directory_entries_are_synced_before_effective_exchange(self):
        events = []
        original_sync = cm._fsync_directory
        original_replace = cm.os.replace

        def sync(path):
            events.append(("sync", path))
            return original_sync(path)

        def replace(candidate, path):
            events.append(("replace", path))
            return original_replace(candidate, path)

        with patch.object(cm, "_fsync_directory", side_effect=sync), patch.object(cm.os, "replace", side_effect=replace):
            cm.stage(self.home)
        exchange = events.index(("replace", self.worker))
        package_state = self.prefix / cm.PATCH_DIRECTORY
        self.assertGreaterEqual(events[:exchange].count(("sync", package_state)), 2)
        self.assertIn(("sync", self.worker.parent), events[exchange+1:])

    def test_linked_worker_cannot_mutate_a_donor_inode(self):
        donor = self.prefix / "donor.cjs"
        os.link(self.worker, donor)
        with self.assertRaisesRegex(cm.PatchError, "one link"):
            cm.stage(self.home)
        self.assertEqual(donor.read_bytes(), self.original)
        self.assertFalse((self.prefix / cm.PATCH_DIRECTORY).exists())

    def test_existing_worker_identity_blocks_first_patch_without_signal_or_metadata_removal(self):
        root = self.home / "memory/claude-mem"
        root.mkdir(parents=True)
        identity = root / "worker.pid"
        raw = json.dumps({"pid": os.getpid(), "port": 12345}).encode()
        identity.write_bytes(raw)
        with self.assertRaisesRegex(cm.PatchError, "existing observer identity"):
            cm.stage(self.home)
        self.assertEqual(identity.read_bytes(), raw)
        self.assertEqual(self.worker.read_bytes(), self.original)
        self.assertFalse((self.prefix / cm.PATCH_DIRECTORY).exists())

    def test_any_persisted_registry_entry_holds_before_pidfd_spawn_or_signal(self):
        root = self.home / "memory/claude-mem"
        root.mkdir(parents=True)
        path = root / "supervisor.json"
        for processes in ({"dead": {"pid": 99999999}}, {"live": {"pid": os.getpid()}}, {"unknown": {}}):
            raw = json.dumps({"processes": processes}).encode()
            path.write_bytes(raw)
            with patch.object(claude_memory.subprocess, "Popen") as spawn, \
                    patch.object(claude_memory.model_service, "_pidfd") as pidfd:
                with self.assertRaisesRegex(cm.PatchError, "Persisted"):
                    claude_memory.foreground_start(self.home, root, {}, Path("bun"), self.worker, {})
            spawn.assert_not_called()
            pidfd.assert_not_called()
            self.assertEqual(path.read_bytes(), raw)

    def test_empty_registry_is_allowed_unknown_format_is_retained(self):
        root = self.home / "memory/claude-mem"
        root.mkdir(parents=True)
        cm.require_empty_registry(root)
        path = root / "supervisor.json"
        path.write_text('{"processes":{}}')
        cm.require_empty_registry(root)
        for raw in ('{}', '{"processes":[]}', '{"processes":null}', 'bad-json'):
            path.write_text(raw)
            with self.assertRaises(ValueError):
                cm.require_empty_registry(root)
            self.assertEqual(path.read_text(), raw)

    def test_worker_entry_requires_provenance_before_returning_native_paths(self):
        config = {"installed": {"bun": {"npm_name": "@oven/bun-linux-x64"}, "claude-mem": {"npm_name": "claude-mem"}}}
        bun = self.home / "packages/bun/node_modules/@oven/bun-linux-x64"
        (bun / "bin").mkdir(parents=True)
        (bun / "bin/bun").write_bytes(b"synthetic native path only")
        (bun / "package.json").write_text('{"bin":{"bun":"bin/bun"}}')
        with patch.object(claude_memory, "load", return_value=(self.home, config)), \
                patch.object(claude_memory, "check_package", return_value=None):
            with self.assertRaises(OSError):
                claude_memory.worker_paths(self.home)
            cm.stage(self.home)
            actual_bun, actual_worker = claude_memory.worker_paths(self.home)
        self.assertEqual(actual_bun, bun / "bin/bun")
        self.assertEqual(actual_worker, self.worker)

    @unittest.skipUnless(shutil.which("node"), "Node is needed only for the isolated JS function control")
    def test_isolated_function_stops_unscoped_reads_and_signals_with_predecessor_control(self):
        start, end = self.policy["start_byte"], self.policy["end_byte_exclusive"]
        script = """const fs=require('node:fs'),vm=require('node:vm');
const p=JSON.parse(fs.readFileSync(0,'utf8'));
async function exercise(source){
 let reads=0,killed=[];
 const fn=vm.runInNewContext('('+source+')');
 const result=await fn({readTable:async()=>{reads++;return [{pid:99123,orphan:true},{pid:99124,orphan:false}];},
                       killTree:async pid=>{killed.push(pid);}});
 return {reads,killed,result};
}
(async()=>console.log(JSON.stringify({old:await exercise(p.old),patched:await exercise(p.patched)})))()
 .catch(()=>process.exit(1));"""
        result = subprocess.run([shutil.which("node"), "-e", script],
                                input=json.dumps({"old": self.original[start:end].decode(), "patched": self.policy["replacement"]}),
                                text=True, capture_output=True, timeout=5, check=True)
        observed = json.loads(result.stdout)
        self.assertEqual((observed["old"]["reads"], observed["old"]["killed"]), (1, [99123]))
        self.assertEqual((observed["patched"]["reads"], observed["patched"]["killed"]), (0, []))
        self.assertEqual(observed["patched"]["result"]["skipped"], "agent_home_unscoped_cleanup_disabled")


@unittest.skipUnless(os.name == "posix" and Path("/proc/self/fdinfo").is_dir(), "Native home lease controls require Linux")
class InstallerLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "home"
        self.config = home.scaffold(self.root, profile="full", base_url="http://127.0.0.1:9/v1", model="fixture", offline=True)

    def modes(self):
        lock = str(self.root / "state/home-lifecycle.lock")
        modes = []
        for descriptor in Path("/proc/self/fd").iterdir():
            try:
                if os.readlink(descriptor) == lock:
                    modes.extend(line for line in (Path("/proc/self/fdinfo") / descriptor.name).read_text().splitlines() if line.startswith("lock:"))
            except FileNotFoundError:
                pass
        return " ".join(modes)

    def test_new_full_source_installer_observes_shared_exclusive_shared_phases(self):
        phases = []

        def loop(root, config, python312, **kwargs):
            phases.append((kwargs.get("only"), self.modes(), kwargs.get("finalize", True)))
            if kwargs.get("only") in {("hermes",), ("claude-mem",)}:
                fds = kwargs["lifecycle_fds"]
                self.assertTrue(fds)
                self.assertEqual(kwargs["lifecycle_lease"].mode, "exclusive")
                # The existing command runner really passes the same EX lease.
                code = "import pathlib;print(pathlib.Path('/proc/self/fdinfo/" + str(fds[0]) + "').read_text())"
                result = home.run([os.sys.executable, "-c", code], cwd=root, pass_fds=fds)
                self.assertIn("FLOCK ADVISORY WRITE", " ".join(result.split()))

        with patch.object(home, "_install_packages", side_effect=loop):
            home.install_packages(self.root, self.config)
        self.assertEqual(len(phases), 6)
        self.assertNotIn("claude-mem", phases[0][0])
        self.assertIn("READ", phases[0][1])
        self.assertEqual(phases[1][0], ("hermes",))
        self.assertIn("WRITE", phases[1][1])
        self.assertIn("READ", phases[2][1])
        self.assertEqual(phases[3][0], ("claude-mem",))
        self.assertIn("WRITE", phases[3][1])
        self.assertIn("READ", phases[4][1])
        self.assertIn("READ", phases[5][1])
        self.assertTrue(phases[5][2])
        with home._observer_install_exclusive(self.root):
            self.assertIn("WRITE", self.modes())

    def test_installed_outer_read_refuses_exclusive_without_upgrading_or_replaying(self):
        calls = []
        with home_entry.consumer(self.root), patch.object(home, "_install_packages", side_effect=lambda *a, **k: calls.append(k)):
            with self.assertRaisesRegex(home.HomeError, "retained reviewed source controller directly") as caught:
                home.install_packages(self.root, self.config)
            self.assertIn(str(Path(home.__file__).resolve()), str(caught.exception))
            self.assertIn("resume-install", str(caught.exception))
            self.assertIn("READ", self.modes())
        self.assertEqual(calls, [])

    def test_partial_package_failure_retains_prior_records_and_skips_final_binding(self):
        calls = []

        def loop(root, config, python312, **kwargs):
            calls.append(kwargs.get("only"))
            if kwargs.get("only") == ("claude-mem",):
                raise home.HomeError("synthetic npm/patch failure")
            config["installed"]["pi"] = {"acceptance": "synthetic partial fixture only"}

        with patch.object(home, "_install_packages", side_effect=loop), self.assertRaisesRegex(home.HomeError, "synthetic"):
            home.install_packages(self.root, self.config)
        self.assertEqual(len(calls), 4)
        self.assertIn("pi", self.config["installed"])
        self.assertNotIn("claude-mem", self.config["installed"])
        with home._observer_install_exclusive(self.root):
            self.assertIn("WRITE", self.modes())


if __name__ == "__main__":
    unittest.main()
