import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from harness.enforcement import (
    EnforcementError,
    _run_command,
    doctor,
    handle_hook,
    run_task,
    validate_contract,
    verify_receipt,
)


class EnforcementTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self._write(
            "worker.py",
            """import os
from pathlib import Path
attempt = int(os.environ['ENFORCEMENT_ATTEMPT'])
feedback = Path(os.environ['ENFORCEMENT_FEEDBACK_FILE']).read_text()
Path('artifacts').mkdir(exist_ok=True)
value = 'accepted with feedback' if attempt > 1 and 'rejected' in feedback else 'rejected'
Path('artifacts/result.txt').write_text(value + '\\n')
""",
        )
        self._write(
            "verify.py",
            """import sys
from pathlib import Path
if '--negative-control' in sys.argv:
    raise SystemExit(0)
value = Path('artifacts/result.txt').read_text()
raise SystemExit(0 if value == 'accepted with feedback\\n' else 1)
""",
        )
        self._write(
            "research.py",
            """import json
print(json.dumps({
  'verdict': 'grounded',
  'source_records': [
    {'url': 'https://a.example/fact', 'sha256': 'a' * 64, 'chars': 40},
    {'url': 'https://b.example/fact', 'sha256': 'b' * 64, 'chars': 48}
  ],
  'consensus': [{
    'claim': 'The test fact is supported.',
    'citations': ['https://a.example/fact', 'https://b.example/fact'],
    'evidence': [
      {'url': 'https://a.example/fact', 'quote': 'The supported test fact appears here.'},
      {'url': 'https://b.example/fact', 'quote': 'The test fact is independently supported here.'}
    ]
  }]
}))
""",
        )
        self.spec = {
            "schema_version": 1,
            "task_id": "enforcement-test",
            "objective": "Produce the independently verified result.",
            "worker": {
                "argv": ["{python}", "worker.py"],
                "files": ["worker.py"],
                "timeout_seconds": 30,
            },
            "outputs": ["artifacts/result.txt"],
            "receipt_output": "artifacts/enforcement-receipt.json",
            "retry": {
                "max_attempts": 3,
                "retry_on": [
                    "process_failure",
                    "tool_failure",
                    "verification_failure",
                ],
                "backoff_seconds": [0],
                "inner_tool_max_attempts": 2,
            },
            "research": {
                "required": True,
                "argv": ["{python}", "research.py"],
                "files": ["research.py"],
                "receipt_output": "artifacts/research-receipt.json",
                "min_sources": 2,
                "timeout_seconds": 30,
            },
            "verifier": {
                "argv": ["{python}", "verify.py"],
                "negative_control": {
                    "argv": ["{python}", "verify.py", "--negative-control"],
                    "files": ["verify.py"],
                    "timeout_seconds": 30,
                },
                "files": ["verify.py"],
                "timeout_seconds": 30,
            },
        }
        self.spec_path = self.root / "task.json"
        self._save_spec()

    def tearDown(self):
        self.temporary.cleanup()

    def _write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _save_spec(self):
        self.spec_path.write_text(
            json.dumps(self.spec, indent=2) + "\n", encoding="utf-8"
        )

    def test_doctor_and_contract_reject_shell_string(self):
        self.assertTrue(doctor(self.root, self.spec_path)["ready"])
        self.spec["worker"]["argv"] = "python worker.py"
        self._save_spec()
        diagnosis = doctor(self.root, self.spec_path)
        self.assertFalse(diagnosis["ready"])
        self.assertIn("non-empty list", diagnosis["issues"][0])

    def test_command_observation_distinguishes_actual_exit_and_host_failure(self):
        cases = [
            ([sys.executable, "-c", "raise SystemExit(124)"], "exited", 124, 124),
            ([sys.executable, "-c", "raise SystemExit(127)"], "exited", 127, 127),
            ([str(self.root / "missing-executable")], "os_error", None, 127),
            ([sys.executable, "-c", "import time; time.sleep(10)"], "timed_out", None, 124),
        ]
        for argv, outcome, observed_exit, legacy_code in cases:
            with self.subTest(outcome=outcome, observed_exit=observed_exit):
                process = _run_command(self.root, {"argv": argv, "timeout_seconds": 1}, {}, {})
                self.assertEqual(process["exit_code"], legacy_code)
                self.assertEqual(process["process_observation"], {
                    "outcome": outcome,
                    "observed_exit_code": observed_exit,
                    "duration_ms": process["duration_ms"],
                    "descendant_quiescence": "unknown",
                })
                self.assertGreaterEqual(process["duration_ms"], 0)

    def test_negative_control_must_use_same_distinct_program(self):
        self.spec["verifier"]["negative_control"]["argv"] = [
            "{python}",
            "other.py",
        ]
        self._write("other.py", "raise SystemExit(0)\n")
        self._save_spec()
        with self.assertRaisesRegex(EnforcementError, "same verifier"):
            validate_contract(self.root, self.spec)

    def test_research_then_feedback_retry_reaches_accepted_receipt(self):
        receipt = run_task(self.root, self.spec_path)
        self.assertEqual(receipt["status"], "accepted")
        self.assertEqual(receipt["accepted_attempt"], 2)
        trace_path = self.root / receipt["attempts"][-1]["process_trace"]
        observation = json.loads(trace_path.read_text(encoding="utf-8"))["process_observation"]
        self.assertEqual(observation["outcome"], "exited")
        self.assertEqual(observation["observed_exit_code"], 0)
        self.assertEqual(receipt["attempts"][0]["issue_class"], "verification_failure")
        self.assertEqual(receipt["research"]["min_sources"], 2)
        self.assertTrue((self.root / self.spec["receipt_output"]).is_file())
        self.assertEqual(
            (self.root / "artifacts/result.txt").read_text(encoding="utf-8"),
            "accepted with feedback\n",
        )
        verified = verify_receipt(
            self.root,
            self.spec_path,
            self.root / self.spec["receipt_output"],
        )
        self.assertEqual(verified["status"], "verified")
        with self.assertRaisesRegex(EnforcementError, "contract hash"):
            verify_receipt(
                self.root,
                self.spec_path,
                self.root / self.spec["receipt_output"],
                negative_control=True,
            )
        self._write("artifacts/result.txt", "drifted\n")
        with self.assertRaisesRegex(EnforcementError, "output bytes"):
            verify_receipt(
                self.root,
                self.spec_path,
                self.root / self.spec["receipt_output"],
            )

    def test_ungrounded_research_prevents_worker_execution(self):
        self._write("research.py", 'print(\'{"verdict":"ungrounded"}\')\n')
        receipt = run_task(self.root, self.spec_path)
        self.assertEqual(receipt["status"], "failed")
        self.assertIn("research rejected", receipt["reason"])
        self.assertFalse((self.root / "artifacts/result.txt").exists())

    def test_unchanged_output_cannot_pass_as_current_attempt(self):
        self._write("artifacts/result.txt", "accepted with feedback\n")
        self._write("worker.py", "raise SystemExit(0)\n")
        self.spec["retry"]["max_attempts"] = 1
        self.spec["research"] = {"required": False}
        self._save_spec()
        receipt = run_task(self.root, self.spec_path)
        self.assertEqual(receipt["status"], "failed")
        self.assertIn("not produced", receipt["reason"])

    def test_worker_cannot_rewrite_its_verifier(self):
        self._write(
            "worker.py",
            """from pathlib import Path
Path('verify.py').write_text('raise SystemExit(0)\\n')
Path('artifacts').mkdir(exist_ok=True)
Path('artifacts/result.txt').write_text('accepted with feedback\\n')
""",
        )
        self.spec["retry"]["max_attempts"] = 1
        self.spec["research"] = {"required": False}
        self._save_spec()
        receipt = run_task(self.root, self.spec_path)
        self.assertEqual(receipt["status"], "failed")
        self.assertIn("protected control file changed", receipt["reason"])

    def test_hook_blocks_completion_until_failed_tool_succeeds(self):
        event_dir = self.root / ".enforcement" / "hook-test"
        research_path = self.root / "artifacts/research-receipt.json"
        environment = {
            "ENFORCEMENT_HOOK_EVENT_DIR": str(event_dir),
            "ENFORCEMENT_POLICY_FILE": str(self.spec_path),
            "ENFORCEMENT_TASK_ROOT": str(self.root),
            "ENFORCEMENT_RESEARCH_RECEIPT": str(research_path),
        }
        self._write(
            "artifacts/research-receipt.json",
            json.dumps(
                {
                    "verdict": "grounded",
                    "source_records": [
                        {"url": "https://a", "sha256": "a" * 64, "chars": 8},
                        {"url": "https://b", "sha256": "b" * 64, "chars": 8},
                    ],
                    "consensus": [
                        {
                            "claim": "fact",
                            "citations": ["https://a", "https://b"],
                            "evidence": [
                                {"quote": "evidence a", "url": "https://a"},
                                {"quote": "evidence b", "url": "https://b"},
                            ],
                        }
                    ],
                }
            ),
        )
        environment["ENFORCEMENT_RESEARCH_SHA256"] = hashlib.sha256(
            research_path.read_bytes()
        ).hexdigest()
        handle_hook(
            "normalized",
            {
                "event_type": "tool_result",
                "status": "failed",
                "tool_name": "web_search",
                "tool_input": {"query": "secret query"},
                "error_summary": "temporary network failure",
            },
            environment,
        )
        blocked = handle_hook(
            "normalized", {"event_type": "completion_check"}, environment
        )
        self.assertFalse(blocked["allow"])
        self.assertIn("web_search", blocked["reason"])
        handle_hook(
            "normalized",
            {
                "event_type": "tool_result",
                "status": "success",
                "tool_name": "web_search",
                "tool_input": {"query": "corrected query"},
            },
            environment,
        )
        self.assertEqual(
            handle_hook("normalized", {"event_type": "completion_check"}, environment),
            {},
        )
        event_text = "\n".join(path.read_text() for path in event_dir.glob("*.json"))
        self.assertNotIn("secret query", event_text)

    def test_research_requires_hashed_source_records(self):
        self._write(
            "research.py",
            'print(\'{"verdict":"grounded","consensus":[]}\')\n',
        )
        receipt = run_task(self.root, self.spec_path)
        self.assertEqual(receipt["status"], "failed")
        self.assertIn("source_records", receipt["reason"])

    def test_claude_and_hermes_completion_directives_are_native(self):
        event_dir = self.root / ".enforcement" / "native-hooks"
        environment = {
            "ENFORCEMENT_HOOK_EVENT_DIR": str(event_dir),
            "ENFORCEMENT_POLICY_FILE": str(self.spec_path),
            "ENFORCEMENT_TASK_ROOT": str(self.root),
            "ENFORCEMENT_RESEARCH_RECEIPT": "",
        }
        claude = handle_hook("claude", {"hook_event_name": "Stop"}, environment)
        self.assertEqual(claude["decision"], "block")
        hermes = handle_hook("hermes", {"hook_event_name": "pre_verify"}, environment)
        self.assertEqual(hermes["action"], "continue")

    def test_adapter_templates_cover_failure_and_completion_events(self):
        repository = Path(__file__).resolve().parents[1]
        claude = json.loads(
            (repository / "adapters/claude-code/settings.example.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            set(claude["hooks"]), {"PostToolUse", "PostToolUseFailure", "Stop"}
        )
        self.assertTrue(
            all(
                "trusted-task hook --host claude" in json.dumps(event_configuration)
                for event_configuration in claude["hooks"].values()
            )
        )
        hermes = (repository / "adapters/hermes/config.example.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn("post_tool_call:", hermes)
        self.assertIn("pre_verify:", hermes)
        self.assertIn("trusted-task hook --host hermes", hermes)
        pi = (repository / "adapters/pi/enforcement.ts").read_text(encoding="utf-8")
        self.assertIn('pi.on("tool_execution_start"', pi)
        self.assertIn('pi.on("tool_execution_end"', pi)
        self.assertIn("pendingInputs.get(event.toolCallId)", pi)
        self.assertIn("tool_call_id: event.toolCallId", pi)
        self.assertNotIn("tool_input: event.args", pi)
        self.assertIn('pi.on("agent_settled"', pi)
        self.assertIn('"completion_check"', pi)

    def test_inner_retry_prompt_has_a_finite_budget(self):
        self.spec["research"] = {"required": False}
        self.spec["retry"]["inner_tool_max_attempts"] = 1
        self._save_spec()
        event_dir = self.root / ".enforcement" / "finite-hook"
        environment = {
            "ENFORCEMENT_HOOK_EVENT_DIR": str(event_dir),
            "ENFORCEMENT_POLICY_FILE": str(self.spec_path),
            "ENFORCEMENT_TASK_ROOT": str(self.root),
            "ENFORCEMENT_RESEARCH_RECEIPT": "",
        }
        handle_hook(
            "normalized",
            {
                "event_type": "tool_result",
                "status": "failed",
                "tool_name": "read",
                "tool_input": {"path": "missing"},
                "error_summary": "missing",
            },
            environment,
        )
        self.assertFalse(
            handle_hook("normalized", {"event_type": "completion_check"}, environment)[
                "allow"
            ]
        )
        self.assertEqual(
            handle_hook("normalized", {"event_type": "completion_check"}, environment),
            {},
        )


if __name__ == "__main__":
    unittest.main()
