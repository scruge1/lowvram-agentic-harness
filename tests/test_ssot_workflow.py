import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ssot.control import SSOTError, project_status
from ssot.workflow import doctor_project, init_project, next_work, run_stage_command


SOURCE_EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "ssot-starter"
SCRIPT_RUNTIME = {
    "kind": "script",
    "executor": "workflow-test",
    "harness": "subprocess",
    "harness_version": "stdlib",
    "host_observed": True,
    "attempt": 1,
    "fallback_from": None,
}


class WorkflowExperienceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def _copy_configured_example(self):
        shutil.copytree(SOURCE_EXAMPLE, self.root, dirs_exist_ok=True)

    def test_init_is_source_bound_but_deliberately_not_ready(self):
        (self.root / "PRD.md").write_text("# Product\n\nBuild it.\n", encoding="utf-8")
        result = init_project(self.root, "PRD.md", "new-product")
        self.assertEqual(result["state"], "scaffolded")
        self.assertFalse(result["ready"])
        diagnosis = doctor_project(self.root)
        self.assertFalse(diagnosis["ready"])
        self.assertIn("REQ-UNRESOLVED-001", diagnosis["unresolved_requirements"])
        with self.assertRaisesRegex(SSOTError, "refusing to overwrite"):
            init_project(self.root, "PRD.md", "replacement")

    def test_doctor_and_next_expose_configured_frontier(self):
        self._copy_configured_example()
        diagnosis = doctor_project(self.root)
        self.assertTrue(diagnosis["ready"], diagnosis["issues"])
        packet = next_work(self.root)
        self.assertEqual(packet["count"], 1)
        self.assertEqual(packet["frontier"][0]["stage_id"], "plan")
        self.assertEqual(packet["frontier"][0]["authority"], "preview_only")

    def test_host_runner_executes_records_and_verifies_stage(self):
        self._copy_configured_example()
        command = [
            sys.executable,
            "-c",
            (
                "import json; from pathlib import Path; "
                "Path('artifacts').mkdir(exist_ok=True); "
                "Path('artifacts/plan.json').write_text("
                "json.dumps({'project':'starter','steps':['build']})+'\\n')"
            ),
        ]
        result = run_stage_command(
            self.root, "plan", "external-harness", SCRIPT_RUNTIME, command
        )
        self.assertEqual(result["status"], "verified")
        self.assertTrue((self.root / "artifacts" / "plan-run-trace.json").is_file())
        status = project_status(self.root)
        states = {row["id"]: row["state"] for row in status["stages"]}
        self.assertEqual(states, {"plan": "verified", "build": "frontier"})

    def test_host_runner_abandons_failed_process(self):
        self._copy_configured_example()
        result = run_stage_command(
            self.root,
            "plan",
            "external-harness",
            SCRIPT_RUNTIME,
            [sys.executable, "-c", "raise SystemExit(3)"],
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 3)
        run_id = result["run_id"]
        self.assertTrue(
            (self.root / ".ssot" / "abandoned" / f"{run_id}.json").is_file()
        )
        self.assertEqual(project_status(self.root)["stages"][0]["state"], "frontier")

    def test_host_runner_abandons_command_that_cannot_start(self):
        self._copy_configured_example()
        result = run_stage_command(
            self.root,
            "plan",
            "external-harness",
            SCRIPT_RUNTIME,
            [str(self.root / "missing-executable")],
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 127)
        self.assertTrue(
            (self.root / ".ssot" / "abandoned" / f"{result['run_id']}.json").is_file()
        )

    def test_cli_run_keeps_options_out_of_host_command(self):
        self._copy_configured_example()
        runtime_file = self.root / "runtime-script.json"
        command = [
            sys.executable,
            "-m",
            "ssot.cli",
            "--root",
            str(self.root),
            "run",
            "plan",
            "--worker",
            "external-harness",
            "--runtime-file",
            str(runtime_file),
            "--",
            sys.executable,
            "-c",
            (
                "import json; from pathlib import Path; "
                "Path('artifacts').mkdir(exist_ok=True); "
                "Path('artifacts/plan.json').write_text("
                "json.dumps({'project':'starter','steps':['build']})+'\\n')"
            ),
        ]
        completed = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "verified")

    def test_host_runner_holds_worker_that_changes_control_state(self):
        self._copy_configured_example()
        command = [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; "
                "Path('.ssot/worker-write').write_text('unauthorized')"
            ),
        ]
        with self.assertRaisesRegex(SSOTError, "changed protected .ssot"):
            run_stage_command(
                self.root, "plan", "untrusted-worker", SCRIPT_RUNTIME, command
            )


if __name__ == "__main__":
    unittest.main()
