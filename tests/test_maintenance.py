"""Owned source-stage controls; no activation, install, service or model."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from harness import home as bootstrap
from harness import maintenance


REPO = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(shutil.which("git"), "The existing source scaffold requires Git")
class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        selected = os.environ.get("MAINTENANCE_TEST_ROOT")
        if not selected and os.name == "nt" and Path("E:/").is_dir():
            selected = "E:/"
        self.temporary = tempfile.TemporaryDirectory(prefix="harness-maintenance-", dir=selected)
        self.base = Path(self.temporary.name).resolve()
        self.parent = self.base.parent
        self.addCleanup(self.clean_fixture)
        self.source = self.base / "source"
        for name in ("harness", "ssot", "adapters/pi"):
            for path in (REPO / name).rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts and (
                        path.suffix in {".py", ".ts", ".mjs", ".md"}
                        or "templates" in path.parts):
                    target = self.source / path.relative_to(REPO)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
        self.home = self.base / "agent home"
        bootstrap.scaffold(self.home, source=self.source, profile="core",
                           base_url="http://127.0.0.1:9/v1", model="synthetic-fixture", offline=True)
        self.protected = []
        for name in ("agent/auth.json", "agent/sessions/original.jsonl", "context/current.md",
                     "memory/palace/retained.bin", "state/projects/board.sqlite", "state/hermes/keep.bin",
                     "packages/retained-cache.bin", "cache/retained.bin", "envs/retained.bin"):
            target = self.home / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(("synthetic preserved content: " + name).encode())
            self.protected.append(target)
        self.before = {str(path): digest(path) for path in self.protected}
        self.active = maintenance.active_snapshot(self.home)[2]
        self.execution_marker = self.base / "candidate-was-executed"
        (self.source / "harness/candidate.py").write_text(
            "from pathlib import Path\nPath(" + repr(str(self.execution_marker)) + ").write_text('unexpected')\n",
            encoding="utf-8")

    def clean_fixture(self):
        # Resolve and check the exact owned deletion target before cleanup.
        self.assertEqual(self.base.parent, self.parent)
        self.assertTrue(self.base.name.startswith("harness-maintenance-"))
        self.temporary.cleanup()

    def protected_unchanged(self):
        self.assertEqual({str(path): digest(path) for path in self.protected}, self.before)
        self.assertEqual(maintenance.active_snapshot(self.home)[2], self.active)

    def staged(self, operation="source-a"):
        plan = maintenance.plan(self.home, self.source)
        self.assertEqual(plan["local_closure"]["errors"], [])
        return maintenance.stage(self.home, self.source, operation, plan["plan_sha256"])

    def test_read_only_plan_contains_source_pin_and_artifact_closure(self):
        first = maintenance.plan(self.home, self.source)
        second = maintenance.plan(self.home, self.source)
        self.assertEqual(first, second)
        self.assertIn("harness/candidate.py", first["diff"]["added"])
        self.assertIn("adapters/pi/project-workflow/kanban-reply-projector.mjs", first["source_files"])
        self.assertIn("harness/templates/agent-home/gitignore.template", first["source_files"])
        self.assertIn("pi-task-worker.py", first["source_files"])
        self.assertIn("framework", first["pins"])
        self.assertEqual(first["candidate_runtime_acceptance"], "not_run")
        self.assertIn("pending", first["package_qualification"])
        self.assertFalse((self.home / "state/updates").exists())
        self.assertFalse(self.execution_marker.exists())
        self.protected_unchanged()

    def test_stage_complete_candidate_and_predecessor_without_activation(self):
        staged = self.staged()
        self.assertEqual(staged["status"], "staged_not_active")
        root = Path(staged["receipt"]).parent
        candidate = root / "candidate/runtime"
        binding = json.loads((candidate / "adapters/pi/project-workflow/everyday-runtime.json").read_text())
        self.assertEqual(binding["runtime"], str(candidate))
        self.assertNotEqual(binding["runtime"], str(self.home / "runtime"))
        self.assertEqual(binding["runtime_manifest_sha256"], digest(candidate / "runtime-manifest.json"))
        self.assertEqual((root / "predecessor/home.json").read_bytes(), (self.home / "home.json").read_bytes())
        self.assertEqual((candidate / "harness/candidate.py").read_bytes(), (self.source / "harness/candidate.py").read_bytes())
        self.assertTrue(maintenance.verify_stage(self.home, "source-a")["valid_staged_source"])
        self.assertFalse(self.execution_marker.exists())
        self.protected_unchanged()

    def test_withdraw_retains_both_generations_and_timestamped_receipt(self):
        staged = self.staged()
        previous = Path(staged["receipt"]).read_bytes()
        candidate = Path(staged["receipt"]).parent / "candidate/runtime"
        before = {str(p): digest(p) for p in candidate.rglob("*") if p.is_file()}
        retired = maintenance.withdraw(self.home, "source-a", staged["receipt_sha256"])
        self.assertEqual(retired["status"], "withdrawn_not_active")
        self.assertEqual(Path(retired["previous_receipt"]).read_bytes(), previous)
        self.assertEqual({str(p): digest(p) for p in candidate.rglob("*") if p.is_file()}, before)
        self.assertFalse(maintenance.verify_stage(self.home, "source-a")["valid_staged_source"])
        self.assertEqual(maintenance.pending_operations(self.home), [])
        self.protected_unchanged()

    def test_replay_and_pending_generation_are_refused(self):
        staged = self.staged()
        with self.assertRaisesRegex(ValueError, "pending"):
            self.staged("source-b")
        maintenance.withdraw(self.home, "source-a", staged["receipt_sha256"])
        plan = maintenance.plan(self.home, self.source)
        with self.assertRaisesRegex(ValueError, "replay"):
            maintenance.stage(self.home, self.source, "source-a", plan["plan_sha256"])
        self.protected_unchanged()

    def test_source_change_after_reviewed_plan_refuses_without_operation(self):
        selected = maintenance.plan(self.home, self.source)
        (self.source / "harness/candidate.py").write_text("CHANGED = True\n")
        with self.assertRaisesRegex(ValueError, "drift"):
            maintenance.stage(self.home, self.source, "source-a", selected["plan_sha256"])
        self.assertFalse((self.home / "state/updates/source-a").exists())
        self.protected_unchanged()

    def test_active_configuration_change_after_plan_refuses(self):
        selected = maintenance.plan(self.home, self.source)
        config = json.loads((self.home / "home.json").read_text())
        config["name"] = "Changed by an independent fixture owner"
        (self.home / "home.json").write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError, "drift"):
            maintenance.stage(self.home, self.source, "source-a", selected["plan_sha256"])
        self.assertFalse((self.home / "state/updates/source-a").exists())

    def test_active_runtime_source_drift_and_unlisted_artifact_refuse(self):
        path = self.home / "runtime/harness/enforcement.py"
        path.write_bytes(path.read_bytes() + b"\n# drift\n")
        with self.assertRaisesRegex(ValueError, "source drift"):
            maintenance.plan(self.home, self.source)
        self.assertFalse((self.home / "state/updates").exists())

    def test_active_workflow_binding_drift_is_not_candidate_acceptance(self):
        path = self.home / "runtime/adapters/pi/project-workflow/everyday-runtime.json"
        value = json.loads(path.read_text())
        value["runtime"] = str(self.base)
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "runtime binding"):
            maintenance.plan(self.home, self.source)

    def bind_fixture_descriptors(self):
        # Explicit descriptor fixtures exercise byte checks only, not package/API acceptance.
        framework = self.base / "synthetic-framework-source.py"
        framework.write_text("VALUE = 'original'\n")
        onnx = self.base / "synthetic-onnx-source.py"
        onnx.write_text("CACHE = 'bound'\n")
        helper = self.home / "runtime/adapters/pi/intake/decision-138.py"
        file = self.home / "state/framework-binding.json"
        file.write_text(json.dumps({"schema": "pi-framework-binding/v1", "framework_version": "1.21.0",
                                   "python": sys.executable, "python_sha256": digest(Path(sys.executable)),
                                   "helper": str(helper), "helper_sha256": digest(helper),
                                   "files": [{"path": str(framework), "sha256": digest(framework)}]}))
        shim = self.home / "bin/mempalace"
        shim.write_text("synthetic shim bytes; never executed\n")
        config = json.loads((self.home / "home.json").read_text())
        config["framework_binding_sha256"] = digest(file)
        config["memory_runtime"] = {"schema": "memory-runtime/v1", "mempalace_version": "3.11.0",
                                    "python": sys.executable, "python_sha256": digest(Path(sys.executable)),
                                    "onnx_source": {"path": str(onnx), "sha256": digest(onnx)},
                                    "cache_directory": str(self.home / "cache/chroma/onnx_models/all-MiniLM-L6-v2")}
        config["memory_cli_sha256"] = digest(shim)
        (self.home / "home.json").write_text(json.dumps(config))
        self.active = maintenance.active_snapshot(self.home)[2]
        return framework, onnx

    def test_existing_descriptors_bind_actual_references_and_backup_owned_shim(self):
        framework, onnx = self.bind_fixture_descriptors()
        self.assertIn(str(framework), self.active["bound_artifacts"])
        self.assertIn(str(onnx), self.active["bound_artifacts"])
        staged = self.staged()
        backup = Path(staged["receipt"]).parent / "predecessor/bin/mempalace"
        self.assertEqual(digest(backup), digest(self.home / "bin/mempalace"))
        self.assertTrue(maintenance.verify_stage(self.home, "source-a")["valid_staged_source"])
        self.protected_unchanged()

    def test_framework_descriptor_or_bound_source_drift_refuses(self):
        framework, _onnx = self.bind_fixture_descriptors()
        original = framework.read_bytes()
        framework.write_text("CHANGED = True\n")
        with self.assertRaisesRegex(ValueError, "Framework source binding artifact drift"):
            maintenance.plan(self.home, self.source)
        framework.write_bytes(original)
        file = self.home / "state/framework-binding.json"
        file.write_bytes(file.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "Framework descriptor drift"):
            maintenance.plan(self.home, self.source)
        self.assertFalse((self.home / "state/updates").exists())

    def test_memory_bound_source_drift_invalidates_stage(self):
        _framework, onnx = self.bind_fixture_descriptors()
        self.staged()
        onnx.write_text("CHANGED = True\n")
        result = maintenance.verify_stage(self.home, "source-a")
        self.assertFalse(result["valid_staged_source"])
        self.assertTrue(any("Memory ONNX source binding artifact drift" in error for error in result["errors"]))

    def test_pin_changes_hold_before_staging_or_install(self):
        path = self.source / "harness/home.py"
        value = path.read_text().replace('"mempalace==3.11.0"', '"mempalace==99.0.0"')
        path.write_text(value)
        selected = maintenance.plan(self.home, self.source)
        self.assertEqual(selected["package_changes"][0]["package"], "mempalace")
        with self.assertRaisesRegex(ValueError, "Package pins changed"):
            maintenance.stage(self.home, self.source, "source-a", selected["plan_sha256"])
        self.assertFalse((self.home / "state/updates").exists())
        self.protected_unchanged()

    def test_dynamic_pins_do_not_execute_candidate(self):
        path = self.source / "harness/home.py"
        value = path.read_text().replace('"mempalace": "mempalace==3.11.0"', '"mempalace": __import__("os").getcwd()')
        path.write_text(value)
        with self.assertRaisesRegex(ValueError, "PINS must be data"):
            maintenance.plan(self.home, self.source)
        self.assertFalse(self.execution_marker.exists())

    def test_new_literal_external_dependency_holds_without_import_or_install(self):
        (self.source / "harness/candidate.py").write_text("from missing_dependency.native import execute\n")
        selected = maintenance.plan(self.home, self.source)
        self.assertIn("python:missing_dependency.native", selected["introduced_dependency_imports"])
        with self.assertRaisesRegex(ValueError, "New dependency imports"):
            maintenance.stage(self.home, self.source, "source-a", selected["plan_sha256"])
        self.assertFalse((self.home / "state/updates").exists())
        self.protected_unchanged()

    def test_static_local_import_and_syntax_gaps_hold(self):
        path = self.source / "harness/candidate.py"
        path.write_text("from .missing_component import function\n")
        selected = maintenance.plan(self.home, self.source)
        self.assertTrue(selected["local_closure"]["errors"])
        with self.assertRaisesRegex(ValueError, "unresolved"):
            maintenance.stage(self.home, self.source, "source-a", selected["plan_sha256"])
        path.write_text("def broken(:\n")
        self.assertTrue(maintenance.plan(self.home, self.source)["local_closure"]["errors"])
        self.protected_unchanged()

    def test_js_import_of_unlisted_data_is_not_a_complete_closure(self):
        directory = self.source / "adapters/pi/project-workflow"
        (directory / "candidate.mjs").write_text("import './unlisted.js';\n")
        (directory / "unlisted.js").write_text("export const value=1;\n")
        selected = maintenance.plan(self.home, self.source)
        self.assertTrue(any("outside selected" in error for error in selected["local_closure"]["errors"]))

    def test_candidate_extra_missing_changed_and_request_tampering_detected(self):
        staged = self.staged()
        root = Path(staged["receipt"]).parent
        file = root / "candidate/runtime/harness/candidate.py"
        file.write_text("CHANGED=True\n")
        self.assertFalse(maintenance.verify_stage(self.home, "source-a")["valid_staged_source"])
        (root / "candidate/runtime/extra.json").write_text("{}")
        self.assertTrue(maintenance.verify_stage(self.home, "source-a")["errors"])
        request = json.loads((root / "request.json").read_text())
        request["source_sha256"] = "0" * 64
        (root / "request.json").write_text(json.dumps(request))
        self.assertIn("Retained request changed", maintenance.verify_stage(self.home, "source-a")["errors"])
        self.protected_unchanged()

    def test_predecessor_or_active_change_invalidates_retained_stage(self):
        staged = self.staged()
        old = Path(staged["receipt"]).parent / "predecessor/home.json"
        old.write_bytes(old.read_bytes() + b" ")
        self.assertTrue(any("Predecessor backup changed" in item for item in maintenance.verify_stage(self.home, "source-a")["errors"]))
        config = self.home / "home.json"
        config.write_bytes(config.read_bytes() + b" ")
        self.assertIn("Active state changed after staging", maintenance.verify_stage(self.home, "source-a")["errors"])

    def test_low_space_refuses_before_candidate_copy(self):
        selected = maintenance.plan(self.home, self.source)
        with mock.patch.object(maintenance.shutil, "disk_usage", return_value=shutil._ntuple_diskusage(100, 99, 1)):
            with self.assertRaisesRegex(ValueError, "Insufficient staging space"):
                maintenance.stage(self.home, self.source, "source-a", selected["plan_sha256"])
        self.assertFalse((self.home / "state/updates").exists())
        self.protected_unchanged()

    def test_existing_lock_and_incomplete_operation_are_not_replayed(self):
        updates = self.home / "state/updates"
        updates.mkdir()
        (updates / ".maintenance.lock").write_text("retained unknown owner")
        self.assertTrue(maintenance.plan(self.home, self.source)["pending_operations"])
        with self.assertRaisesRegex(ValueError, "pending"):
            self.staged()
        self.protected_unchanged()

    def test_failure_retains_partial_candidate_and_requires_withdrawal(self):
        original = maintenance.copy_exact

        def fail_candidate(source, target, expected):
            if "candidate/runtime" in target.as_posix():
                raise OSError("Synthetic copy interruption")
            return original(source, target, expected)

        selected = maintenance.plan(self.home, self.source)
        with mock.patch.object(maintenance, "copy_exact", side_effect=fail_candidate):
            with self.assertRaisesRegex(OSError, "copy interruption"):
                maintenance.stage(self.home, self.source, "source-a", selected["plan_sha256"])
        path = self.home / "state/updates/source-a/admission.json"
        self.assertEqual(json.loads(path.read_text())["status"], "failed_staging_not_active")
        self.assertFalse((path.parent.parent / ".maintenance.lock").exists())
        retired = maintenance.withdraw(self.home, "source-a", digest(path))
        self.assertEqual(retired["status"], "withdrawn_not_active")
        self.assertTrue((path.parent / "predecessor/home.json").is_file())
        self.protected_unchanged()

    def test_withdraw_requires_exact_receipt_and_refuses_second_transition(self):
        staged = self.staged()
        with self.assertRaisesRegex(ValueError, "Receipt drift"):
            maintenance.withdraw(self.home, "source-a", "0" * 64)
        retired = maintenance.withdraw(self.home, "source-a", staged["receipt_sha256"])
        with self.assertRaisesRegex(ValueError, "terminal"):
            maintenance.withdraw(self.home, "source-a", retired["receipt_sha256"])
        self.protected_unchanged()

    def test_symlink_escape_is_refused_without_external_mutation(self):
        outside = self.base / "outside"
        outside.mkdir()
        try:
            (self.home / "state/updates").symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest("Symlinks unavailable: " + str(error))
        with self.assertRaises(ValueError):
            maintenance.plan(self.home, self.source)
        self.assertEqual(list(outside.iterdir()), [])
        self.protected_unchanged()

    def test_active_configuration_symlink_refuses_without_external_mutation(self):
        target = self.base / "preserved-home-config.json"
        config = self.home / "home.json"
        original = config.read_bytes()
        target.write_bytes(original)
        config.unlink()
        try:
            config.symlink_to(target)
        except OSError as error:
            config.write_bytes(original)
            self.skipTest("Symlinks unavailable: " + str(error))
        with self.assertRaisesRegex(ValueError, "configuration symlink"):
            maintenance.plan(self.home, self.source)
        self.assertEqual(target.read_bytes(), original)
        config.unlink()
        config.write_bytes(original)
        runtime = self.home / "runtime"
        saved = self.base / "preserved-runtime"
        runtime.rename(saved)
        runtime.symlink_to(saved, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "tree symlink"):
            maintenance.inside(runtime, "harness/home.py", exists=True)
        with self.assertRaisesRegex(ValueError, "symlink|escaped"):
            maintenance.plan(self.home, self.source)
        runtime.unlink()
        saved.rename(runtime)
        self.protected_unchanged()

    def test_existing_active_doctor_and_repair_plan_are_read_only(self):
        result = maintenance.inspect(self.home)
        self.assertEqual(result["active_doctor"]["failures"], [])
        self.assertIn("not candidate", result["doctor_scope"])
        self.assertEqual(result["running_generation"], "not_observed")
        self.assertFalse(maintenance.repair_plan(self.home)["repair"]["automatic_changes"])
        self.protected_unchanged()

    def test_real_cli_plan_and_verify_return_scoped_results(self):
        command = [sys.executable, "-B", "-m", "harness.maintenance", "--home", str(self.home)]
        result = subprocess.run([*command, "plan", "--source", str(self.source)], cwd=REPO, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["candidate_runtime_acceptance"], "not_run")
        self.staged()
        verified = subprocess.run([*command, "verify-stage", "--operation", "source-a"], cwd=REPO, capture_output=True, text=True)
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertFalse(json.loads(verified.stdout)["active_generation_replaced"])
        self.protected_unchanged()


if __name__ == "__main__":
    unittest.main()
