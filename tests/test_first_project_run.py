"""Real preparation/checking with an explicit mocked agent; no model or service."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from harness import first_project, home, home_entry, managed_launch


class FirstProjectRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="first-project-run-", dir=os.environ.get("FIRST_PROJECT_TEST_ROOT"))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.agent = self.root / "owned agent"
        (self.agent / "projects").mkdir(parents=True)
        (self.agent / "agent").mkdir()
        self.config = {"schema": "agent-home/v1", "home": str(self.agent), "model": "fixture-model",
                       "installed": {"hermes": {"fixture": True}}}
        (self.agent / "home.json").write_text(json.dumps(self.config))
        (self.agent / "agent/models.json").write_text(json.dumps({"providers": {"local": {"models": [
            {"id": "fixture-model", "contextWindow": 32768, "maxTokens": 4096}]}}}))
        # Registration is real; its target is never executed in these tests.
        (self.agent / "agent-home.py").write_text("# Explicit unused launcher fixture.\n")
        (self.agent / "runtime/harness").mkdir(parents=True)
        (self.agent / "runtime/harness/managed_launch.py").write_bytes(Path(managed_launch.__file__).read_bytes())
        managed_launch.register_command(self.agent, self.agent / "bin")
        self.facts = {
            "ram_total_gb": 32.5, "gpu_vram_mib": None, "storage_total_gb": 1000,
            "configured_model": {"context_tokens": 32768, "output_tokens": 4096},
            "fixture_only": True,
        }

    def report(self, project):
        text = "# Synthetic checker fixture\n\nSource: hardware-facts.json.\n\n"
        text += "| Measurement | Value | Unit |\n| --- | --- | --- |\n"
        for row in first_project._rows(self.facts):
            value = "unknown" if row["value"] is None else str(row["value"])
            text += "| " + row["label"] + " | " + value + " | " + row["unit"] + " |\n"
        text += "\nFixture output only; no model authored this text. Semantic review is separate.\n"
        text += " inventory" * (300 - first_project.word_count(text))
        (project / first_project.OUTPUT).write_text(text, encoding="utf-8")

    @contextlib.contextmanager
    def fixtures(self, child):
        with mock.patch.object(first_project, "_facts", return_value=self.facts), \
             mock.patch.object(home, "check_package", return_value=None), \
             mock.patch.object(home, "board", return_value={"fixture_board_admission": True}) as board, \
             mock.patch.object(home, "launch", side_effect=child) as launch:
            yield launch, board

    def successful_child(self, selected, args, *, project_root):
        self.assertEqual(selected, self.agent)
        self.assertEqual(args[:5], ["--offline", "--mode", "json", "--print", "--"])
        self.assertEqual(len(args), 6)
        self.report(project_root)
        return 0

    def test_single_normal_launch_receives_exact_original_contract_and_checks_independently(self):
        before = (self.agent / "home.json").read_bytes(), (self.agent / "agent/models.json").read_bytes()
        original_check = first_project.check
        with self.fixtures(self.successful_child) as (launch, board), \
             mock.patch.object(first_project, "check", wraps=original_check) as checked:
            result = first_project.run(self.agent, "first-report")
        self.assertEqual(result["status"], "predicates_passed")
        self.assertEqual(result["semantic_review"], "required")
        self.assertEqual(result["model_requests"], "not_counted_by_wrapper")
        self.assertFalse(result["automatic_replay"])
        self.assertEqual(launch.call_count, 1)
        self.assertEqual(board.call_count, 1)
        self.assertTrue(board.call_args.args[1]["initialize"])
        project = Path(result["project_root"])
        self.assertTrue((project / ".git").is_dir())
        prompt = launch.call_args.args[1][-1]
        admission = json.loads(prompt.split("project_admit with EXACTLY this JSON: ", 1)[1].split("\n", 1)[0])
        self.assertEqual(admission, {"project_root": str(project)})
        self.assertIn("host has already created", prompt)
        self.assertIn("do not supply native_authority", prompt)
        self.assertIn("not a project identity hash", prompt)
        self.assertIn("Original manifest SHA-256: " + result["manifest_sha256"], prompt)
        encoded = prompt.split("Original check_argv JSON: ", 1)[1].split("\n", 1)[0]
        self.assertEqual(json.loads(encoded), result["check_argv"])
        checked.assert_called_once_with(project, result["manifest_sha256"])
        self.assertEqual(before, ((self.agent / "home.json").read_bytes(), (self.agent / "agent/models.json").read_bytes()))
        self.assertEqual(result["reopen_argv"][:3], [str(managed_launch.command_file(self.agent / "bin", "harness-agent")),
                                                   "--project", str(project)])
        self.assertEqual("--continue" in result["reopen_argv"], sys.platform == "linux")

    def test_nonzero_child_cannot_become_success_even_when_report_passes(self):
        def child(_home, _args, *, project_root):
            self.report(project_root)
            return 7
        with self.fixtures(child) as (launch, _):
            result = first_project.run(self.agent, "failed-child")
        self.assertEqual(result["launch_exit_code"], 7)
        self.assertTrue(result["check"]["passed"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(launch.call_count, 1)
        self.assertTrue((Path(result["project_root"]) / first_project.OUTPUT).is_file())

    def test_native_text_mode_is_the_only_other_output_selection(self):
        def child(selected, args, *, project_root):
            self.assertEqual(selected, self.agent)
            self.assertEqual(args[:5], ["--offline", "--mode", "text", "--print", "--"])
            self.report(project_root)
            return 0
        with self.fixtures(child) as (launch, _):
            result = first_project.run(self.agent, "text-output", mode="text")
        self.assertEqual(result["status"], "predicates_passed")
        self.assertEqual(launch.call_count, 1)

    def test_missing_report_and_launch_exception_preserve_project_without_retry(self):
        for name, child in [("missing-report", lambda *_a, **_k: 0),
                            ("failed-launch", mock.Mock(side_effect=OSError("fixture launch failed")))]:
            with self.subTest(name=name), self.fixtures(child) as (launch, _):
                result = first_project.run(self.agent, name)
            self.assertEqual(result["status"], "failed")
            self.assertFalse(result["check"]["passed"])
            self.assertEqual(launch.call_count, 1)
            project = Path(result["project_root"])
            self.assertTrue((project / ".git").is_dir())
            self.assertTrue((project / first_project.MANIFEST).is_file())
            if name == "failed-launch":
                self.assertEqual(result["launch_error"], "fixture launch failed")
                self.assertIsNone(result["launch_exit_code"])

    def test_child_contract_replacement_is_checked_against_original_pin(self):
        original = []
        def child(_home, args, *, project_root):
            path = project_root / first_project.MANIFEST
            original.append(first_project.digest(path.read_bytes()))
            path.write_bytes(path.read_bytes() + b"\n")
            self.report(project_root)
            return 0
        with self.fixtures(child):
            result = first_project.run(self.agent, "changed-contract")
        self.assertEqual(result["manifest_sha256"], original[0])
        self.assertEqual(result["check_argv"][-1], original[0])
        self.assertIn("manifest byte drift", result["check"]["error"])
        self.assertEqual(result["status"], "failed")

    def test_existing_project_cannot_be_replayed_and_invalid_mode_has_no_effects(self):
        with self.fixtures(self.successful_child):
            first_project.run(self.agent, "retained")
        project = self.agent / "projects/retained"
        before = {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
        with self.fixtures(self.successful_child) as (launch, _):
            with self.assertRaisesRegex(ValueError, "already exists"):
                first_project.run(self.agent, "retained")
            launch.assert_not_called()
            with self.assertRaises(ValueError):
                first_project.run(self.agent, "never-created", mode="rpc")
        self.assertFalse((self.agent / "projects/never-created").exists())
        self.assertEqual(before, {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()})

    def test_changed_installed_reopen_command_refuses_before_preparation(self):
        managed_launch.command_file(self.agent / "bin", "harness-agent").write_bytes(b"changed")
        with self.fixtures(self.successful_child) as (launch, _), \
             mock.patch.object(first_project, "prepare") as prepare:
            with self.assertRaisesRegex(ValueError, "missing or changed"):
                first_project.run(self.agent, "not-created")
        prepare.assert_not_called()
        launch.assert_not_called()

    def test_cli_from_unrelated_cwd_returns_final_host_report_and_failure_code(self):
        unrelated = self.root / "unrelated"
        unrelated.mkdir()
        previous = Path.cwd()
        try:
            os.chdir(unrelated)
            def streamed(selected, args, *, project_root):
                print('{"fixture_native_stream": "no model call"}')
                return self.successful_child(selected, args, project_root=project_root)
            with self.fixtures(streamed), contextlib.redirect_stdout(io.StringIO()) as output:
                code = first_project.main(["run", "--home", str(self.agent), "--name", "cli-report"])
            self.assertEqual(code, 0)
            native, final = output.getvalue().split("\n", 1)
            self.assertIn("fixture_native_stream", json.loads(native))
            self.assertEqual(json.loads(final)["status"], "predicates_passed")
            self.assertEqual(list(unrelated.iterdir()), [])
            with self.fixtures(lambda *_a, **_k: 0), contextlib.redirect_stdout(io.StringIO()) as output:
                code = first_project.main(["run", "--home", str(self.agent), "--name", "cli-missing"])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(output.getvalue())["status"], "failed")
        finally:
            os.chdir(previous)

    @unittest.skipUnless(sys.platform == "linux", "Actual Linux home lifetime lease")
    def test_outer_home_lease_remains_held_between_prepare_launch_and_final_check(self):
        raw = Path(home_entry.__file__).with_name("home_lifecycle.py").read_bytes()
        (self.agent / "home-lifecycle.py").write_bytes(raw)
        (self.agent / "state").mkdir(exist_ok=True)
        pin = hashlib.sha256(raw).hexdigest()
        self.config["lifecycle_guard_sha256"] = pin
        (self.agent / "home.json").write_text(json.dumps(self.config))
        guard = home_entry._load_guard(self.agent, pin)
        checked = first_project.check
        observed = []
        def exclusive_refuses():
            with self.assertRaises(guard.LeaseBusy):
                with guard.lease(self.agent, expected_sha256=pin, mode="exclusive"):
                    self.fail("Updater entered a live first-project run")
        def child(selected, args, *, project_root):
            exclusive_refuses()
            observed.append("child")
            return self.successful_child(selected, args, project_root=project_root)
        def check(project, expected):
            exclusive_refuses()
            observed.append("check")
            return checked(project, expected)
        with self.fixtures(child), mock.patch.object(first_project, "check", side_effect=check):
            result = first_project.run(self.agent, "leased")
        self.assertEqual(observed, ["child", "check"])
        self.assertEqual(result["status"], "predicates_passed")
        with guard.lease(self.agent, expected_sha256=pin, mode="exclusive"):
            pass


if __name__ == "__main__":
    unittest.main()
