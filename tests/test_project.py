import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from harness.project import (
    ProjectError,
    abandon_project,
    create_intent,
    project_status,
    request_execution,
    resume_project,
)


class TrustedProjectActivationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "AGENTS.md").write_text("# Target rules\n", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def test_plan_captures_exact_immutable_intent_and_is_idempotent(self):
        result = create_intent(
            self.root,
            "Build a small parser.",
            "plan",
            constraints=["Use Python"],
            open_decisions=["Output format"],
        )
        self.assertEqual(result["state"], "held_open_decisions")
        self.assertEqual(result["authority"], "intent_only")
        self.assertFalse(result["ready_for_execution"])
        project = self.root / ".trusted-project" / "projects" / result["project_id"]
        intent = json.loads((project / "intent.json").read_text(encoding="utf-8"))
        self.assertEqual(intent["request"]["text"], "Build a small parser.")
        self.assertEqual(intent["constraints"], ["Use Python"])
        before = (project / "intent.json").read_bytes()
        repeated = create_intent(
            self.root,
            "Build a small parser.",
            "plan",
            constraints=["Use Python"],
            open_decisions=["Output format"],
        )
        self.assertTrue(repeated["idempotent"])
        self.assertEqual((project / "intent.json").read_bytes(), before)
        self.assertEqual(repeated["event_count"], 1)

    def test_existing_ssot_is_bound_for_reuse(self):
        (self.root / "ssot-project.json").write_text("{}\n", encoding="utf-8")
        result = create_intent(self.root, "Extend the project", "plan")
        self.assertEqual(result["ssot_mode"], "reuse_existing")

    def test_execute_is_supported_but_fails_closed_before_prd(self):
        result = request_execution(self.root, "Build the requested utility")
        self.assertEqual(result["state"], "held_prd_not_reviewed")
        self.assertEqual(result["authority"], "no_execution_authority")
        self.assertFalse(result["ready_for_execution"])

    def test_authority_surface_drift_holds_resume(self):
        result = create_intent(self.root, "Inspect this target", "plan")
        (self.root / "AGENTS.md").write_text("# Changed rules\n", encoding="utf-8")
        status = project_status(self.root, result["project_id"])
        self.assertEqual(status["state"], "held_target_drift")
        self.assertFalse(resume_project(self.root, result["project_id"])["resumed"])

    def test_abandon_is_immutable_idempotent_and_cannot_resume(self):
        result = create_intent(self.root, "Stop this safely", "plan")
        project_id = result["project_id"]
        abandoned = abandon_project(self.root, project_id, "No longer required")
        self.assertEqual(abandoned["state"], "abandoned")
        self.assertEqual(abandoned["event_count"], 2)
        repeated = abandon_project(self.root, project_id, "No longer required")
        self.assertTrue(repeated["idempotent"])
        self.assertEqual(repeated["event_count"], 2)
        with self.assertRaisesRegex(ProjectError, "cannot resume"):
            resume_project(self.root, project_id)

    def test_event_tamper_fails_closed(self):
        result = create_intent(self.root, "Keep the event chain", "plan")
        event = next(
            (
                self.root
                / ".trusted-project"
                / "projects"
                / result["project_id"]
                / "events"
            ).glob("*.json")
        )
        value = json.loads(event.read_text(encoding="utf-8"))
        value["details"]["status"] = "tested"
        event.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ProjectError, "event chain is invalid"):
            project_status(self.root, result["project_id"])

    def test_budget_file_is_exact_and_target_bound(self):
        budget = {
            "model_tokens": 5000,
            "cost_usd": 2.5,
            "wall_seconds": 600,
            "outer_attempts": 3,
            "research_sources": 8,
            "storage_bytes": 10_000_000,
            "external_side_effects": 0,
        }
        (self.root / "budget.json").write_text(json.dumps(budget), encoding="utf-8")
        result = create_intent(
            self.root, "Plan within budget", "plan", budget_file=Path("budget.json")
        )
        intent_path = (
            self.root
            / ".trusted-project"
            / "projects"
            / result["project_id"]
            / "intent.json"
        )
        intent = json.loads(intent_path.read_text(encoding="utf-8"))
        self.assertEqual(intent["budgets"]["values"], budget)
        with self.assertRaisesRegex(ProjectError, "escapes target"):
            create_intent(
                self.root,
                "Bad budget",
                "plan",
                budget_file=self.root.parent / "outside.json",
            )

    def test_cli_plan_and_status_use_the_same_protocol(self):
        repository = Path(__file__).resolve().parents[1]
        planned = subprocess.run(
            [
                sys.executable,
                "-m",
                "harness.project",
                "plan",
                "Build through the installed skill",
                "--root",
                str(self.root),
            ],
            cwd=repository,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(planned.returncode, 0, planned.stderr)
        value = json.loads(planned.stdout)
        status = subprocess.run(
            [
                sys.executable,
                "-m",
                "harness.project",
                "status",
                value["project_id"],
                "--root",
                str(self.root),
            ],
            cwd=repository,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(json.loads(status.stdout)["state"], "intent_captured")

    def test_thin_skill_calls_the_executable_protocol(self):
        skill = (
            Path(__file__).resolve().parents[1]
            / "harness"
            / "templates"
            / "trusted-project-skill.md"
        ).read_text(encoding="utf-8")
        self.assertIn('trusted-project plan "REQUEST" --root TARGET', skill)
        self.assertIn("executable state is authoritative", skill)
        self.assertIn("Do not intercept ordinary tasks", skill)

    def test_malformed_intent_fails_closed(self):
        result = create_intent(self.root, "Protect intent fields", "plan")
        intent = (
            self.root
            / ".trusted-project"
            / "projects"
            / result["project_id"]
            / "intent.json"
        )
        value = json.loads(intent.read_text(encoding="utf-8"))
        del value["authority"]
        intent.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ProjectError, "missing required field"):
            project_status(self.root, result["project_id"])


if __name__ == "__main__":
    unittest.main()
