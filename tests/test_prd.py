import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from harness.compiler import compile_ssot
from harness.prd import REINFORCEMENT_CHECKS, admit_prd
from harness.project import ProjectError, create_intent, project_status, request_execution
from ssot.control import prepare_work


REVIEWER = r'''import json
import os
import sys
from pathlib import Path

owner = "independent-reviewer"
if "--negative-control" in sys.argv:
    verdict = "failed" if "--fail" in sys.argv else "negative_control_pass"
    print(json.dumps({"verdict": verdict, "reviewer_identity": owner}))
    raise SystemExit(0)

if "--mutate" in sys.argv:
    Path(".enforcement").mkdir(exist_ok=True)
    Path(".enforcement/reviewer-mutation").write_text("changed", encoding="utf-8")

manifest = json.loads(Path(os.environ["TRUSTED_PROJECT_MANIFEST"]).read_text())
print(json.dumps({
    "verdict": "approved",
    "reviewer_identity": owner,
    "project_id": os.environ["TRUSTED_PROJECT_PROJECT_ID"],
    "intent_sha256": os.environ["TRUSTED_PROJECT_INTENT_SHA256"],
    "prd_sha256": os.environ["TRUSTED_PROJECT_PRD_SHA256"],
    "manifest_sha256": os.environ["TRUSTED_PROJECT_MANIFEST_SHA256"],
    "reinforcement_sha256": os.environ["TRUSTED_PROJECT_REINFORCEMENT_SHA256"],
    "requirement_ids": [row["id"] for row in manifest["requirements"]],
    "open_decisions": [],
}))
'''

SSOT_REVIEWER = r'''import json
import os
import sys
from pathlib import Path

owner = "ssot-independent-reviewer"
if "--negative-control" in sys.argv:
    print(json.dumps({"verdict": "negative_control_pass", "reviewer_identity": owner}))
    raise SystemExit(0)

if "--mutate" in sys.argv:
    Path("ssot-reviewer-mutation").write_text("changed", encoding="utf-8")

manifest = json.loads(Path(os.environ["TRUSTED_PROJECT_MANIFEST"]).read_text())
verifiers = json.loads(
    Path(os.environ["TRUSTED_PROJECT_VERIFIER_CANDIDATES"]).read_text()
)
print(json.dumps({
    "verdict": "approved",
    "reviewer_identity": owner,
    "project_id": os.environ["TRUSTED_PROJECT_PROJECT_ID"],
    "intent_sha256": os.environ["TRUSTED_PROJECT_INTENT_SHA256"],
    "review_receipt_sha256": os.environ["TRUSTED_PROJECT_REVIEW_RECEIPT_SHA256"],
    "manifest_sha256": os.environ["TRUSTED_PROJECT_MANIFEST_SHA256"],
    "verifier_candidates_sha256": os.environ[
        "TRUSTED_PROJECT_VERIFIER_CANDIDATES_SHA256"
    ],
    "requirement_ids": [row["id"] for row in manifest["requirements"]],
    "verifier_scopes": [row["scope"] for row in verifiers["verifiers"]],
}))
'''


class TrustedPrdAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "AGENTS.md").write_text("# Target rules\n", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def _candidate(self, *, intent_decisions=None, budget=None):
        budget_path = None
        if budget is not None:
            budget_path = self.root / "budget.json"
            self._write_json(budget_path, budget)
        activation = create_intent(
            self.root,
            "Build a checked parser",
            "execute",
            open_decisions=intent_decisions or [],
            budget_file=budget_path,
        )
        project_id = activation["project_id"]
        project = self.root / ".trusted-project" / "projects" / project_id
        intent_path = project / "intent.json"
        intent = json.loads(intent_path.read_text(encoding="utf-8"))
        candidate = self.root / "candidate"
        candidate.mkdir()
        prd = candidate / "PRD.md"
        prd.write_text("# Checked parser\n\nReturn a parsed result.\n", encoding="utf-8")
        requirement_text = "Return a parsed result."
        manifest = {
            "schema_version": 1,
            "project_id": project_id,
            "intent_sha256": self._sha(intent_path),
            "prd_sha256": self._sha(prd),
            "requirements": [
                {
                    "id": "REQ-001",
                    "text": requirement_text,
                    "acceptance": ["A valid input returns a parsed result."],
                    "sources": [
                        {
                            "class": "user",
                            "locator": "intent.request",
                            "sha256": intent["request"]["sha256"],
                        }
                    ],
                    "prd_locator": {
                        "line_start": 3,
                        "line_end": 3,
                        "text_sha256": self._line_sha(prd, 3, 3),
                    },
                }
            ],
            "non_goals": [],
            "constraints": [],
            "risks": [{"risk": "Invalid input", "mitigation": "Reject it"}],
            "dependencies": [],
            "deliverables": ["Parser implementation"],
            "open_decisions": [],
        }
        manifest_path = candidate / "prd-manifest.json"
        self._write_json(manifest_path, manifest)
        reinforcement = {
            "schema_version": 1,
            "project_id": project_id,
            "critic_identity": "prd-critic",
            "prd_sha256": self._sha(prd),
            "manifest_sha256": self._sha(manifest_path),
            "checks": {
                name: {"passed": True, "evidence": [f"{name} checked"]}
                for name in REINFORCEMENT_CHECKS
            },
            "issues": [],
            "open_decisions": [],
        }
        reinforcement_path = candidate / "prd-reinforcement.json"
        self._write_json(reinforcement_path, reinforcement)
        (self.root / "review_prd.py").write_text(REVIEWER, encoding="utf-8")
        contract = {
            "schema_version": 1,
            "project_id": project_id,
            "drafter_identity": "chosen-harness",
            "prd_path": "candidate/PRD.md",
            "manifest_path": "candidate/prd-manifest.json",
            "reinforcement_path": "candidate/prd-reinforcement.json",
            "reviewer": {
                "owner": "independent-reviewer",
                "argv": ["{python}", "review_prd.py"],
                "files": ["review_prd.py"],
                "timeout_seconds": 30,
                "negative_control": {
                    "argv": ["{python}", "review_prd.py", "--negative-control"],
                    "files": ["review_prd.py"],
                    "timeout_seconds": 30,
                },
            },
        }
        contract_path = self.root / "admit-prd.json"
        self._write_json(contract_path, contract)
        return project_id, contract_path, manifest_path, reinforcement_path

    def _compiler_candidate(self, *, two_requirements=False, budget=None):
        project_id, admission, manifest_path, reinforcement_path = self._candidate(
            budget=budget
        )
        if two_requirements:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            second = dict(manifest["requirements"][0])
            second["id"] = "REQ-002"
            second["text"] = "Reject invalid input."
            manifest["requirements"].append(second)
            self._write_json(manifest_path, manifest)
            reinforcement = json.loads(reinforcement_path.read_text(encoding="utf-8"))
            reinforcement["manifest_sha256"] = self._sha(manifest_path)
            self._write_json(reinforcement_path, reinforcement)
        admit_prd(self.root, project_id, admission)
        project_dir = self.root / ".trusted-project" / "projects" / project_id
        reviewed_manifest = json.loads(
            (project_dir / "prd" / "prd-manifest.json").read_text(encoding="utf-8")
        )
        reviewed_prd = project_dir / "prd" / "PRD.md"
        reviewed_prd_relative = reviewed_prd.relative_to(self.root).as_posix()
        (self.root / "verify_stage.py").write_text(
            "raise SystemExit(0)\n", encoding="utf-8"
        )
        (self.root / "worker.py").write_text(
            "from pathlib import Path\nPath('result.json').write_text('{}\\n')\n",
            encoding="utf-8",
        )
        (self.root / "verify_task.py").write_text(
            "raise SystemExit(0)\n", encoding="utf-8"
        )
        (self.root / "accept_project.py").write_text(
            "raise SystemExit(0)\n", encoding="utf-8"
        )
        task = {
            "schema_version": 1,
            "task_id": "build-reviewed-result",
            "objective": "Build the reviewed result.",
            "worker": {
                "argv": ["{python}", "worker.py"],
                "files": ["worker.py"],
                "timeout_seconds": 30,
            },
            "outputs": ["result.json"],
            "receipt_output": "enforcement-receipt.json",
            "retry": {
                "max_attempts": 2,
                "retry_on": ["process_failure", "verification_failure"],
                "backoff_seconds": [0],
                "inner_tool_max_attempts": 1,
            },
            "research": {"required": False},
            "verifier": {
                "argv": ["{python}", "verify_task.py"],
                "files": ["verify_task.py"],
                "timeout_seconds": 30,
                "negative_control": {
                    "argv": ["{python}", "verify_task.py", "--negative-control"],
                    "files": ["verify_task.py"],
                    "timeout_seconds": 30,
                },
            },
        }
        task_path = self.root / "candidate" / "build-task.json"
        self._write_json(task_path, task)
        requirements = []
        acceptance = []
        for row in reviewed_manifest["requirements"]:
            locator = row["prd_locator"]
            requirements.append(
                {
                    "id": row["id"],
                    "text": row["text"],
                    "scope_class": "project_specific",
                    "source": {
                        "path": reviewed_prd_relative,
                        "locator": f"line:{locator['line_start']}-{locator['line_end']}",
                        "sha256": self._sha(reviewed_prd),
                    },
                    "disposition": "applicable",
                    "owner_stage": "build",
                    "acceptance_evidence": row["acceptance"],
                }
            )
            acceptance.extend(row["acceptance"])
        candidate = {
            "schema_version": 1,
            "project_id": project_id,
            "authority_cap": "tested",
            "target": {"files": [reviewed_prd_relative]},
            "requirements": requirements,
            "stages": [
                {
                    "id": "build",
                    "objective": "Build the reviewed result.",
                    "acceptance": "Every reviewed acceptance property passes.",
                    "depends_on": [],
                    "requirements": [row["id"] for row in requirements],
                    "materials": [
                        reviewed_prd_relative,
                        "candidate/build-task.json",
                        "worker.py",
                        "verify_task.py",
                    ],
                    "trace_output": "ssot-execution-trace.json",
                    "outputs": [
                        "result.json",
                        "enforcement-receipt.json",
                        "ssot-execution-trace.json",
                    ],
                    "properties": acceptance,
                    "action": {
                        "kind": "harness.enforcement",
                        "producer": "chosen-harness-worker",
                        "verifier_owner": "task-verifier",
                        "contract": "candidate/build-task.json",
                        "contract_sha256": self._sha(task_path),
                        "receipt_output": "enforcement-receipt.json",
                        "usage_mode": "script_no_model",
                        "effects": [],
                        "runtime_profile": None,
                        "runtime_profile_sha256": None,
                    },
                    "verifier": {
                        "owner": "stage-verifier",
                        "type": "deterministic_property",
                        "argv": ["{python}", "verify_stage.py"],
                        "negative_control": {
                            "argv": ["{python}", "verify_stage.py", "--negative-control"]
                        },
                        "files": ["verify_stage.py"],
                        "timeout_seconds": 30,
                    },
                }
            ],
            "acceptance": {
                "owner": "project-acceptor",
                "type": "deterministic_property",
                "argv": ["{python}", "accept_project.py"],
                "negative_control": {
                    "argv": ["{python}", "accept_project.py", "--negative-control"]
                },
                "files": ["accept_project.py"],
                "timeout_seconds": 30,
            },
        }
        candidate_path = self.root / "candidate" / "ssot-project.json"
        self._write_json(candidate_path, candidate)

        def record(path):
            return {
                "path": path.relative_to(self.root).as_posix(),
                "size": path.stat().st_size,
                "sha256": self._sha(path),
            }

        verifiers = {
            "schema_version": 1,
            "project_id": project_id,
            "status": "untrusted_drafts",
            "generated_by": "chosen-harness-compiler",
            "candidate_manifest_sha256": self._sha(candidate_path),
            "verifiers": [
                {
                    "scope": "stage:build",
                    "owner": "stage-verifier",
                    "argv": ["{python}", "verify_stage.py"],
                    "negative_control_argv": [
                        "{python}",
                        "verify_stage.py",
                        "--negative-control",
                    ],
                    "files": [record(self.root / "verify_stage.py")],
                },
                {
                    "scope": "action:build",
                    "owner": "task-verifier",
                    "argv": ["{python}", "verify_task.py"],
                    "negative_control_argv": [
                        "{python}",
                        "verify_task.py",
                        "--negative-control",
                    ],
                    "files": [record(self.root / "verify_task.py")],
                },
                {
                    "scope": "acceptance",
                    "owner": "project-acceptor",
                    "argv": ["{python}", "accept_project.py"],
                    "negative_control_argv": [
                        "{python}",
                        "accept_project.py",
                        "--negative-control",
                    ],
                    "files": [record(self.root / "accept_project.py")],
                },
            ],
        }
        verifier_path = self.root / "candidate" / "verifier-candidates.json"
        self._write_json(verifier_path, verifiers)
        (self.root / "review_ssot.py").write_text(SSOT_REVIEWER, encoding="utf-8")
        contract = {
            "schema_version": 1,
            "project_id": project_id,
            "compiler_identity": "chosen-harness-compiler",
            "manifest_path": candidate_path.relative_to(self.root).as_posix(),
            "verifier_candidates_path": verifier_path.relative_to(self.root).as_posix(),
            "reviewer": {
                "owner": "ssot-independent-reviewer",
                "argv": ["{python}", "review_ssot.py"],
                "files": ["review_ssot.py"],
                "timeout_seconds": 30,
                "negative_control": {
                    "argv": ["{python}", "review_ssot.py", "--negative-control"],
                    "files": ["review_ssot.py"],
                    "timeout_seconds": 30,
                },
            },
        }
        contract_path = self.root / "compile-ssot.json"
        self._write_json(contract_path, contract)
        return project_id, contract_path, candidate_path, verifier_path

    @staticmethod
    def _sha(path):
        import hashlib

        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _line_sha(path, start, end):
        import hashlib

        lines = path.read_bytes().splitlines(keepends=True)
        return hashlib.sha256(b"".join(lines[start - 1 : end])).hexdigest()

    @staticmethod
    def _write_json(path, value):
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def test_reviewed_candidate_is_published_and_execution_stays_held(self):
        project_id, contract, _manifest, _reinforcement = self._candidate()
        result = admit_prd(self.root, project_id, contract)
        self.assertEqual(result["state"], "prd_reviewed")
        self.assertEqual(result["authority"], "reviewed_prd_only_no_execution")
        self.assertFalse(result["ready_for_execution"])
        published = (
            self.root / ".trusted-project" / "projects" / project_id / "prd"
        )
        self.assertTrue((published / "review-receipt.json").is_file())
        repeated = admit_prd(self.root, project_id, contract)
        self.assertTrue(repeated["idempotent"])
        held = request_execution(self.root, project_id)
        self.assertEqual(held["state"], "held_ssot_not_compiled")

    def test_intent_open_decision_holds_before_review(self):
        project_id, contract, _manifest, _reinforcement = self._candidate(
            intent_decisions=["Select the output format"]
        )
        self.assertEqual(project_status(self.root, project_id)["state"], "held_open_decisions")
        with self.assertRaisesRegex(ProjectError, "held_open_decisions"):
            admit_prd(self.root, project_id, contract)

    def test_manifest_open_decision_is_not_silently_selected(self):
        project_id, contract, manifest_path, reinforcement_path = self._candidate()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["open_decisions"] = ["Choose a wire format"]
        self._write_json(manifest_path, manifest)
        reinforcement = json.loads(reinforcement_path.read_text(encoding="utf-8"))
        reinforcement["manifest_sha256"] = self._sha(manifest_path)
        self._write_json(reinforcement_path, reinforcement)
        with self.assertRaisesRegex(ProjectError, "unresolved material decisions"):
            admit_prd(self.root, project_id, contract)

    def test_requirement_without_source_class_is_rejected(self):
        project_id, contract, manifest_path, reinforcement_path = self._candidate()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        del manifest["requirements"][0]["sources"][0]["class"]
        self._write_json(manifest_path, manifest)
        reinforcement = json.loads(reinforcement_path.read_text(encoding="utf-8"))
        reinforcement["manifest_sha256"] = self._sha(manifest_path)
        self._write_json(reinforcement_path, reinforcement)
        with self.assertRaisesRegex(ProjectError, "source.class"):
            admit_prd(self.root, project_id, contract)

    def test_requirement_must_bind_exact_prd_lines(self):
        project_id, contract, manifest_path, reinforcement_path = self._candidate()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["requirements"][0]["prd_locator"]["text_sha256"] = "0" * 64
        self._write_json(manifest_path, manifest)
        reinforcement = json.loads(reinforcement_path.read_text(encoding="utf-8"))
        reinforcement["manifest_sha256"] = self._sha(manifest_path)
        self._write_json(reinforcement_path, reinforcement)
        with self.assertRaisesRegex(ProjectError, "prd_locator text hash mismatch"):
            admit_prd(self.root, project_id, contract)

    def test_reviewed_target_source_drift_fails_status(self):
        project_id, contract, manifest_path, reinforcement_path = self._candidate()
        design = self.root / "design.md"
        design.write_text("Use a streaming parser.\n", encoding="utf-8")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["requirements"][0]["sources"].append(
            {
                "class": "target",
                "locator": "design.md:1",
                "path": "design.md",
                "sha256": self._sha(design),
            }
        )
        self._write_json(manifest_path, manifest)
        reinforcement = json.loads(reinforcement_path.read_text(encoding="utf-8"))
        reinforcement["manifest_sha256"] = self._sha(manifest_path)
        self._write_json(reinforcement_path, reinforcement)
        admit_prd(self.root, project_id, contract)
        design.write_text("Use a batch parser.\n", encoding="utf-8")
        with self.assertRaisesRegex(ProjectError, "source file hash changed"):
            project_status(self.root, project_id)

    def test_failed_reinforcement_check_is_rejected(self):
        project_id, contract, _manifest_path, reinforcement_path = self._candidate()
        reinforcement = json.loads(reinforcement_path.read_text(encoding="utf-8"))
        reinforcement["checks"]["risk"]["passed"] = False
        self._write_json(reinforcement_path, reinforcement)
        with self.assertRaisesRegex(ProjectError, "risk did not pass"):
            admit_prd(self.root, project_id, contract)

    def test_reviewer_must_be_independent(self):
        project_id, contract_path, _manifest, _reinforcement = self._candidate()
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["reviewer"]["owner"] = contract["drafter_identity"]
        self._write_json(contract_path, contract)
        with self.assertRaisesRegex(ProjectError, "distinct from drafter"):
            admit_prd(self.root, project_id, contract_path)

    def test_negative_control_must_prove_rejection(self):
        project_id, contract_path, _manifest, _reinforcement = self._candidate()
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["reviewer"]["negative_control"]["argv"].append("--fail")
        self._write_json(contract_path, contract)
        with self.assertRaisesRegex(ProjectError, "did not prove rejection"):
            admit_prd(self.root, project_id, contract_path)

    def test_reviewer_cannot_change_even_excluded_enforcement_state(self):
        project_id, contract_path, _manifest, _reinforcement = self._candidate()
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["reviewer"]["argv"].append("--mutate")
        self._write_json(contract_path, contract)
        with self.assertRaisesRegex(ProjectError, "changed target files"):
            admit_prd(self.root, project_id, contract_path)

    def test_receipt_or_verifier_drift_fails_status(self):
        project_id, contract, _manifest, _reinforcement = self._candidate()
        admit_prd(self.root, project_id, contract)
        reviewer = self.root / "review_prd.py"
        reviewer.write_text(REVIEWER + "\n# drift\n", encoding="utf-8")
        with self.assertRaisesRegex(ProjectError, "reviewer file 0 (size|hash) changed"):
            project_status(self.root, project_id)

    def test_review_receipt_tamper_fails_status(self):
        project_id, contract, _manifest, _reinforcement = self._candidate()
        admit_prd(self.root, project_id, contract)
        receipt = (
            self.root
            / ".trusted-project"
            / "projects"
            / project_id
            / "prd"
            / "review-receipt.json"
        )
        value = json.loads(receipt.read_text(encoding="utf-8"))
        value["authority_cap"] = "blessed"
        self._write_json(receipt, value)
        with self.assertRaisesRegex(ProjectError, "receipt hash mismatch"):
            project_status(self.root, project_id)

    def test_compiled_ssot_is_lossless_and_zero_budget_stays_held(self):
        project_id, contract, _candidate, _verifiers = self._compiler_candidate()
        result = compile_ssot(self.root, project_id, contract)
        self.assertEqual(result["state"], "configured")
        self.assertEqual(result["authority"], "no_project_completion_authority")
        self.assertTrue(result["ready_for_execution"])
        self.assertTrue((self.root / "ssot-project.json").is_file())
        seed = json.loads(
            (
                self.root
                / ".trusted-project"
                / "projects"
                / project_id
                / "ssot"
                / "unresolved-seed.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(seed["requirements"][0]["disposition"], "unresolved")
        self.assertEqual(seed["stages"], [])
        self.assertTrue(compile_ssot(self.root, project_id, contract)["idempotent"])
        held = request_execution(self.root, project_id)
        self.assertEqual(held["state"], "held_execution")

    def test_compiled_project_executes_hard_path_and_reaches_tested(self):
        budget = {
            "model_tokens": 0,
            "cost_usd": 0,
            "wall_seconds": 60,
            "outer_attempts": 2,
            "research_sources": 0,
            "storage_bytes": 100000,
            "external_side_effects": 0,
        }
        project_id, contract, _candidate, _verifiers = self._compiler_candidate(
            budget=budget
        )
        compile_ssot(self.root, project_id, contract)
        result = request_execution(self.root, project_id)
        self.assertEqual(result["state"], "tested")
        self.assertEqual(result["authority"], "tested")
        self.assertEqual(result["execution_receipts"], 1)
        self.assertEqual(result["usage"]["outer_attempts"], 1)
        self.assertTrue(result["ssot"]["accepted"])
        self.assertTrue((self.root / "enforcement-receipt.json").is_file())
        self.assertEqual(request_execution(self.root, project_id)["state"], "tested")

    def test_direct_output_bypass_does_not_create_completion_authority(self):
        project_id, contract, _candidate, _verifiers = self._compiler_candidate()
        compile_ssot(self.root, project_id, contract)
        (self.root / "result.json").write_text("{}\n", encoding="utf-8")
        status = project_status(self.root, project_id)
        self.assertEqual(status["state"], "configured")
        self.assertFalse(status["ssot"]["stages_verified"])

    def test_budget_exhaustion_holds_before_project_acceptance(self):
        budget = {
            "model_tokens": 0,
            "cost_usd": 0,
            "wall_seconds": 60,
            "outer_attempts": 2,
            "research_sources": 0,
            "storage_bytes": 1,
            "external_side_effects": 0,
        }
        project_id, contract, _candidate, _verifiers = self._compiler_candidate(
            budget=budget
        )
        compile_ssot(self.root, project_id, contract)
        result = request_execution(self.root, project_id)
        self.assertEqual(result["state"], "held_budget_exhausted")
        self.assertIn("storage_bytes", result["budget_exceeded"])
        self.assertFalse(result["ssot"]["accepted"])

    def test_external_effect_requires_fresh_exact_authorization(self):
        budget = {
            "model_tokens": 0,
            "cost_usd": 0,
            "wall_seconds": 60,
            "outer_attempts": 2,
            "research_sources": 0,
            "storage_bytes": 100000,
            "external_side_effects": 1,
        }
        project_id, contract, candidate_path, verifiers = self._compiler_candidate(
            budget=budget
        )
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        candidate["stages"][0]["action"]["effects"] = ["external_message"]
        self._write_json(candidate_path, candidate)
        verifier_value = json.loads(verifiers.read_text(encoding="utf-8"))
        verifier_value["candidate_manifest_sha256"] = self._sha(candidate_path)
        self._write_json(verifiers, verifier_value)
        compile_ssot(self.root, project_id, contract)
        held = request_execution(self.root, project_id)
        self.assertEqual(held["state"], "held_execution")
        now = datetime.now(timezone.utc)
        authorization = {
            "schema_version": 1,
            "project_id": project_id,
            "stage_id": "build",
            "effects": ["external_message"],
            "authorized_by": "test-user",
            "issued_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(minutes=10))
            .isoformat()
            .replace("+00:00", "Z"),
        }
        self._write_json(self.root / "effect-authorization.json", authorization)
        result = request_execution(
            self.root,
            project_id,
            authorizations={"build": Path("effect-authorization.json")},
        )
        self.assertEqual(result["state"], "tested")
        self.assertEqual(result["usage"]["external_side_effects"], 1)

    def test_interrupted_ssot_work_order_is_abandoned_then_resumed(self):
        budget = {
            "model_tokens": 0,
            "cost_usd": 0,
            "wall_seconds": 60,
            "outer_attempts": 2,
            "research_sources": 0,
            "storage_bytes": 100000,
            "external_side_effects": 0,
        }
        project_id, contract, _candidate, _verifiers = self._compiler_candidate(
            budget=budget
        )
        compile_ssot(self.root, project_id, contract)
        runtime = {
            "kind": "script",
            "executor": "interrupted-test",
            "harness": "test",
            "harness_version": "1",
            "host_observed": True,
            "attempt": 1,
            "fallback_from": None,
        }
        stale = prepare_work(self.root, "build", "chosen-harness-worker", runtime)
        result = request_execution(self.root, project_id)
        self.assertEqual(result["state"], "tested")
        self.assertTrue(
            (self.root / ".ssot" / "abandoned" / f"{stale['run_id']}.json").is_file()
        )

    def test_budget_and_execution_receipt_drift_fail_closed(self):
        budget = {
            "model_tokens": 0,
            "cost_usd": 0,
            "wall_seconds": 60,
            "outer_attempts": 2,
            "research_sources": 0,
            "storage_bytes": 100000,
            "external_side_effects": 0,
        }
        project_id, contract, _candidate, _verifiers = self._compiler_candidate(
            budget=budget
        )
        compile_ssot(self.root, project_id, contract)
        (self.root / "budget.json").write_text("{}\n", encoding="utf-8")
        self.assertEqual(project_status(self.root, project_id)["state"], "held_target_drift")

        self.temporary.cleanup()
        self.setUp()
        project_id, contract, _candidate, _verifiers = self._compiler_candidate(
            budget=budget
        )
        compile_ssot(self.root, project_id, contract)
        request_execution(self.root, project_id)
        receipt = (
            self.root
            / ".trusted-project"
            / "projects"
            / project_id
            / "execution"
            / "build.json"
        )
        value = json.loads(receipt.read_text(encoding="utf-8"))
        value["usage"]["outer_attempts"] = 0
        self._write_json(receipt, value)
        with self.assertRaisesRegex(ProjectError, "execution event receipt hash changed"):
            project_status(self.root, project_id)

    def test_compiler_requires_declared_usage_and_effects(self):
        project_id, contract, candidate_path, _verifiers = self._compiler_candidate()
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        del candidate["stages"][0]["action"]["effects"]
        self._write_json(candidate_path, candidate)
        with self.assertRaisesRegex(ProjectError, "action fields"):
            compile_ssot(self.root, project_id, contract)

    def test_host_metered_profile_is_reused_but_held_until_live_adapter(self):
        budget = {
            "model_tokens": 1000,
            "cost_usd": 1,
            "wall_seconds": 60,
            "outer_attempts": 2,
            "research_sources": 0,
            "storage_bytes": 100000,
            "external_side_effects": 0,
        }
        project_id, contract, candidate_path, verifiers = self._compiler_candidate(
            budget=budget
        )
        profile = self.root / "runtime-profile.json"
        self._write_json(profile, {"host": "unproved-test-host"})
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        action = candidate["stages"][0]["action"]
        action["usage_mode"] = "host_metered"
        action["runtime_profile"] = "runtime-profile.json"
        action["runtime_profile_sha256"] = self._sha(profile)
        self._write_json(candidate_path, candidate)
        verifier_value = json.loads(verifiers.read_text(encoding="utf-8"))
        verifier_value["candidate_manifest_sha256"] = self._sha(candidate_path)
        self._write_json(verifiers, verifier_value)
        compile_ssot(self.root, project_id, contract)
        held = request_execution(self.root, project_id)
        self.assertEqual(held["state"], "held_execution")
        self.assertIn("metered host adapter", held["next_allowed_action"])
        self._write_json(profile, {"host": "drifted"})
        with self.assertRaisesRegex(ProjectError, "runtime profile hash changed"):
            project_status(self.root, project_id)

    def test_compiler_rejects_missing_reviewed_requirement(self):
        project_id, contract, candidate_path, verifiers = self._compiler_candidate(
            two_requirements=True
        )
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        candidate["requirements"].pop()
        candidate["stages"][0]["requirements"].pop()
        candidate["stages"][0]["properties"] = candidate["requirements"][0][
            "acceptance_evidence"
        ]
        self._write_json(candidate_path, candidate)
        verifier_value = json.loads(verifiers.read_text(encoding="utf-8"))
        verifier_value["candidate_manifest_sha256"] = self._sha(candidate_path)
        self._write_json(verifiers, verifier_value)
        with self.assertRaisesRegex(ProjectError, "coverage mismatch"):
            compile_ssot(self.root, project_id, contract)

    def test_compiler_rejects_duplicate_stage_ownership(self):
        project_id, contract, candidate_path, verifiers = self._compiler_candidate()
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        duplicate = dict(candidate["stages"][0])
        duplicate["id"] = "duplicate"
        duplicate["outputs"] = ["duplicate.json"]
        duplicate["trace_output"] = "duplicate-trace.json"
        duplicate["outputs"] = [
            "duplicate.json",
            "duplicate-enforcement-receipt.json",
            "duplicate-trace.json",
        ]
        duplicate["action"] = dict(duplicate["action"])
        duplicate["action"]["producer"] = "duplicate-worker"
        duplicate["action"]["verifier_owner"] = "duplicate-task-verifier"
        duplicate["action"]["receipt_output"] = "duplicate-enforcement-receipt.json"
        duplicate["verifier"] = dict(duplicate["verifier"])
        duplicate["verifier"]["owner"] = "duplicate-verifier"
        candidate["stages"].append(duplicate)
        self._write_json(candidate_path, candidate)
        verifier_value = json.loads(verifiers.read_text(encoding="utf-8"))
        verifier_value["candidate_manifest_sha256"] = self._sha(candidate_path)
        self._write_json(verifiers, verifier_value)
        with self.assertRaisesRegex(ProjectError, "multiple stage owners"):
            compile_ssot(self.root, project_id, contract)

    def test_generated_verifier_cannot_claim_promotion(self):
        project_id, contract, _candidate, verifiers = self._compiler_candidate()
        value = json.loads(verifiers.read_text(encoding="utf-8"))
        value["status"] = "promoted"
        self._write_json(verifiers, value)
        with self.assertRaisesRegex(ProjectError, "untrusted_drafts"):
            compile_ssot(self.root, project_id, contract)

    def test_compiler_requires_real_enforcement_action(self):
        project_id, contract, candidate_path, _verifiers = self._compiler_candidate()
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        del candidate["stages"][0]["action"]
        self._write_json(candidate_path, candidate)
        with self.assertRaisesRegex(ProjectError, "action fields"):
            compile_ssot(self.root, project_id, contract)

    def test_compiler_rejects_enforcement_contract_drift(self):
        project_id, contract, _candidate, _verifiers = self._compiler_candidate()
        task = self.root / "candidate" / "build-task.json"
        task.write_text(task.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ProjectError, "contract hash changed"):
            compile_ssot(self.root, project_id, contract)

    def test_compiler_requires_action_receipt_and_trace_outputs(self):
        project_id, contract, candidate_path, _verifiers = self._compiler_candidate()
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        candidate["stages"][0]["outputs"].remove("enforcement-receipt.json")
        self._write_json(candidate_path, candidate)
        with self.assertRaisesRegex(ProjectError, "controller evidence|omit enforcement"):
            compile_ssot(self.root, project_id, contract)

    def test_verifier_candidate_drift_is_rejected(self):
        project_id, contract, _candidate, verifiers = self._compiler_candidate()
        value = json.loads(verifiers.read_text(encoding="utf-8"))
        value["verifiers"][0]["owner"] = "invented-owner"
        self._write_json(verifiers, value)
        with self.assertRaisesRegex(ProjectError, "exactly bind every verifier"):
            compile_ssot(self.root, project_id, contract)

    def test_ssot_reviewer_must_be_independent(self):
        project_id, contract_path, _candidate, _verifiers = self._compiler_candidate()
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["reviewer"]["owner"] = contract["compiler_identity"]
        self._write_json(contract_path, contract)
        with self.assertRaisesRegex(ProjectError, "distinct from drafter"):
            compile_ssot(self.root, project_id, contract_path)

    def test_ssot_reviewer_cannot_mutate_target(self):
        project_id, contract_path, _candidate, _verifiers = self._compiler_candidate()
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["reviewer"]["argv"].append("--mutate")
        self._write_json(contract_path, contract)
        with self.assertRaisesRegex(ProjectError, "changed project files"):
            compile_ssot(self.root, project_id, contract_path)

    def test_ssot_that_appears_after_activation_is_not_overwritten(self):
        project_id, contract, _candidate, _verifiers = self._compiler_candidate()
        appeared = self.root / "ssot-project.json"
        appeared.write_text('{"owner":"other"}\n', encoding="utf-8")
        with self.assertRaisesRegex(ProjectError, "held_target_drift"):
            compile_ssot(self.root, project_id, contract)
        self.assertEqual(appeared.read_text(encoding="utf-8"), '{"owner":"other"}\n')

    def test_post_compile_verifier_drift_fails_status(self):
        project_id, contract, _candidate, _verifiers = self._compiler_candidate()
        compile_ssot(self.root, project_id, contract)
        (self.root / "verify_stage.py").write_text(
            "# drift\nraise SystemExit(0)\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(ProjectError, "verifier candidates do not exactly bind"):
            project_status(self.root, project_id)

    def test_post_compile_root_manifest_drift_fails_status(self):
        project_id, contract, _candidate, _verifiers = self._compiler_candidate()
        compile_ssot(self.root, project_id, contract)
        (self.root / "ssot-project.json").write_text('{"forged":true}\n', encoding="utf-8")
        with self.assertRaisesRegex(ProjectError, "root SSOT (size|hash) changed"):
            project_status(self.root, project_id)

    def test_interrupted_ssot_publication_recovers_absent_only(self):
        project_id, contract, _candidate, _verifiers = self._compiler_candidate()
        compile_ssot(self.root, project_id, contract)
        (self.root / "ssot-project.json").unlink()
        event = (
            self.root
            / ".trusted-project"
            / "projects"
            / project_id
            / "events"
            / "000003-ssot_compiled.json"
        )
        event.unlink()
        recovered = compile_ssot(self.root, project_id, contract)
        self.assertEqual(recovered["state"], "configured")
        self.assertTrue(recovered["idempotent"])
        self.assertTrue((self.root / "ssot-project.json").is_file())
        restored_event = json.loads(event.read_text(encoding="utf-8"))
        self.assertTrue(restored_event["details"]["recovered_after_publish"])


if __name__ == "__main__":
    unittest.main()
