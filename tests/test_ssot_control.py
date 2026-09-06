import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from ssot.control import (
    SSOTError,
    abandon_work,
    accept_project,
    prepare_work,
    project_status,
    submit_outputs,
    verify_stage,
)


VERIFY_GOOD = """import sys
from pathlib import Path
def valid(text):
    return text.startswith('ok:')
if '--negative-control' in sys.argv:
    raise SystemExit(0 if not valid('invalid') else 1)
raise SystemExit(0 if valid(Path('artifacts/result.txt').read_text(encoding='utf-8')) else 1)
"""

ACCEPT_GOOD = """import sys
from pathlib import Path
def valid(text):
    return text == 'ok: final\\n'
if '--negative-control' in sys.argv:
    raise SystemExit(0 if not valid('invalid') else 1)
raise SystemExit(0 if valid(Path('artifacts/result.txt').read_text(encoding='utf-8')) else 1)
"""


class StarterSSOTTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        prd_path = self.root / "PRD.md"
        prd_path.write_text("produce the result\n", encoding="utf-8")
        self.prd_hash = hashlib.sha256(prd_path.read_bytes()).hexdigest()
        (self.root / "input.txt").write_text("stable input\n", encoding="utf-8")
        (self.root / "verify.py").write_text(VERIFY_GOOD, encoding="utf-8")
        (self.root / "accept.py").write_text(ACCEPT_GOOD, encoding="utf-8")
        (self.root / "artifacts").mkdir()
        self.project = {
            "schema_version": 1,
            "project_id": "test-project",
            "authority_cap": "tested",
            "target": {"files": ["PRD.md"]},
            "requirements": [
                {
                    "id": "REQ-001",
                    "text": "Produce the result.",
                    "scope_class": "project_specific",
                    "source": {
                        "path": "PRD.md",
                        "locator": "line:1",
                        "sha256": self.prd_hash,
                    },
                    "disposition": "applicable",
                    "owner_stage": "build",
                }
            ],
            "stages": [
                {
                    "id": "build",
                    "objective": "build result",
                    "acceptance": "result starts with ok",
                    "depends_on": [],
                    "requirements": ["REQ-001"],
                    "materials": ["PRD.md", "input.txt"],
                    "outputs": ["artifacts/result.txt"],
                    "properties": ["result starts with ok"],
                    "verifier": {
                        "owner": "host-verifier",
                        "type": "deterministic_property",
                        "argv": ["{python}", "verify.py"],
                        "negative_control": {
                            "argv": ["{python}", "verify.py", "--negative-control"]
                        },
                        "files": ["verify.py"],
                        "timeout_seconds": 30,
                    },
                }
            ],
            "acceptance": {
                "owner": "independent-acceptor",
                "type": "deterministic_property",
                "argv": ["{python}", "accept.py"],
                "negative_control": {
                    "argv": ["{python}", "accept.py", "--negative-control"]
                },
                "files": ["accept.py"],
                "timeout_seconds": 30,
            },
        }
        self.runtime = {
            "kind": "script",
            "executor": "unit-test",
            "harness": "unittest",
            "harness_version": "stdlib",
            "host_observed": True,
            "attempt": 1,
            "fallback_from": None,
        }
        self._write_project()

    def tearDown(self):
        self.temporary.cleanup()

    def _write_project(self):
        (self.root / "ssot-project.json").write_text(
            json.dumps(self.project, indent=2) + "\n", encoding="utf-8"
        )

    def _execution(self, trace_file="artifacts/result.txt"):
        return {
            "host_observed": True,
            "status": "completed",
            "duration_ms": 1,
            "trace_file": trace_file,
        }

    def _produce(self, text="ok: final\n", worker="worker-a"):
        work = prepare_work(self.root, "build", worker, self.runtime)
        (self.root / "artifacts" / "result.txt").write_text(text, encoding="utf-8")
        submit_outputs(self.root, work["run_id"], worker, self._execution())
        return work

    def test_full_workflow_reaches_tested_but_not_blessed(self):
        initial = project_status(self.root)
        self.assertEqual(initial["authority_state"], "compiled")
        self.assertEqual(initial["stages"][0]["state"], "frontier")
        work = self._produce()
        receipt = verify_stage(self.root, work["run_id"])
        self.assertEqual(receipt["status"], "verified")
        before_acceptance = project_status(self.root)
        self.assertTrue(before_acceptance["stages_verified"])
        self.assertFalse(before_acceptance["complete"])
        self.assertFalse(before_acceptance["accepted"])
        self.assertEqual(before_acceptance["authority_state"], "enforced")
        accept_project(self.root, "independent-acceptor")
        final = project_status(self.root)
        self.assertTrue(final["accepted"])
        self.assertEqual(final["authority_state"], "tested")

    def test_worker_cannot_be_verifier_owner(self):
        with self.assertRaisesRegex(SSOTError, "must differ"):
            prepare_work(self.root, "build", "host-verifier", self.runtime)

    def test_acceptance_owner_must_be_separate_from_stage_verifier(self):
        self.project["acceptance"]["owner"] = "host-verifier"
        self._write_project()
        with self.assertRaisesRegex(SSOTError, "independent"):
            project_status(self.root)

    def test_unchanged_preexisting_output_is_not_same_run_production(self):
        output = self.root / "artifacts" / "result.txt"
        output.write_text("ok: final\n", encoding="utf-8")
        work = prepare_work(self.root, "build", "worker-a", self.runtime)
        output.write_text("ok: final\n", encoding="utf-8")
        with self.assertRaisesRegex(SSOTError, "not produced in this run"):
            submit_outputs(self.root, work["run_id"], "worker-a", self._execution())

    def test_target_drift_blocks_submission(self):
        work = prepare_work(self.root, "build", "worker-a", self.runtime)
        (self.root / "artifacts" / "result.txt").write_text(
            "ok: final\n", encoding="utf-8"
        )
        (self.root / "PRD.md").write_text("changed requirement\n", encoding="utf-8")
        with self.assertRaisesRegex(SSOTError, "source bytes changed"):
            submit_outputs(self.root, work["run_id"], "worker-a", self._execution())

    def test_abandoned_work_cannot_be_replayed(self):
        work = prepare_work(self.root, "build", "worker-a", self.runtime)
        abandon_work(self.root, work["run_id"], "worker stopped")
        (self.root / "artifacts" / "result.txt").write_text(
            "ok: final\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(SSOTError, "terminal"):
            submit_outputs(self.root, work["run_id"], "worker-a", self._execution())
        replacement = prepare_work(self.root, "build", "worker-b", self.runtime)
        self.assertNotEqual(replacement["run_id"], work["run_id"])

    def test_verifier_mutation_fails(self):
        (self.root / "verify.py").write_text(
            "from pathlib import Path\nPath('mutation.txt').write_text('bad')\nraise SystemExit(0)\n",
            encoding="utf-8",
        )
        work = self._produce()
        receipt = verify_stage(self.root, work["run_id"])
        self.assertEqual(receipt["status"], "failed")
        self.assertIn(
            "mutated_project",
            (
                receipt["negative_control_purity"],
                receipt["verifier_purity"],
            ),
        )
        self.assertFalse(project_status(self.root)["stages_verified"])

    def test_verifier_byte_drift_blocks_verification(self):
        work = self._produce()
        (self.root / "verify.py").write_text(
            VERIFY_GOOD + "\n# changed after work preparation\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(SSOTError, "verifier bytes changed"):
            verify_stage(self.root, work["run_id"])

    def test_verifier_negative_control_must_pass(self):
        (self.root / "verify.py").write_text(
            "import sys\n"
            "raise SystemExit(1 if '--negative-control' in sys.argv else 0)\n",
            encoding="utf-8",
        )
        work = self._produce()
        receipt = verify_stage(self.root, work["run_id"])
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["negative_control_exit_code"], 1)

    def test_acceptance_negative_control_must_pass(self):
        (self.root / "accept.py").write_text(
            "import sys\n"
            "raise SystemExit(1 if '--negative-control' in sys.argv else 0)\n",
            encoding="utf-8",
        )
        work = self._produce()
        verify_stage(self.root, work["run_id"])
        with self.assertRaisesRegex(SSOTError, "negative control failed"):
            accept_project(self.root, "independent-acceptor")

    def test_output_drift_retracts_completion(self):
        work = self._produce()
        verify_stage(self.root, work["run_id"])
        self.assertTrue(project_status(self.root)["stages_verified"])
        (self.root / "artifacts" / "result.txt").write_text(
            "tampered\n", encoding="utf-8"
        )
        status = project_status(self.root)
        self.assertFalse(status["stages_verified"])
        self.assertEqual(status["stages"][0]["state"], "frontier")

    def test_event_chain_tamper_fails_closed(self):
        prepare_work(self.root, "build", "worker-a", self.runtime)
        events = self.root / ".ssot" / "events.jsonl"
        events.write_text(
            events.read_text(encoding="utf-8").replace("work_prepared", "work_forged"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(SSOTError, "event chain failed"):
            project_status(self.root)

    def test_dependency_frontier_blocks_skip(self):
        second_verifier = self.root / "verify_second.py"
        second_verifier.write_text("raise SystemExit(0)\n", encoding="utf-8")
        self.project["stages"].append(
            {
                "id": "review",
                "objective": "review",
                "acceptance": "review exists",
                "depends_on": ["build"],
                "requirements": ["REQ-002"],
                "materials": ["PRD.md", "artifacts/result.txt"],
                "outputs": ["artifacts/review.txt"],
                "properties": ["review exists"],
                "verifier": {
                    "owner": "review-verifier",
                    "type": "deterministic_property",
                    "argv": ["{python}", "verify_second.py"],
                    "negative_control": {
                        "argv": [
                            "{python}",
                            "verify_second.py",
                            "--negative-control",
                        ]
                    },
                    "files": ["verify_second.py"],
                },
            }
        )
        self.project["requirements"].append(
            {
                "id": "REQ-002",
                "text": "Review the result.",
                "scope_class": "project_specific",
                "source": {
                    "path": "PRD.md",
                    "locator": "derived:review",
                    "sha256": self.prd_hash,
                },
                "disposition": "applicable",
                "owner_stage": "review",
            }
        )
        self._write_project()
        with self.assertRaisesRegex(SSOTError, "not on the current frontier"):
            prepare_work(self.root, "review", "worker-a", self.runtime)

    def test_unresolved_requirement_blocks_acceptance(self):
        self.project["requirements"].append(
            {
                "id": "REQ-OPEN",
                "text": "A decision is still required.",
                "scope_class": "not_yet_understood",
                "source": {
                    "path": "PRD.md",
                    "locator": "decision:open",
                    "sha256": self.prd_hash,
                },
                "disposition": "unresolved",
            }
        )
        self._write_project()
        work = self._produce()
        verify_stage(self.root, work["run_id"])
        status = project_status(self.root)
        self.assertTrue(status["stages_verified"])
        self.assertFalse(status["requirements"]["conserved"])
        with self.assertRaisesRegex(SSOTError, "unresolved requirements"):
            accept_project(self.root, "independent-acceptor")

    def test_typed_independent_waiver_is_conserved(self):
        (self.root / "waiver.md").write_text(
            "REQ-WAIVED is not applicable to this package.\n", encoding="utf-8"
        )
        self.project["requirements"].append(
            {
                "id": "REQ-WAIVED",
                "text": "Use a deployment-specific external service.",
                "scope_class": "universal",
                "source": {
                    "path": "PRD.md",
                    "locator": "decision:external",
                    "sha256": self.prd_hash,
                },
                "disposition": "waived",
                "waiver_type": "not_applicable",
                "reason": "The unit-test package has no external service.",
                "approved_by": "waiver-reviewer",
                "evidence": ["waiver.md"],
            }
        )
        self._write_project()
        status = project_status(self.root)
        self.assertTrue(status["requirements"]["conserved"])
        self.assertEqual(status["requirements"]["counts"]["waived"], 1)

    def test_supersession_cycle_fails_closed(self):
        (self.root / "supersession.md").write_text("Cycle fixture.\n", encoding="utf-8")
        for current, replacement in (("REQ-A", "REQ-B"), ("REQ-B", "REQ-A")):
            self.project["requirements"].append(
                {
                    "id": current,
                    "text": f"Superseded fixture {current}.",
                    "scope_class": "project_specific",
                    "source": {
                        "path": "PRD.md",
                        "locator": f"fixture:{current}",
                        "sha256": self.prd_hash,
                    },
                    "disposition": "superseded",
                    "superseded_by": replacement,
                    "reason": "Cycle negative control.",
                    "approved_by": "change-reviewer",
                    "evidence": ["supersession.md"],
                }
            )
        self._write_project()
        with self.assertRaisesRegex(SSOTError, "supersession cycle"):
            project_status(self.root)

    def test_material_drift_blocks_submission(self):
        work = prepare_work(self.root, "build", "worker-a", self.runtime)
        (self.root / "artifacts" / "result.txt").write_text(
            "ok: final\n", encoding="utf-8"
        )
        (self.root / "input.txt").write_text("changed input\n", encoding="utf-8")
        with self.assertRaisesRegex(SSOTError, "material bytes changed"):
            submit_outputs(self.root, work["run_id"], "worker-a", self._execution())

    def test_runtime_identity_is_required_and_propagated(self):
        invalid = dict(self.runtime)
        invalid["host_observed"] = False
        with self.assertRaisesRegex(SSOTError, "host_observed"):
            prepare_work(self.root, "build", "worker-a", invalid)
        work = self._produce()
        producer = submit_path = (
            self.root / ".ssot" / "producer-receipts" / f"{work['run_id']}.json"
        )
        self.assertTrue(submit_path.is_file())
        self.assertEqual(json.loads(producer.read_text())["runtime"], self.runtime)

    def test_model_execution_receipt_binds_call_telemetry_and_files(self):
        digest = "a" * 64
        runtime = {
            "kind": "local_model",
            "executor": "host-adapter",
            "harness": "custom",
            "harness_version": "1",
            "host_observed": True,
            "attempt": 1,
            "fallback_from": None,
            "provider_family": "openai-compatible",
            "model_family": "qwen",
            "checkpoint": "model.gguf",
            "served_model_id": "qwen-local",
            "backend": "llama.cpp",
            "quant": "Q4_K_M",
            "endpoint": "http://127.0.0.1:8080/v1",
            "system_prompt_sha256": digest,
            "context_sha256": digest,
            "sampling": {"temperature": 0},
        }
        work = prepare_work(self.root, "build", "worker-a", runtime)
        (self.root / "artifacts" / "result.txt").write_text(
            "ok: final\n", encoding="utf-8"
        )
        execution = {
            "host_observed": True,
            "status": "completed",
            "duration_ms": 42,
            "trace_file": "artifacts/result.txt",
            "model_call_id": "call-1",
            "input_bytes": 100,
            "output_bytes": 10,
            "prompt_tokens": 20,
            "completion_tokens": 3,
            "tool_calls": [],
            "raw_output_file": "artifacts/result.txt",
            "parsed_output_file": "artifacts/result.txt",
        }
        receipt = submit_outputs(self.root, work["run_id"], "worker-a", execution)
        self.assertEqual(receipt["execution"]["model_call_id"], "call-1")
        self.assertEqual(
            receipt["execution"]["trace"]["sha256"],
            receipt["outputs"][0]["sha256"],
        )

    def test_model_execution_receipt_rejects_missing_telemetry(self):
        digest = "b" * 64
        runtime = {
            "kind": "local_model",
            "executor": "host-adapter",
            "harness": "custom",
            "harness_version": "1",
            "host_observed": True,
            "attempt": 1,
            "fallback_from": None,
            "provider_family": "openai-compatible",
            "model_family": "qwen",
            "checkpoint": "model.gguf",
            "served_model_id": "qwen-local",
            "backend": "llama.cpp",
            "quant": "Q4_K_M",
            "endpoint": "http://127.0.0.1:8080/v1",
            "system_prompt_sha256": digest,
            "context_sha256": digest,
            "sampling": {"temperature": 0},
        }
        work = prepare_work(self.root, "build", "worker-a", runtime)
        (self.root / "artifacts" / "result.txt").write_text(
            "ok: final\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(SSOTError, "model_call_id"):
            submit_outputs(self.root, work["run_id"], "worker-a", self._execution())

    def test_process_local_controller_lock_fails_closed(self):
        from ssot.control import _controller_lock

        errors = []

        def contender():
            try:
                prepare_work(self.root, "build", "worker-b", self.runtime)
            except SSOTError as exc:
                errors.append(str(exc))

        with _controller_lock(self.root):
            thread = threading.Thread(target=contender)
            thread.start()
            thread.join()
        self.assertEqual(errors, ["another controller mutation is active"])

    def test_cross_process_controller_lock_fails_closed(self):
        from ssot.control import _controller_lock

        source_root = Path(__file__).resolve().parents[1]
        child = """import json
import sys
from pathlib import Path
from ssot.control import SSOTError, prepare_work
runtime = json.loads(sys.argv[2])
try:
    prepare_work(Path(sys.argv[1]), 'build', 'worker-child', runtime)
except SSOTError as exc:
    print(exc)
    raise SystemExit(0)
raise SystemExit(1)
"""
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(source_root)
        with _controller_lock(self.root):
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    child,
                    str(self.root),
                    json.dumps(self.runtime),
                ],
                cwd=self.root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("another controller process is active", completed.stdout)

    def test_blessed_cap_requires_external_trust_provider(self):
        self.project["authority_cap"] = "blessed"
        self._write_project()
        with self.assertRaisesRegex(SSOTError, "external trust provider"):
            project_status(self.root)


if __name__ == "__main__":
    unittest.main()
